<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { RotateCcw } from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import Tag from '@/components/Tag.vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { TelegramStatusEventData } from '@/api/events'
import {
  deleteTelegramAiBotToken,
  disableTelegramAiBot,
  enableTelegramAiBot,
  fetchTelegramAiBots,
  importLegacyTelegramAiBotToken,
  putTelegramAiBotToken,
  retryTelegramAiBot,
  toApiError,
  type AIBotView,
} from '@/features/ai/api'
import { formatAiError } from '@/features/ai/terminal-protocol'
import { isTelegramTokenValid } from './api'
import TelegramAiBotEnableSheet from './TelegramAiBotEnableSheet.vue'
import TelegramStatusPill from './TelegramStatusPill.vue'
import { useBackendStore } from '@/stores/backend'

defineProps<{
  busy?: boolean
  writable?: boolean
}>()

const runtime = inject(backendRuntimeKey)
const queryClient = useQueryClient()
const store = useBackendStore()
const online = computed(() => store.connection === 'online')

const aiBotsQuery = useQuery({
  queryKey: ['telegram', 'ai-bots'],
  enabled: online,
  queryFn: async () => {
    const client = runtime?.api()
    if (!client) throw new Error('未连接后端')
    return fetchTelegramAiBots(client)
  },
  staleTime: 10000,
})

const bots = computed<AIBotView[]>(() => aiBotsQuery.data.value?.items ?? [])
const revision = computed(() => aiBotsQuery.data.value?.revision ?? 0)

// 实时 WS 状态更新映射表（key: slot，如 ai:claude_code）
const livePollerStates = ref<Record<string, { state: string; lastError?: string | null }>>({})

let removeWsListener: (() => void) | null = null

onMounted(() => {
  removeWsListener =
    runtime?.onEvent?.((envelope) => {
      if (envelope.type === 'telegram.status') {
        const data = envelope.data as unknown as TelegramStatusEventData
        const slot = data.slot || 'main'
        if (slot.startsWith('ai:')) {
          livePollerStates.value[slot] = {
            state: data.state,
            lastError: data.last_error_category,
          }
        }
      }
    }) ?? null
})

onBeforeUnmount(() => {
  removeWsListener?.()
})

function getEffectivePollerState(bot: AIBotView) {
  const live = livePollerStates.value[bot.slot]
  return (live?.state || bot.poller.state) as AIBotView['poller']['state']
}

// 机器人标题与描述
const BOT_META: Record<string, { name: string; desc: string }> = {
  claude_code: {
    name: 'Claude Code 机器人',
    desc: '专用于 Claude Code headless 交互与指令通知的专属 Telegram 机器人。',
  },
  codex: {
    name: 'Codex 机器人',
    desc: '专用于 OpenAI Codex 代码生成与会话交互的专属 Telegram 机器人。',
  },
  gemini: {
    name: 'Antigravity 机器人',
    desc: '专用于 Google Gemini / Antigravity CLI 交互的专属 Telegram 机器人。',
  },
}

// Token 表单状态（按 ai_id 隔离）
const tokenInputs = ref<Record<string, string>>({
  claude_code: '',
  codex: '',
  gemini: '',
})
const tokenErrors = ref<Record<string, string | null>>({
  claude_code: null,
  codex: null,
  gemini: null,
})
const botNotices = ref<Record<string, { kind: 'info' | 'warn' | 'error'; text: string } | null>>({
  claude_code: null,
  codex: null,
  gemini: null,
})

// 删除确认
const deleteTargetBot = ref<AIBotView | null>(null)

// 启用弹窗
const enableTargetBot = ref<AIBotView | null>(null)
const enableSubmitting = ref(false)
const enableError = ref<string | null>(null)

function invalidateBots() {
  void queryClient.invalidateQueries({ queryKey: ['telegram', 'ai-bots'] })
}

