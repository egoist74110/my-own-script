<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import Tag from '@/components/Tag.vue'
import {
  isTelegramTokenValid,
  POLLER_STATE_DESC,
  POLLER_STATE_LABEL,
  verifyFailHint,
  type TokenVerification,
  type ACLGroup,
  type ACLMember,
  type ActivityItem,
} from './api'
import TelegramAiBotsCard from './TelegramAiBotsCard.vue'
import TelegramEnableSheet from './TelegramEnableSheet.vue'
import TelegramGroupDeleteSheet from './TelegramGroupDeleteSheet.vue'
import TelegramGroupEditSheet from './TelegramGroupEditSheet.vue'
import TelegramMemberEditSheet from './TelegramMemberEditSheet.vue'
import TelegramStatusPill from './TelegramStatusPill.vue'
import { fmtLocal } from './format'
import { settingsContextKey } from './useSettings'

const ctx = inject(settingsContextKey)!

// 基础数据
const t = computed(() => ctx.telegram.data.value ?? null)
const bot = computed(() => t.value?.bot ?? null)
const poller = computed(() => t.value?.poller ?? null)
const owner = computed(() => t.value?.owner ?? null)
const notify = computed(() => t.value?.notify ?? null)
const acl = computed(() => t.value?.acl ?? null)
const groups = computed(() => (acl.value?.groups ?? []) as ACLGroup[])
const members = computed(() => (acl.value?.members ?? []) as ACLMember[])
const legacyWhitelist = computed(() => (acl.value?.legacy_whitelist ?? []) as string[])
const allTasks = computed(() => ctx.tasks.data.value ?? [])

// --- Bot 卡片状态 ---
const tokenInput = ref('')
const tokenError = ref<string | null>(null)
const deleteTokenConfirm = ref(false)

// --- Token 校验与身份 ---
// 本地保存最近一次 mutation 响应里的 verify，overview 刷新后以持久化字段为准。
const localVerify = ref<TokenVerification | null>(null)
const tokenPresent = computed(() => Boolean(bot.value?.credential.present))
const verifiedBot = computed(() => t.value?.control.verified_bot ?? bot.value?.verified_bot ?? null)
const verify = computed<TokenVerification | null>(() =>
  tokenPresent.value
    ? (localVerify.value ?? bot.value?.verify ?? t.value?.control.token_verify ?? null)
    : null,
)
const botUsername = computed(() => verifiedBot.value?.username || bot.value?.username || null)
const botId = computed(
  () => verifiedBot.value?.id || bot.value?.bot_id || t.value?.control.bot_id || null,
)
// 已校验有效：最近一次校验成功；没有校验记录但存在已验证身份（旧数据）也视为有效。
const tokenVerified = computed(
  () => tokenPresent.value && (verify.value ? verify.value.ok : Boolean(verifiedBot.value)),
)
const verifyFailed = computed(() => verify.value !== null && !verify.value.ok)
const hasWebhook = computed(() => verify.value?.has_webhook === true)
const identityPlaceholder = computed(() => (tokenPresent.value ? '未校验' : '—'))
const showEnableGuide = computed(() => tokenVerified.value && !t.value?.control.enabled)
const atName = computed(() => (botUsername.value ? `@${botUsername.value.replace(/^@/, '')}` : ''))

watch(tokenPresent, (p) => {
  if (!p) localVerify.value = null
})

/** 保存/导入后根据 verify 结果给出整页提示（不再只说“已导入”）。 */
function noticeAfterToken(what: string, v: TokenVerification | undefined) {
  localVerify.value = v ?? null
  if (!v) return
  if (v.ok) {
    const who = botUsername.value ? `@${botUsername.value.replace(/^@/, '')}` : '机器人'
    ctx.notice.value = { kind: 'ok', text: `${what}，Token 有效：${who}` }
  } else {
    ctx.notice.value = { kind: 'warn', text: `${what}，但 Token 校验失败：${v.message}` }
  }
}

async function onVerifyToken() {
  tokenError.value = null
  const res = await ctx.verifyTelegramToken((err) => {
    if (err.code === 'no_credential') {
      tokenError.value = '未保存 Bot Token，请先录入或导入 Token'
      return true
    }
    return false
  })
  if (res.ok && res.data?.verify) localVerify.value = res.data.verify
}

async function onSaveToken() {
  tokenError.value = null
  const val = tokenInput.value.trim()
  if (!isTelegramTokenValid(val)) {
    tokenInput.value = ''
    tokenError.value = 'Token 格式不正确（需为 <数字id>:<字符串>）'
    return
  }
  tokenInput.value = '' // 提交后立即清空输入框，永不回显
  const res = await ctx.putTelegramToken(val, (err) => {
    if (err.status === 422 || err.code === 'validation_error') {
      tokenError.value = 'Token 格式不正确'
      return true
    }
    if (err.code === 'telegram_active') {
      tokenError.value = 'Telegram 正在运行中，无法修改 Token，请先停用'
      return true
    }
    return false
  })
  if (res.ok) noticeAfterToken('Bot Token 已保存', res.data?.verify)
}

async function onImportLegacyToken() {
  tokenError.value = null
  const res = await ctx.importLegacyTelegramToken((err) => {
    if (err.code === 'legacy_missing' || err.status === 404) {
      ctx.notice.value = { kind: 'warn', text: '旧应用中未找到 Telegram Bot Token' }
      return true
    }
    if (err.code === 'telegram_active') {
      ctx.notice.value = {
        kind: 'error',
        text: 'Telegram 正在运行中，无法导入 Token，请先停用',
      }
      return true
    }
    return false
  })
  if (res.ok) noticeAfterToken('已从旧应用导入 Bot Token', res.data?.verify)
}

async function onConfirmDeleteToken() {
  deleteTokenConfirm.value = false
  await ctx.deleteTelegramToken((err) => {
    if (err.code === 'telegram_active') {
      ctx.notice.value = {
        kind: 'error',
        text: 'Telegram 正在运行中，无法删除 Token，请先停用',
      }
      return true
    }
    return false
  })
}

// --- 接管卡片状态 ---
const enableSheetOpen = ref(false)
const enableError = ref<string | null>(null)
const webhookSetDetected = ref(false)

function openEnableSheet() {
  enableError.value = null
  webhookSetDetected.value = false
  enableSheetOpen.value = true
}

function onToggleControl(val: boolean) {
  if (val) {
    openEnableSheet()
  } else {
    void ctx.disableTelegram()
  }
}

async function onConfirmEnable(opts: { ackOldBotStopped: boolean; deleteWebhook: boolean }) {
  enableError.value = null
  const res = await ctx.enableTelegram(opts.ackOldBotStopped, opts.deleteWebhook, (err) => {
    if (err.code === 'webhook_set') {
      webhookSetDetected.value = true
      enableError.value = '检测到已设置 Webhook，需勾选二次确认删除 Webhook'
      return true
    }
    if (err.code === 'ack_required') {
      enableError.value = '必须确认旧应用已停止轮询'
      return true
    }
    if (err.code === 'no_credential') {
      enableError.value = '未保存 Bot Token，请先录入或导入 Token'
      return true
    }
    if (err.code === 'telegram_active') {
      enableError.value = 'Telegram 已在运行中。请先在“远程控制”里停用，再重新启用'
      return true
    }
    if (err.code === 'telegram_request_failed' || err.code === 'telegram_unreachable') {
      enableError.value = `${err.message}。请检查网络或代理后，点“确认启用”重试`
      return true
    }
    if (err.code === 'token_invalid') {
      enableError.value = 'Token 无效或已被撤销，请关闭此窗口后重新录入 Token'
      return true
    }
    enableError.value = err.message
    return true
  })
  if (res.ok) {
    enableSheetOpen.value = false
    const st = t.value?.poller.state
    if (st && ['conflict', 'token_invalid', 'webhook_set', 'store_unavailable'].includes(st)) {
      ctx.notice.value = {
        kind: 'warn',
        text: `已启用，但连接状态为“${POLLER_STATE_LABEL[st]}”：${POLLER_STATE_DESC[st] ?? ''}`,
      }
    }
  } else if (!enableError.value && res.error) {
    // revision_conflict 等由 act 统一处理的错误：也要在 Sheet 内可见，不能静默失败
    enableError.value =
      res.error.code === 'revision_conflict'
        ? '配置已被其他窗口或进程更新，已刷新为最新内容。请确认后再点“确认启用”重试'
        : res.error.message
  }
}

async function onRetryTakeover() {
  await ctx.retryTelegram()
}

// --- Owner 卡片状态 ---
const bindCode = ref<string | null>(null)
const bindCodeExpiresAt = ref<number | null>(null)
const bindCountdown = ref('')
const unbindConfirm = ref(false)
let bindTimer: ReturnType<typeof setInterval> | null = null

function updateCountdown() {
  if (!bindCodeExpiresAt.value) {
    bindCountdown.value = ''
    return
  }
  const rem = Math.max(0, Math.floor((bindCodeExpiresAt.value - Date.now()) / 1000))
  if (rem === 0) {
    bindCountdown.value = '已过期'
  } else {
    const m = Math.floor(rem / 60)
    const s = rem % 60
    bindCountdown.value = `${m}:${s < 10 ? '0' : ''}${s}`
  }
}

async function onCreateBindCode() {
  const res = await ctx.createBindCode()
  if (res.ok && res.data) {
    bindCode.value = res.data.code
    bindCodeExpiresAt.value = Date.parse(res.data.expires_at)
    updateCountdown()
    if (bindTimer) clearInterval(bindTimer)
    bindTimer = setInterval(updateCountdown, 1000)
  }
}

async function onConfirmUnbind() {
  unbindConfirm.value = false
  await ctx.unbindOwner()
}

watch(
  () => owner.value?.bound,
  (bound) => {
    if (bound) {
      bindCode.value = null
      bindCodeExpiresAt.value = null
      if (bindTimer) {
        clearInterval(bindTimer)
        bindTimer = null
      }
    }
  },
)

onUnmounted(() => {
  if (bindTimer) clearInterval(bindTimer)
})

// --- 通知卡片 ---
function onToggleNotifyDetails(val: boolean) {
  void ctx.patchTelegramSettings({ include_details: val })
}

function onToggleNotifyUiRuns(val: boolean) {
  void ctx.patchTelegramSettings({ ui_runs_to_owner: val })
}

// --- 测试消息 ---
const canTestMessage = computed(() => Boolean(t.value?.control.enabled && owner.value?.bound))