// 保存 Token
async function onSaveToken(aiId: 'claude_code' | 'codex' | 'gemini') {
  tokenErrors.value[aiId] = null
  botNotices.value[aiId] = null
  const val = (tokenInputs.value[aiId] || '').trim()
  if (!isTelegramTokenValid(val)) {
    tokenInputs.value[aiId] = ''
    tokenErrors.value[aiId] = 'Token 格式不正确（需为 <数字id>:<字符串>）'
    return
  }
  tokenInputs.value[aiId] = '' // 提交后立即清空，永不回显

  const client = runtime?.api()
  if (!client) return

  try {
    await putTelegramAiBotToken(client, aiId, val, revision.value)
    botNotices.value[aiId] = { kind: 'info', text: 'Token 保存成功' }
    invalidateBots()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    const code = (apiErr as { code?: string }).code
    if (code === 'telegram_active') {
      tokenErrors.value[aiId] = '机器人正在运行中，无法修改 Token，请先停用'
    } else {
      tokenErrors.value[aiId] = formatAiError(code, '保存 Token 失败')
    }
  }
}

// 导入旧版 Token
async function onImportLegacyToken(aiId: 'claude_code' | 'codex' | 'gemini') {
  tokenErrors.value[aiId] = null
  botNotices.value[aiId] = null
  const client = runtime?.api()
  if (!client) return

  try {
    await importLegacyTelegramAiBotToken(client, aiId, revision.value)
    botNotices.value[aiId] = { kind: 'info', text: '已从旧版应用成功导入 Token' }
    invalidateBots()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    const code = (apiErr as { code?: string }).code
    if (code === 'legacy_missing') {
      tokenErrors.value[aiId] = '旧版应用中未找到此机器人的 Token'
    } else if (code === 'telegram_active') {
      tokenErrors.value[aiId] = '机器人正在运行中，无法导入 Token，请先停用'
    } else {
      tokenErrors.value[aiId] = formatAiError(code, '导入旧版 Token 失败')
    }
  }
}

// 删除 Token
async function onConfirmDeleteToken() {
  if (!deleteTargetBot.value) return
  const aiId = deleteTargetBot.value.ai_id
  const client = runtime?.api()
  deleteTargetBot.value = null
  if (!client) return

  try {
    await deleteTelegramAiBotToken(client, aiId, revision.value)
    botNotices.value[aiId] = { kind: 'info', text: 'Token 已删除' }
    invalidateBots()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    const code = (apiErr as { code?: string }).code
    if (code === 'telegram_active') {
      tokenErrors.value[aiId] = '机器人正在运行中，无法删除 Token，请先停用'
    } else {
      tokenErrors.value[aiId] = formatAiError(code, '删除 Token 失败')
    }
  }
}

// 开关切换
function onToggleEnable(bot: AIBotView, val: boolean) {
  if (val) {
    enableError.value = null
    enableTargetBot.value = bot
  } else {
    void handleDisable(bot.ai_id)
  }
}

// 确认启用
async function onConfirmEnable(opts: { ackOldBotCleared: boolean; deleteWebhook: boolean }) {
  if (!enableTargetBot.value) return
  const aiId = enableTargetBot.value.ai_id
  const client = runtime?.api()
  if (!client) return

  enableSubmitting.value = true
  enableError.value = null
  try {
    await enableTelegramAiBot(client, aiId, {
      ack_old_bot_cleared: opts.ackOldBotCleared,
      delete_webhook: opts.deleteWebhook,
      revision: revision.value,
    })
    enableTargetBot.value = null
    botNotices.value[aiId] = { kind: 'info', text: '机器人已成功启用' }
    invalidateBots()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    const code = (apiErr as { code?: string }).code
    if (code === 'bot_in_use') {
      enableError.value = '此 Bot Token 已被其他槽位占用'
    } else if (code === 'ack_old_bot_cleared_required' || code === 'ack_required') {
      enableError.value = '必须确认已在旧版应用中清空对应 Token'
    } else {
      enableError.value = formatAiError(code, '启用机器人失败')
    }
  } finally {
    enableSubmitting.value = false
  }
}

// 停用
async function handleDisable(aiId: 'claude_code' | 'codex' | 'gemini') {
  const client = runtime?.api()
  if (!client) return
  try {
    await disableTelegramAiBot(client, aiId, revision.value)
    botNotices.value[aiId] = { kind: 'info', text: '机器人已停用' }
    invalidateBots()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    tokenErrors.value[aiId] = formatAiError((apiErr as { code?: string }).code, '停用机器人失败')
  }
}