async function onSendTestMessage() {
  if (!canTestMessage.value) return
  await ctx.sendTestMessage()
}

// --- 权限组卡片 ---
const groupEditOpen = ref(false)
const groupToDelete = ref<ACLGroup | null>(null)
const groupToEdit = ref<ACLGroup | null>(null)
const groupEditError = ref<string | null>(null)

function onNewGroup() {
  groupToEdit.value = null
  groupEditError.value = null
  groupEditOpen.value = true
}

function onEditGroup(g: ACLGroup) {
  groupToEdit.value = g
  groupEditError.value = null
  groupEditOpen.value = true
}

async function onSaveGroup(data: {
  name: string
  can_run: boolean
  can_stop: boolean
  can_status: boolean
  can_rollback: boolean
  task_ids: string[]
}) {
  groupEditError.value = null
  if (groupToEdit.value) {
    const res = await ctx.patchAclGroup(groupToEdit.value.id, data, (err) => {
      groupEditError.value = err.message
      return true
    })
    if (res.ok) groupEditOpen.value = false
    else if (!groupEditError.value && res.error) groupEditError.value = res.error.message
  } else {
    const res = await ctx.createAclGroup(data, (err) => {
      groupEditError.value = err.message
      return true
    })
    if (res.ok) groupEditOpen.value = false
    else if (!groupEditError.value && res.error) groupEditError.value = res.error.message
  }
}

async function onConfirmDeleteGroup() {
  if (!groupToDelete.value) return
  const id = groupToDelete.value.id
  groupToDelete.value = null
  await ctx.deleteAclGroup(id)
}

function taskNamesOfGroup(g: ACLGroup): string {
  if (!g.task_ids || g.task_ids.length === 0) return '—'
  return g.task_ids
    .map((tid) => {
      const task = allTasks.value.find((x) => x.id === tid)
      return task ? task.name : tid
    })
    .join('，')
}

function getGroupWarnings(g: ACLGroup, idx: number): string[] {
  const list: string[] = []
  const prefix = `ACL 组 #${idx + 1}`
  for (const w of t.value?.warnings ?? []) {
    if (
      w.startsWith(prefix) ||
      (w.includes('该组已无可运行任务') &&
        (g.can_run || g.can_rollback) &&
        (!g.task_ids || g.task_ids.length === 0))
    ) {
      list.push(w)
    }
  }
  const missing = (g.task_ids ?? []).filter(
    (tid) => !allTasks.value.some((task) => task.id === tid),
  )
  if (missing.length > 0 && !list.some((w) => w.includes('引用不存在的任务'))) {
    list.push(`引用不存在的任务: ${missing.join(', ')}`)
  }
  if (
    (g.can_run || g.can_rollback) &&
    (!g.task_ids || g.task_ids.length === 0) &&
    !list.some((w) => w.includes('无可运行任务'))
  ) {
    list.push('该组已无可运行任务')
  }
  return list
}

function getMemberWarnings(_m: ACLMember, idx: number): string[] {
  const list: string[] = []
  const prefix = `ACL 成员 #${idx + 1}`
  for (const w of t.value?.warnings ?? []) {
    if (w.startsWith(prefix)) {
      list.push(w)
    }
  }
  return list
}

function getWhitelistWarnings(_item: string, idx: number): string[] {
  const list: string[] = []
  const prefix = `旧白名单 #${idx + 1}`
  for (const w of t.value?.warnings ?? []) {
    if (w.startsWith(prefix)) {
      list.push(w)
    }
  }
  return list
}

// --- 组成员卡片 ---
const memberEditOpen = ref(false)
const memberToDelete = ref<ACLMember | null>(null)
const memberToEdit = ref<ACLMember | null>(null)
const memberEditError = ref<string | null>(null)

function onNewMember() {
  memberToEdit.value = null
  memberEditError.value = null
  memberEditOpen.value = true
}

function onEditMember(m: ACLMember) {
  memberToEdit.value = m
  memberEditError.value = null
  memberEditOpen.value = true
}

async function onSaveMember(data: {
  group_id: string
  label: string
  chat_id: string | null
  username: string | null
}) {
  memberEditError.value = null
  if (memberToEdit.value) {
    const res = await ctx.patchAclMember(memberToEdit.value.id, data, (err) => {
      memberEditError.value = err.message
      return true
    })
    if (res.ok) memberEditOpen.value = false
    else if (!memberEditError.value && res.error) memberEditError.value = res.error.message
  } else {
    const res = await ctx.createAclMember(data, (err) => {
      memberEditError.value = err.message
      return true
    })
    if (res.ok) memberEditOpen.value = false
    else if (!memberEditError.value && res.error) memberEditError.value = res.error.message
  }
}

async function onConfirmDeleteMember() {
  if (!memberToDelete.value) return
  const id = memberToDelete.value.id
  memberToDelete.value = null
  await ctx.deleteAclMember(id)
}

function groupOf(m: ACLMember): ACLGroup | undefined {
  return groups.value.find((x) => x.id === m.group_id)
}

function groupNameOfMember(gid: string): string {
  const g = groups.value.find((x) => x.id === gid)
  return g ? g.name : gid
}

// --- 旧白名单 ---
const whitelistDraft = ref('')
const whitelistEditing = ref(false)

function startEditWhitelist() {
  whitelistDraft.value = legacyWhitelist.value.join('\n')
  whitelistEditing.value = true
}

async function onSaveWhitelist() {
  const lines = whitelistDraft.value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  const res = await ctx.putLegacyWhitelist(lines)
  if (res.ok) whitelistEditing.value = false
}

// --- 最近活动列表 ---
const activities = ref<ActivityItem[]>([])
const loadingActivity = ref(false)

async function refreshActivity() {
  loadingActivity.value = true
  try {
    activities.value = (await ctx.getTelegramActivity(50)) ?? []
  } catch {
    // 忽略加载异常
    activities.value = []
  } finally {
    loadingActivity.value = false
  }
}

onMounted(() => {
  ctx.telegramTabActive.value = true
  void refreshActivity()
})

onUnmounted(() => {
  ctx.telegramTabActive.value = false
  if (bindTimer) clearInterval(bindTimer)
})
</script>

<template>
  <div class="st-body" data-testid="telegram-tab">
    <!-- 失败次数警告 Banner -->
    <Banner
      v-if="poller && poller.consecutive_failures >= 10"
      kind="warn"
      role="alert"
      data-testid="poller-failure-banner"
    >
      连续轮询失败已达 {{ poller.consecutive_failures }} 次，请检查网络连接或代理设置。
    </Banner>

    <!-- GET 返回的 warnings 提示 -->
    <Banner
      v-if="t && t.warnings && t.warnings.length > 0"
      kind="warn"
      role="alert"
      data-testid="telegram-warnings-banner"
    >
      <span>Telegram 配置存在需要关注的警告：</span>
      <ul class="st-list mt-1">
        <li v-for="w in t.warnings" :key="w">{{ w }}</li>
      </ul>
    </Banner>

    <!-- 启用引导：Token 已验证但远程控制未启用 -->
    <Banner v-if="showEnableGuide" kind="warn" data-testid="enable-guide-banner">
      <span>
        Token 已验证{{
          atName ? `（${atName}）` : ''
        }}，但远程控制还没启用，机器人现在不会响应任何命令。
      </span>
      <template #actions>
        <Button
          variant="primary"
          data-testid="enable-guide-btn"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="openEnableSheet"
        >
          启用远程控制
        </Button>
      </template>
    </Banner>

    <!-- 1. Bot 卡片 -->
    <section class="st-section" aria-label="Bot 配置" data-testid="bot-card">
      <div class="st-head">
        <h2>机器人</h2>
        <span class="st-grow"></span>
        <Button
          data-testid="import-legacy-token-btn"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="onImportLegacyToken"
        >
          从旧应用导入
        </Button>
      </div>

      <p class="st-note">Bot Token 只存在钥匙串里，界面不会回显；提交后输入框立即清空。</p>

      <dl class="st-kv">
        <dt>Token</dt>
        <dd data-testid="token-present-status">
          <Tag :tone="bot?.credential.present ? 'ok' : 'neutral'">
            {{ bot?.credential.present ? '已保存' : '未保存' }}
          </Tag>
          <span v-if="bot?.credential.source" class="src-text">
            （{{
              bot.credential.source === 'imported'
                ? '从旧版导入'
                : bot.credential.source === 'manual'
                  ? '手动录入'
                  : '未知'
            }}）
          </span>
        </dd>
        <dt>机器人账号</dt>
        <dd class="st-mono" data-testid="bot-username">
          {{ atName || identityPlaceholder }}
        </dd>
        <dt>Bot ID</dt>
        <dd class="st-mono" data-testid="bot-id">{{ botId || identityPlaceholder }}</dd>
        <template v-if="tokenPresent">
          <dt>Token 校验</dt>
          <dd data-testid="token-verify-status">
            <template v-if="verify?.ok">
              <Tag tone="ok" data-testid="token-verify-ok">
                Token 有效{{ atName ? `：${atName}` : '' }}
              </Tag>
            </template>
            <template v-else-if="verifyFailed">
              <Tag tone="neutral" data-testid="token-verify-failed">校验失败</Tag>
            </template>
            <template v-else>
              <Tag tone="neutral" data-testid="token-verify-unchecked">未校验</Tag>
            </template>
            <Button
              size="sm"
              data-testid="verify-token-btn"
              class="verify-btn"
              :disabled="ctx.busy.value || !ctx.writable.value"
              @click="onVerifyToken"
            >
              {{ verifyFailed ? '重新检查' : '检查 Token' }}
            </Button>
          </dd>
        </template>
      </dl>
      <Banner
        v-if="verifyFailed && verify"
        kind="error"
        class="mt-2"
        data-testid="token-verify-error"
      >
        {{ verify.message }}{{ verifyFailHint(verify.code) }}
      </Banner>
      <Banner v-if="hasWebhook" kind="warn" class="mt-2" data-testid="token-webhook-note">
        这个 Bot 设置了 webhook，启用时会询问是否删除。
      </Banner>

      <!-- Token 输入表单 -->
      <div class="token-form">
        <div class="st-fld">
          <label class="lbl" for="bot-token-input">录入 Token</label>
          <div class="token-inputs">
            <input
              id="bot-token-input"
              v-model="tokenInput"
              type="password"
              autocomplete="new-password"
              placeholder="格式为 <数字id>:<密钥字符串>"
              class="st-select token-pw-input"
              data-testid="token-input"
              :disabled="ctx.busy.value || !ctx.writable.value"
              @keydown.enter.prevent="onSaveToken"
            />
            <Button
              variant="primary"
              data-testid="save-token-btn"
              :disabled="ctx.busy.value || !ctx.writable.value || !tokenInput.trim()"
              @click="onSaveToken"
            >
              保存 Token
            </Button>
            <Button
              v-if="bot?.credential.present"
              variant="destructive"
              data-testid="delete-token-btn"
              :disabled="ctx.busy.value || !ctx.writable.value"
              @click="deleteTokenConfirm = true"
            >
              删除 Token
            </Button>
          </div>
        </div>
        <p v-if="tokenError" class="st-warn token-err" data-testid="token-error-msg">
          {{ tokenError }}
        </p>
      </div>
    </section>

    <!-- 2. 接管卡片 -->
    <section class="st-section" aria-label="接管与轮询" data-testid="takeover-card">
      <div class="st-head">
        <h2>远程控制</h2>
      </div>

      <div class="st-row">
        <div class="st-lbl">
          <b>用 Telegram 控制任务</b>
          <small>关闭时机器人不接收任何命令</small>
        </div>
        <Switch
          :model-value="Boolean(t?.control.enabled)"
          data-testid="telegram-control-switch"
          aria-label="用 Telegram 控制任务"
          :disabled="ctx.busy.value || !ctx.writable.value || !bot?.credential.present"
          @update:model-value="(val: boolean) => onToggleControl(val)"
        />
      </div>

      <div class="st-row">
        <div class="st-lbl">
          <b>连接状态</b>
          <small>机器人与 Telegram 服务器的连接</small>
        </div>
        <TelegramStatusPill v-if="poller" :state="poller.state" data-testid="poller-status-pill" />
        <Button
          v-if="poller && (poller.state === 'conflict' || poller.state === 'backoff')"
          variant="default"
          data-testid="retry-poller-btn"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="onRetryTakeover"
        >
          重试接管
        </Button>
      </div>

      <!-- 状态补充说明 -->
      <div v-if="poller && POLLER_STATE_DESC[poller.state]" class="poller-desc st-free">
        <Banner
          :kind="poller.state === 'conflict' ? 'error' : 'warn'"
          data-testid="poller-state-desc-banner"
        >
          {{ POLLER_STATE_DESC[poller.state] }}
        </Banner>
      </div>
      <p v-else-if="poller?.state === 'backoff'" class="st-note" data-testid="poller-backoff-note">
        {{
          poller.last_error_category
            ? `网络异常（${poller.last_error_category}），正在等待指数退避重试…`
            : '正在等待指数退避重试…'
        }}
      </p>
    </section>

    <!-- 2b. AI 专属机器人卡片组 -->
    <TelegramAiBotsCard :busy="ctx.busy.value" :writable="ctx.writable.value" />

    <!-- 3. Owner 卡片 -->
    <section class="st-section" aria-label="所有者设置" data-testid="owner-card">
      <div class="st-head">
        <h2>所有者</h2>
        <Tag :tone="owner?.bound ? 'ok' : 'neutral'">{{ owner?.bound ? '已绑定' : '未绑定' }}</Tag>
        <span class="st-grow"></span>
        <Button
          v-if="owner?.bound"
          variant="destructive"
          data-testid="unbind-owner-btn"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="unbindConfirm = true"
        >
          解除绑定
        </Button>
      </div>

      <dl v-if="owner?.bound" class="st-kv">
        <dt>Chat ID</dt>
        <dd class="st-mono" data-testid="owner-chat-id">{{ owner.chat_id }}</dd>
        <dt>绑定方式</dt>
        <dd data-testid="owner-source">
          {{ owner.source === 'imported' ? '从旧版导入' : '用绑定码绑定' }}
        </dd>
      </dl>
      <div v-else class="owner-unbound-box" data-testid="owner-unbound-box">
        <p class="st-note">
          还没有绑定所有者。生成绑定码后，在 Telegram 里私聊机器人发送它即可绑定。
        </p>
        <div v-if="!bindCode" class="mt-2">
          <Button
            variant="primary"
            data-testid="create-bind-code-btn"
            :disabled="ctx.busy.value || !ctx.writable.value"
            @click="onCreateBindCode"
          >
            生成绑定码
          </Button>
        </div>
        <div v-else class="bind-code-card mt-2" data-testid="bind-code-card">
          <div class="bind-code-line">
            <span class="code-title">一次性绑定码</span>
            <span class="bind-code-val st-mono" data-testid="bind-code-display">{{
              bindCode
            }}</span>
            <span class="bind-countdown" data-testid="bind-code-countdown">
              剩余 {{ bindCountdown }}
            </span>
          </div>
          <p class="bind-instruction">
            请在 Telegram 中向当前机器人私聊发送：
            <code class="bind-cmd">/bind {{ bindCode }}</code>
          </p>
          <Button
            v-if="bindCountdown === '已过期'"
            data-testid="regen-bind-code-btn"
            @click="onCreateBindCode"
          >
            重新生成绑定码
          </Button>
        </div>
      </div>
    </section>

    <!-- 4. 通知卡片 -->
    <section class="st-section" aria-label="通知设置" data-testid="notify-card">
      <div class="st-head">
        <h2>任务运行结果通知</h2>
      </div>
      <div class="st-row">
        <div class="st-lbl">
          <b>通知里带上详细信息</b>
          <small>打开后包含分支、目标和 Release 链接；默认只发操作和结果摘要</small>
        </div>
        <Switch
          :model-value="Boolean(notify?.include_details)"
          data-testid="notify-details-switch"
          aria-label="通知里带上详细信息"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @update:model-value="(val: boolean) => onToggleNotifyDetails(val)"
        />
      </div>
      <div class="st-row">
        <div class="st-lbl">
          <b>在桌面应用里运行也通知我</b>
          <small>在桌面应用里启动的任务，完成后同样向所有者发 Telegram 通知</small>
        </div>
        <Switch
          :model-value="Boolean(notify?.ui_runs_to_owner)"
          data-testid="notify-ui-runs-switch"
          aria-label="在桌面应用里运行也通知我"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @update:model-value="(val: boolean) => onToggleNotifyUiRuns(val)"
        />
      </div>
    </section>

    <!-- 5. 测试消息 -->
    <section class="st-section" aria-label="测试消息" data-testid="test-message-card">
      <div class="st-head">
        <h2>测试消息</h2>
        <span class="st-grow"></span>
        <Button
          data-testid="send-test-message-btn"
          :disabled="ctx.busy.value || !canTestMessage"
          @click="onSendTestMessage"
        >
          发送测试消息
        </Button>
      </div>
      <p class="st-note" data-testid="test-message-hint">
        {{
          canTestMessage
            ? '向所有者发一条固定的测试文字，确认机器人能正常发消息。'
            : '需要先打开「用 Telegram 控制任务」并绑定所有者，才能发送测试消息。'
        }}
      </p>
    </section>

    <!-- 7. 组成员卡片 -->
    <section class="st-section" aria-label="谁能用机器人" data-testid="acl-members-card">
      <div class="st-head">
        <h2>谁能用机器人</h2>
        <Tag>{{ members.length }}</Tag>
        <span class="st-grow"></span>
        <Button
          variant="primary"
          data-testid="create-member-btn"
          :disabled="ctx.busy.value || !ctx.writable.value || groups.length === 0"
          @click="onNewMember"
        >
          ＋ 添加成员
        </Button>
      </div>

      <p class="st-note">成员按组授权。只填了用户名的成员，第一次给机器人发消息后会自动绑定。</p>
      <div class="st-tw">
        <table class="st-tbl" data-testid="acl-members-table">
          <thead>
            <tr>
              <th scope="col">成员</th>
              <th scope="col">用户名</th>
              <th scope="col">组</th>
              <th scope="col">权限</th>
              <th scope="col">绑定状态</th>
              <th scope="col"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, idx) in members" :key="m.id" :data-testid="`member-row-${m.id}`">
              <td>
                <div>{{ m.label || '—' }}</div>
                <div
                  v-for="w in getMemberWarnings(m, idx)"
                  :key="w"
                  class="inline-warn"
                  data-testid="member-inline-warning"
                >
                  ⚠ {{ w }}
                </div>
              </td>
              <td class="st-mono">
                <span v-if="m.username">@{{ m.username.replace(/^@/, '') }}</span>
                <span v-if="m.username && m.chat_id"> / </span>
                <span v-if="m.chat_id">{{ m.chat_id }}</span>
                <span v-if="!m.username && !m.chat_id">—</span>
              </td>
              <td>{{ groupNameOfMember(m.group_id) }}</td>
              <td>
                <div class="st-tags">
                  <Tag v-if="groupOf(m)?.can_run" tone="ok">执行</Tag>
                  <Tag v-if="groupOf(m)?.can_stop">停止</Tag>
                  <Tag v-if="groupOf(m)?.can_status">状态</Tag>
                  <Tag v-if="groupOf(m)?.can_rollback" tone="warn">回滚</Tag>
                </div>
              </td>
              <td>
                <span v-if="m.username">
                  <Tag :tone="m.user_id ? 'ok' : 'neutral'">
                    {{ m.user_id ? '已绑定' : '待绑定' }}
                  </Tag>
                </span>
                <span v-else class="st-note">—</span>
              </td>
              <td>
                <div class="st-actions">
                  <Button
                    data-testid="edit-member-btn"
                    :disabled="ctx.busy.value || !ctx.writable.value"
                    @click="onEditMember(m)"
                  >
                    编辑
                  </Button>
                  <Button
                    variant="destructive"
                    data-testid="delete-member-btn"
                    :disabled="ctx.busy.value || !ctx.writable.value"
                    @click="memberToDelete = m"
                  >
                    删除
                  </Button>
                </div>
              </td>
            </tr>
            <tr v-if="members.length === 0">
              <td colspan="6" class="st-note">还没有成员。先建好权限组，再添加成员。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 6. 权限组卡片 -->
    <section class="st-section" aria-label="权限组管理" data-testid="acl-groups-card">
      <div class="st-head">
        <h2>权限组</h2>
        <Tag>{{ groups.length }}</Tag>
        <span class="st-grow"></span>
        <Button
          variant="primary"
          data-testid="create-group-btn"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="onNewGroup"
        >
          ＋ 新建权限组
        </Button>
      </div>

      <p class="st-note">权限组决定成员能做什么：运行或回滚哪些任务、能否停止、能否查看状态。</p>
      <div class="st-tw">
        <table class="st-tbl" data-testid="acl-groups-table">
          <thead>
            <tr>
              <th scope="col">组</th>
              <th scope="col">权限</th>
              <th scope="col" class="wrap">可操作的任务</th>
              <th scope="col"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(g, idx) in groups" :key="g.id" :data-testid="`group-row-${g.id}`">
              <td class="font-bold">
                <div>{{ g.name }}</div>
                <div
                  v-for="w in getGroupWarnings(g, idx)"
                  :key="w"
                  class="inline-warn"
                  data-testid="group-inline-warning"
                >
                  ⚠ {{ w }}
                </div>
              </td>
              <td>
                <div class="st-tags">
                  <Tag v-if="g.can_run" tone="ok">执行</Tag>
                  <Tag v-if="g.can_stop">停止</Tag>
                  <Tag v-if="g.can_status">状态</Tag>
                  <Tag v-if="g.can_rollback" tone="warn">回滚</Tag>
                </div>
              </td>
              <td class="wrap">
                <span class="task-summary">{{ taskNamesOfGroup(g) }}</span>
              </td>
              <td>
                <div class="st-actions">
                  <Button
                    data-testid="edit-group-btn"
                    :disabled="ctx.busy.value || !ctx.writable.value"
                    @click="onEditGroup(g)"
                  >
                    编辑
                  </Button>
                  <Button
                    variant="destructive"
                    data-testid="delete-group-btn"
                    :disabled="ctx.busy.value || !ctx.writable.value"
                    @click="groupToDelete = g"
                  >
                    删除
                  </Button>
                </div>
              </td>
            </tr>
            <tr v-if="groups.length === 0">
              <td colspan="4" class="st-note">还没有权限组。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 8. 旧白名单卡片 -->
    <section class="st-section" aria-label="旧白名单" data-testid="legacy-whitelist-card">
      <div class="st-head">
        <h2>旧版白名单</h2>
        <Tag>{{ legacyWhitelist.length }}</Tag>
        <span class="st-grow"></span>
        <Button
          v-if="!whitelistEditing"
          data-testid="edit-whitelist-btn"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="startEditWhitelist"
        >
          编辑白名单
        </Button>
      </div>

      <p class="st-note">
        从旧应用迁移过来的名单，只能用 <code>/status</code> 查看状态，不能运行任务。
      </p>

      <div v-if="!whitelistEditing" class="whitelist-view">
        <div v-if="legacyWhitelist.length > 0" class="st-tags" data-testid="whitelist-tags">
          <div v-for="(item, idx) in legacyWhitelist" :key="item" class="whitelist-item-row">
            <Tag class="st-mono">{{ item }}</Tag>
            <span
              v-for="w in getWhitelistWarnings(item, idx)"
              :key="w"
              class="inline-warn"
              data-testid="whitelist-inline-warning"
            >
              ⚠ {{ w }}
            </span>
          </div>
        </div>
        <p v-else class="st-note">没有旧版白名单条目。</p>
      </div>

      <div v-else class="whitelist-editor">
        <textarea
          v-model="whitelistDraft"
          rows="4"
          placeholder="每行输入一个 chat_id 或 @username"
          class="st-select whitelist-textarea st-mono"
          data-testid="whitelist-textarea"
          :disabled="ctx.busy.value"
        />
        <div class="st-actions mt-2">
          <Button :disabled="ctx.busy.value" @click="whitelistEditing = false">取消</Button>
          <Button
            variant="primary"
            data-testid="save-whitelist-btn"
            :disabled="ctx.busy.value"
            @click="onSaveWhitelist"
          >
            保存白名单
          </Button>
        </div>
      </div>
    </section>

    <!-- 9. 最近活动卡片 -->
    <section class="st-section" aria-label="最近活动" data-testid="recent-activity-card">
      <div class="st-head">
        <h2>最近活动</h2>
        <span class="st-grow"></span>
        <Button
          data-testid="refresh-activity-btn"
          :disabled="loadingActivity"
          @click="refreshActivity"
        >
          {{ loadingActivity ? '刷新中…' : '刷新活动' }}
        </Button>
      </div>

      <p class="st-note">机器人最近收到并处理的指令和按钮回调。只记录元数据，不记录消息正文。</p>

      <div class="st-tw">
        <table class="st-tbl" data-testid="activity-table">
          <thead>
            <tr>
              <th scope="col">时间</th>
              <th scope="col">类型</th>
              <th scope="col">指令/回调</th>
              <th scope="col">Chat ID</th>
              <th scope="col">状态</th>
              <th scope="col" class="wrap">说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(act, idx) in activities" :key="idx" :data-testid="`activity-row-${idx}`">
              <td class="st-mono text-sub">{{ fmtLocal(act.received_at) }}</td>
              <td>{{ act.kind }}</td>
              <td class="st-mono">{{ act.command || '—' }}</td>
              <td class="st-mono">{{ act.chat_id || '—' }}</td>
              <td>
                <Tag
                  :tone="
                    act.status === 'handled' ? 'ok' : act.status === 'failed' ? 'warn' : 'neutral'
                  "
                >
                  {{ act.status }}
                </Tag>
              </td>
              <td class="wrap">{{ act.reason || '—' }}</td>
            </tr>
            <tr v-if="!activities || activities.length === 0">
              <td colspan="6" class="st-note">还没有活动记录。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Sheets -->
    <TelegramEnableSheet
      v-model:open="enableSheetOpen"
      :submitting="ctx.busy.value"
      :error="enableError"
      :webhook-set="webhookSetDetected || hasWebhook"
      @confirm="onConfirmEnable"
    />

    <TelegramGroupEditSheet
      v-model:open="groupEditOpen"
      :group="groupToEdit"
      :all-tasks="allTasks"
      :submitting="ctx.busy.value"
      :error="groupEditError"
      @save="onSaveGroup"
    />

    <TelegramGroupDeleteSheet
      :open="Boolean(groupToDelete)"
      :group="groupToDelete"
      :members="members"
      :submitting="ctx.busy.value"
      @update:open="
        (val) => {
          if (!val) groupToDelete = null
        }
      "
      @confirm="onConfirmDeleteGroup"
    />

    <TelegramMemberEditSheet
      v-model:open="memberEditOpen"
      :member="memberToEdit"
      :groups="groups"
      :submitting="ctx.busy.value"
      :error="memberEditError"
      @save="onSaveMember"
    />

    <Sheet
      :open="Boolean(memberToDelete)"
      :title="`确认删除成员「${memberToDelete?.label || memberToDelete?.username || memberToDelete?.chat_id}」？`"
      description="删除成员后该 Telegram 用户将失去该权限组的权限。"
      @update:open="
        (val) => {
          if (!val) memberToDelete = null
        }
      "
    >
      <p class="st-note">确认要将此成员从组中移除吗？</p>
      <template #actions>
        <Button :disabled="ctx.busy.value" @click="memberToDelete = null">取消</Button>
        <Button
          variant="destructive"
          data-testid="confirm-delete-member-btn"
          :disabled="ctx.busy.value"
          @click="onConfirmDeleteMember"
        >
          确认删除
        </Button>
      </template>
    </Sheet>

    <Sheet
      :open="unbindConfirm"
      title="确认解除所有者 (Owner) 绑定？"
      description="解除绑定后，当前绑定的 Telegram 账号将不再拥有 Owner 特权及通知接收资格。"
      @update:open="unbindConfirm = $event"
    >
      <p class="st-note">解绑后可通过重新生成绑定码绑定新的所有者。</p>
      <template #actions>
        <Button :disabled="ctx.busy.value" @click="unbindConfirm = false">取消</Button>
        <Button
          variant="destructive"
          data-testid="confirm-unbind-btn"
          :disabled="ctx.busy.value"
          @click="onConfirmUnbind"
        >
          确认解绑
        </Button>
      </template>
    </Sheet>

    <Sheet
      :open="deleteTokenConfirm"
      title="确认删除 Telegram Bot Token？"
      description="删除 Token 后将无法连接 Telegram。如已启用轮询需先停用。"
      @update:open="deleteTokenConfirm = $event"
    >
      <p class="st-note">确认从钥匙串中彻底清除当前 Bot Token 吗？</p>
      <template #actions>
        <Button :disabled="ctx.busy.value" @click="deleteTokenConfirm = false">取消</Button>
        <Button
          variant="destructive"
          data-testid="confirm-delete-token-btn"
          :disabled="ctx.busy.value"
          @click="onConfirmDeleteToken"
        >
          确认删除
        </Button>
      </template>
    </Sheet>
  </div>