// 重试
async function handleRetry(aiId: 'claude_code' | 'codex' | 'gemini') {
  const client = runtime?.api()
  if (!client) return
  try {
    await retryTelegramAiBot(client, aiId, revision.value)
    invalidateBots()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    tokenErrors.value[aiId] = formatAiError((apiErr as { code?: string }).code, '重试失败')
  }
}
</script>

<template>
  <div class="ai-bots-section" data-testid="telegram-ai-bots-section">
    <div class="section-title-row">
      <h2>AI 专属机器人</h2>
      <span class="st-note"
        >为 Claude Code、Codex 与 Gemini 配置独立专属的 Telegram 交互通道。</span
      >
    </div>

    <!-- 告警信息 -->
    <Banner
      v-if="aiBotsQuery.data.value?.warnings && aiBotsQuery.data.value.warnings.length > 0"
      kind="warn"
      class="mb-3"
      data-testid="ai-bots-warnings-banner"
    >
      <ul class="list-disc pl-4">
        <li v-for="w in aiBotsQuery.data.value.warnings" :key="w">{{ w }}</li>
      </ul>
    </Banner>

    <div class="bots-grid">
      <section
        v-for="b in bots"
        :key="b.ai_id"
        class="st-section ai-bot-card"
        :data-testid="`ai-bot-card-${b.ai_id}`"
      >
        <div class="st-head">
          <div class="flex items-center gap-2">
            <h3>{{ BOT_META[b.ai_id]?.name ?? b.ai_id }}</h3>
            <TelegramStatusPill :state="getEffectivePollerState(b)" />
          </div>
          <span class="st-grow"></span>

          <!-- 重试按钮（发生错误或 conflict 时显示） -->
          <Button
            v-if="
              getEffectivePollerState(b) === 'conflict' ||
              getEffectivePollerState(b) === 'backoff' ||
              getEffectivePollerState(b) === 'token_invalid'
            "
            variant="default"
            size="sm"
            data-testid="retry-ai-bot-btn"
            @click="handleRetry(b.ai_id)"
          >
            <RotateCcw :size="13" class="mr-1" /> 重试
          </Button>

          <!-- 启用开关 -->
          <div class="flex items-center gap-2 ml-2">
            <span class="text-xs text-neutral-500">{{
              b.control.enabled ? '已启用' : '已停用'
            }}</span>
            <Switch
              :model-value="Boolean(b.control.enabled)"
              :disabled="busy || !writable || !b.bot.credential.present"
              :data-testid="`ai-bot-switch-${b.ai_id}`"
              @update:model-value="(val: boolean) => onToggleEnable(b, val)"
            />
          </div>
        </div>

        <p class="st-note">{{ BOT_META[b.ai_id]?.desc }}</p>

        <!-- 提示横幅 -->
        <Banner v-if="botNotices[b.ai_id]" :kind="botNotices[b.ai_id]!.kind" class="mb-2 mt-2">
          {{ botNotices[b.ai_id]!.text }}
        </Banner>
        <Banner
          v-if="tokenErrors[b.ai_id]"
          kind="error"
          class="mb-2 mt-2"
          data-testid="ai-bot-token-error"
        >
          {{ tokenErrors[b.ai_id] }}
        </Banner>

        <div class="card-grid">
          <dl class="st-kv">
            <dt>凭据状态</dt>
            <dd :data-testid="`ai-bot-credential-status-${b.ai_id}`">
              <Tag :tone="b.bot.credential.present ? 'ok' : 'neutral'">
                {{ b.bot.credential.present ? '已保存' : '未配置' }}
              </Tag>
              <span v-if="b.bot.credential.source" class="src-text text-xs text-neutral-500 ml-1">
                （{{ b.bot.credential.source === 'imported' ? '旧配置导入' : '手动录入' }}）
              </span>
            </dd>

            <dt>Bot 用户名</dt>
            <dd class="st-mono text-sm" :data-testid="`ai-bot-username-${b.ai_id}`">
              {{ b.bot.username ? `@${b.bot.username.replace(/^@/, '')}` : '—' }}
            </dd>

            <dt>Bot ID</dt>
            <dd class="st-mono text-sm" :data-testid="`ai-bot-id-${b.ai_id}`">
              {{ b.bot.bot_id || '—' }}
            </dd>

            <dt v-if="b.poller.last_error_category">最近错误</dt>
            <dd v-if="b.poller.last_error_category" class="text-red-500 text-xs">
              {{ b.poller.last_error_category }}
            </dd>
          </dl>
        </div>

        <!-- Token 输入表单 -->
        <div class="token-form mt-3">
          <div class="st-fld">
            <label class="lbl" :for="`ai-bot-token-${b.ai_id}`">录入 Token</label>
            <div class="token-inputs flex gap-2">
              <input
                :id="`ai-bot-token-${b.ai_id}`"
                v-model="tokenInputs[b.ai_id]"
                type="password"
                autocomplete="new-password"
                placeholder="格式为 <数字id>:<密钥字符串>"
                class="st-select token-pw-input flex-1"
                :data-testid="`ai-bot-token-input-${b.ai_id}`"
                :disabled="busy || !writable"
                @keydown.enter.prevent="onSaveToken(b.ai_id)"
              />
              <Button
                variant="primary"
                size="sm"
                :data-testid="`save-ai-bot-token-btn-${b.ai_id}`"
                :disabled="busy || !writable || !tokenInputs[b.ai_id]?.trim()"
                @click="onSaveToken(b.ai_id)"
              >
                保存 Token
              </Button>
              <Button
                variant="default"
                size="sm"
                :data-testid="`import-legacy-ai-bot-token-btn-${b.ai_id}`"
                :disabled="busy || !writable"
                @click="onImportLegacyToken(b.ai_id)"
              >
                从旧版导入
              </Button>
              <Button
                v-if="b.bot.credential.present"
                variant="destructive"
                size="sm"
                :data-testid="`delete-ai-bot-token-btn-${b.ai_id}`"
                :disabled="busy || !writable"
                @click="deleteTargetBot = b"
              >
                删除 Token
              </Button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 启用切换步骤 Sheet -->
    <TelegramAiBotEnableSheet
      :open="Boolean(enableTargetBot)"
      :ai-title="
        enableTargetBot ? BOT_META[enableTargetBot.ai_id]?.name || enableTargetBot.ai_id : ''
      "
      :submitting="enableSubmitting"
      :error="enableError"
      @update:open="
        (val) => {
          if (!val) enableTargetBot = null
        }
      "
      @confirm="onConfirmEnable"
    />

    <!-- 删除 Token 确认 Sheet -->
    <Sheet
      :open="Boolean(deleteTargetBot)"
      title="删除 AI 机器人 Token"
      description="删除后将清除保存在 Keychain 中的此机器人 Token。未保存 Token 的机器人将无法启用长轮询。"
      @update:open="
        (val) => {
          if (!val) deleteTargetBot = null
        }
      "
    >
      <div class="p-2">
        <p class="text-sm text-neutral-600 mb-4">
          确定要删除
          <strong>{{ deleteTargetBot ? BOT_META[deleteTargetBot.ai_id]?.name : '' }}</strong>
          的 Token 吗？
        </p>
        <div class="flex justify-end gap-2">
          <Button variant="default" @click="deleteTargetBot = null">取消</Button>
          <Button
            variant="destructive"
            data-testid="confirm-delete-ai-bot-token-btn"
            @click="onConfirmDeleteToken"
          >
            确认删除
          </Button>
        </div>
      </div>
    </Sheet>
  </div>
</template>

<style scoped>
.ai-bots-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 24px;
}
.section-title-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.section-title-row h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
}
.bots-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ai-bot-card {
  padding: 16px;
  border-radius: var(--r-card, 8px);
  border: 1px solid var(--line);
  background: var(--bg-card, #fff);
}
.st-head {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}
.st-head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.st-grow {
  flex: 1;
}
.st-note {
  font-size: 12.5px;
  color: var(--mute);
  margin-bottom: 12px;
}
.st-kv {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
  gap: 6px 12px;
  font-size: 12.5px;
}
.st-kv dt {
  color: var(--mute);
}
.st-kv dd {
  margin: 0;
  color: var(--ink);
}
.st-fld {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.lbl {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink);
}
.token-pw-input {
  padding: 6px 10px;
  border-radius: var(--r-ctl, 6px);
  border: 1px solid var(--line);
  font: inherit;
  font-size: 12.5px;
}
</style>