</template>

<style scoped>
.poller-desc {
  margin-top: 8px;
}
.src-text {
  font-size: var(--text-sub);
  color: var(--mute);
  margin-left: 6px;
}
.token-inputs {
  display: flex;
  align-items: center;
  gap: 8px;
}
.token-pw-input {
  flex: 1;
  max-width: 380px;
}
.token-err {
  margin: 6px 0 0 126px;
  font-size: var(--text-sub);
}
.bind-code-card {
  background: var(--bg-inspector);
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bind-code-line {
  display: flex;
  align-items: center;
  gap: 10px;
}
.code-title {
  font-weight: 600;
}
.bind-code-val {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--ink);
  background: var(--bg-window);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--line);
}
.bind-countdown {
  font-size: var(--text-sub);
  color: var(--st-verify-fg);
  font-weight: 600;
}
.bind-instruction {
  margin: 0;
  font-size: var(--text-body);
}
.bind-cmd {
  font-family: var(--font-mono);
  background: var(--bg-window);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--line);
  font-weight: 600;
}
.task-summary {
  font-size: var(--text-sub);
  color: var(--ink);
}
.whitelist-textarea {
  width: 100%;
  box-sizing: border-box;
  font-size: var(--text-sub);
  padding: 8px;
  min-height: 80px;
}
.text-sub {
  font-size: var(--text-sub);
}
.mt-1 {
  margin-top: 4px;
}
.verify-btn {
  margin-left: 8px;
}
.mt-2 {
  margin-top: 8px;
}
.font-bold {
  font-weight: 600;
}
.inline-warn {
  font-size: var(--text-sub);
  color: var(--bn-warn-fg, #b45309);
  margin-top: 2px;
}
.whitelist-item-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
code {
  font-family: var(--font-mono);
}
</style>
