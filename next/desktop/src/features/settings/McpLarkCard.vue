<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import StatusPill from '@/components/StatusPill.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import type { PillState } from '@/components/pill'
import type { LarkMcpView, RuntimeView } from './api'
import McpLarkOwnershipSheet from './McpLarkOwnershipSheet.vue'
import { useMcpContext } from './useMcp'

const props = defineProps<{
  lark?: LarkMcpView
  runtime?: RuntimeView
  managedNodeVersion?: string
  nodeMinVersion?: string
  busy?: boolean
  writable?: boolean
}>()

const mcp = useMcpContext()

// --- 状态映射 ---
const lk = computed(() => props.lark)
const rt = computed(() => props.runtime)
const activeJob = computed(() => mcp.activeJob.value)

const pillState = computed<PillState>(() => {
  const s = lk.value?.state || 'stopped'
  switch (s) {
    case 'starting':
      return 'queued'
    case 'running':
      return 'running'
    case 'running_degraded':
      return 'verify'
    case 'unhealthy':
    case 'failed':
      return 'failed'
    case 'stopping':
      return 'stopping'
    case 'logging_in':
      return 'running'
    case 'stopped':
    default:
      return 'disabled'
  }
})

const pillLabel = computed<string>(() => {
  const s = lk.value?.state || 'stopped'
  switch (s) {
    case 'starting':
      return '启动中'
    case 'running':
      return '运行中'
    case 'running_degraded':
      return '降级运行'
    case 'unhealthy':
      return '健康探测异常'
    case 'failed':
      return '服务失败'
    case 'stopping':
      return '停止中'
    case 'logging_in':
      return '登录中'
    case 'stopped':
    default:
      return '已停止'
  }
})

// --- 操作反馈 ---
const cardError = computed(() => mcp.larkError.value || mcp.runtimeError.value)
const isStarting = computed(() => mcp.larkStarting.value)
const isStopping = computed(() => mcp.larkStopping.value)
const isLoggingIn = computed(() => mcp.larkLoggingIn.value)
const isCancellingLogin = computed(() => mcp.larkCancellingLogin.value)
const isLoggingOut = computed(() => mcp.larkLoggingOut.value)
const isInstallingRuntime = computed(() => mcp.runtimeInstalling.value)
const isCancellingJob = computed(() => mcp.runtimeCancelling.value)

// --- 所有权确认 Sheet ---
const ownershipSheetOpen = ref(false)

function onOpenOwnershipSheet() {
  ownershipSheetOpen.value = true
}

async function onConfirmOwnership() {
  const ok = await mcp.confirmLarkOwnership(true)
  if (ok) {
    ownershipSheetOpen.value = false
  }
}

async function onRevokeOwnership() {
  await mcp.revokeLarkOwnership()
}

// --- 启停与登录 ---
const isRunning = computed(
  () => lk.value?.state === 'running' || lk.value?.state === 'running_degraded',
)
const isLoggingInState = computed(() => lk.value?.state === 'logging_in')

async function onStart() {
  await mcp.startLark()
}

async function onStop() {
  await mcp.stopLark()
}

async function onLogin() {
  await mcp.loginLark()
}

async function onCancelLogin() {
  await mcp.cancelLarkLogin()
}

async function onLogout() {
  await mcp.logoutLark()
}

async function onRelogin() {
  // 一键重登：先登出再登录
  const ok = await mcp.logoutLark()
  if (ok) {
    await mcp.loginLark()
  }
}

// --- 凭据管理（只写不读回，提交后立即清空局部变量） ---
const inputSecret = ref('')
const secretSubmitting = ref(false)

async function onSaveSecret() {
  if (!lk.value?.app_id || !inputSecret.value) return
  secretSubmitting.value = true
  const secretVal = inputSecret.value
  try {
    await mcp.saveLarkSecret(lk.value.app_id, secretVal)
  } finally {
    // 立即清空，不留凭据
    inputSecret.value = ''
    secretSubmitting.value = false
  }
}

async function onDeleteSecret() {
  if (!lk.value?.app_id) return
  await mcp.deleteLarkSecret(lk.value.app_id)
}

async function onImportLegacySecret() {
  if (!lk.value?.app_id) return
  await mcp.importLegacyLarkSecret(lk.value.app_id)
}

// --- 运行组件安装 ---
async function onInstallRuntime() {
  await mcp.installRuntime(false)
}

async function onCancelJob() {
  if (!activeJob.value?.job_id) return
  await mcp.cancelRuntimeJob(activeJob.value.job_id)
}

// --- 设置项编辑 ---
const editAppId = ref(lk.value?.app_id ?? '')
const editDomain = ref(lk.value?.domain ?? 'https://open.larksuite.com')
const editPort = ref(String(lk.value?.port ?? 3000))
const editLanguage = ref<'zh' | 'en'>(lk.value?.language ?? 'zh')
const editTools = ref(lk.value?.tools ?? '')
const editAutostart = ref(lk.value?.autostart ?? false)
const settingsSubmitting = ref(false)
const settingsMessage = ref<string | null>(null)

// 当快照数据更新时同步设置项（如果未在编辑中）
watch(
  () => lk.value,
  (newVal) => {
    if (!newVal || settingsSubmitting.value) return
    editAppId.value = newVal.app_id
    editDomain.value = newVal.domain
    editPort.value = String(newVal.port)
    editLanguage.value = newVal.language
    editTools.value = newVal.tools
    editAutostart.value = newVal.autostart
  },
  { immediate: true },
)

async function onSaveSettings() {
  if (!lk.value) return
  settingsSubmitting.value = true
  settingsMessage.value = null
  try {
    const ok = await mcp.updateLarkSettings({
      app_id: editAppId.value.trim(),
      domain: editDomain.value.trim(),
      port: Number(editPort.value) || 3000,
      language: editLanguage.value,
      tools: editTools.value.trim(),
      autostart: editAutostart.value,
      scope_hint: lk.value.scope_hint,
      owner_confirmed_at: lk.value.owner_confirmed_at,
      login: lk.value.login,
    })
    if (ok) {
      settingsMessage.value = '已保存配置'
      setTimeout(() => {
        settingsMessage.value = null
      }, 2000)
    }
  } finally {
    settingsSubmitting.value = false
  }
}

// --- 端点 URL 复制 ---
const urlCopied = ref(false)

async function onCopyEndpoint() {
  const url = lk.value?.endpoint
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    urlCopied.value = true
    setTimeout(() => {
      urlCopied.value = false
    }, 2000)
  } catch {
    // 忽略剪贴板写入异常
  }
}
</script>

<template>
  <section class="st-section" aria-label="飞书 / Lark MCP" data-testid="mcp-lark-card">
    <div class="st-head">
      <h2>飞书 / Lark MCP</h2>
      <StatusPill :state="pillState" :label="pillLabel" data-testid="lark-status-pill" />
      <div class="st-grow"></div>

      <!-- 控制按钮组 -->
      <div class="control-actions">
        <template v-if="!isRunning && !isLoggingInState">
          <Button
            variant="primary"
            data-testid="lark-start-btn"
            :disabled="
              !lk?.owner_confirmed_at ||
              !lk?.secret_configured ||
              !rt?.ready ||
              isStarting ||
              busy ||
              !writable
            "
            @click="onStart"
          >
            {{ isStarting ? '启动中…' : '启动' }}
          </Button>
          <Button
            variant="default"
            data-testid="lark-login-btn"
            :disabled="!lk?.owner_confirmed_at || isLoggingIn || busy || !writable"
            @click="onLogin"
          >
            {{ isLoggingIn ? '拉起中…' : '登录授权' }}
          </Button>
        </template>

        <template v-else-if="isLoggingInState">
          <Button
            variant="destructive"
            data-testid="lark-cancel-login-btn"
            :disabled="isCancellingLogin || busy || !writable"
            @click="onCancelLogin"
          >
            {{ isCancellingLogin ? '取消中…' : '取消登录' }}
          </Button>
        </template>

        <template v-else>
          <Button
            variant="default"
            data-testid="lark-stop-btn"
            :disabled="isStopping || busy || !writable"
            @click="onStop"
          >
            {{ isStopping ? '停止中…' : '停止' }}
          </Button>
          <Button
            variant="default"
            data-testid="lark-logout-btn"
            :disabled="isLoggingOut || busy || !writable"
            @click="onLogout"
          >
            {{ isLoggingOut ? '登出中…' : '登出' }}
          </Button>
        </template>
      </div>
    </div>

    <p class="st-note">托管本地 lark-mcp 服务实例，提供飞书文档、多维表格与云盘工具。</p>

    <!-- 错误横幅展示 -->
    <Banner v-if="cardError" kind="error" data-testid="lark-error-banner">
      {{ cardError }}
    </Banner>

    <!-- 降级或健康警示 -->
    <Banner v-if="lk?.state === 'running_degraded'" kind="warn" data-testid="lark-degraded-banner">
      <div class="banner-col">
        <span v-if="!lk.patches?.all_applied">刷新补丁未生效：过期后可能需要重登</span>
        <span v-if="!lk.keytar_available">令牌存储不可用，重启后需重登</span>
      </div>
    </Banner>

    <Banner v-if="lk?.state === 'unhealthy'" kind="error" data-testid="lark-unhealthy-banner">
      健康探测异常：连续探测失败，请检查端口占用或服务进程。
    </Banner>

    <Banner
      v-if="lk?.token_status?.state === 'refresh_failing'"
      kind="error"
      data-testid="lark-refresh-failing-banner"
    >
      <div class="banner-row">
        <span>令牌刷新失败，请重新登录授权。</span>
        <Button variant="default" size="sm" data-testid="lark-relogin-btn" @click="onRelogin">
          一键重登
        </Button>
      </div>
    </Banner>

    <Banner v-if="isLoggingInState" kind="info" data-testid="lark-logging-in-banner">
      已拉起授权流程，请在 60 秒内完成浏览器授权。
    </Banner>

    <!-- 补丁与令牌状态展示 -->
    <div class="status-summary-box">
      <div class="summary-col">
        <span class="lbl">所有权状态：</span>
        <div class="summary-val" data-testid="lark-ownership-status">
          <template v-if="lk?.owner_confirmed_at">
            <Tag class="st-ok">已确认所有权</Tag>
            <Button
              variant="plain"
              size="sm"
              data-testid="lark-revoke-ownership-btn"
              :disabled="isRunning || isLoggingInState || busy || !writable"
              @click="onRevokeOwnership"
            >
              撤销所有权
            </Button>
          </template>
          <template v-else>
            <Tag class="st-warn">未确认所有权</Tag>
            <Button
              variant="plain"
              size="sm"
              data-testid="lark-open-ownership-btn"
              :disabled="busy || !writable"
              @click="onOpenOwnershipSheet"
            >
              所有权确认
            </Button>
          </template>
        </div>
      </div>

      <div class="summary-col">
        <span class="lbl">令牌状态：</span>
        <div class="summary-val" data-testid="lark-token-status">
          <Tag :class="lk?.token_status?.state === 'ok' ? 'st-ok' : 'st-warn'">
            {{
              lk?.token_status?.state === 'ok'
                ? '有效'
                : lk?.token_status?.state === 'refresh_failing'
                  ? '刷新失败'
                  : '未登录 / 未知'
            }}
          </Tag>
          <span v-if="lk?.login?.logged_in_at" class="st-mono mute">
            (登录于 {{ lk.login.logged_in_at.slice(0, 16).replace('T', ' ') }})
          </span>
        </div>
      </div>

      <div class="summary-col">
        <span class="lbl">补丁状态：</span>
        <div class="summary-val st-tags" data-testid="lark-patches-status">
          <Tag :class="lk?.patches?.mcp_tool === 'applied' ? 'st-ok' : 'st-warn'">
            mcp-tool: {{ lk?.patches?.mcp_tool || 'unknown' }}
          </Tag>
          <Tag :class="lk?.patches?.auth_store === 'applied' ? 'st-ok' : 'st-warn'">
            auth-store: {{ lk?.patches?.auth_store || 'unknown' }}
          </Tag>
          <Tag :class="lk?.patches?.oidc === 'applied' ? 'st-ok' : 'st-warn'">
            oidc: {{ lk?.patches?.oidc || 'unknown' }}
          </Tag>
        </div>
      </div>

      <div v-if="lk?.endpoint" class="summary-col">
        <span class="lbl">端点 URL：</span>
        <div class="summary-val">
          <span class="st-mono" data-testid="lark-endpoint-url">{{ lk.endpoint }}</span>
          <Button
            variant="plain"
            size="sm"
            data-testid="copy-lark-endpoint-btn"
            @click="onCopyEndpoint"
          >
            {{ urlCopied ? '已复制！' : '复制' }}
          </Button>
        </div>
      </div>
    </div>

    <hr class="st-sep" />

    <!-- 运行组件状态与安装 -->
    <div class="runtime-section">
      <div class="st-head">
        <strong class="setting-title">运行组件 (Node.js & npm 包)</strong>
        <Tag :class="rt?.ready ? 'st-ok' : 'st-warn'" data-testid="runtime-ready-tag">
          {{ rt?.ready ? '组件就绪' : '组件未就绪' }}
        </Tag>
        <div class="st-grow"></div>
        <Button
          variant="default"
          data-testid="install-runtime-btn"
          :disabled="isInstallingRuntime || busy || !writable"
          @click="onInstallRuntime"
        >
          {{ isInstallingRuntime ? '发起中…' : '安装运行组件' }}
        </Button>
      </div>

      <dl class="st-kv runtime-kv">
        <dt class="lbl">Node 来源</dt>
        <dd data-testid="runtime-node-source">
          {{
            rt?.node?.source === 'detected'
              ? '系统检测'
              : rt?.node?.source === 'managed'
                ? '托管下载'
                : '未找到 (下限 >= ' + (nodeMinVersion || '20.20.0') + ')'
          }}
          <span v-if="rt?.node?.version" class="st-mono mute"> ({{ rt.node.version }})</span>
        </dd>
        <dt class="lbl">Node 路径</dt>
        <dd class="st-mono" data-testid="runtime-node-path">{{ rt?.node?.path || '—' }}</dd>
        <dt class="lbl">Lark MCP 包</dt>
        <dd data-testid="runtime-lark-pkg">
          {{ rt?.packages?.['@larksuiteoapi/lark-mcp'] || '0.5.1' }}
          ·
          <span :class="rt?.lark_package_ready ? 'st-ok' : 'st-warn'">
            {{ rt?.lark_package_ready ? '已安装' : '未安装' }}
          </span>
        </dd>
        <dt class="lbl">Keytar 原生模块</dt>
        <dd data-testid="runtime-keytar-status">
          <span :class="rt?.keytar_ready ? 'st-ok' : 'st-warn'">
            {{ rt?.keytar_ready ? '已就绪' : '未就绪 (将退回内存存储)' }}
          </span>
        </dd>
      </dl>

      <!-- 安装 Job 状态与输出 -->
      <div v-if="activeJob" class="job-box" data-testid="runtime-job-box">
        <div class="job-header">
          <span class="lbl">安装任务：</span>
          <Tag
            :class="
              activeJob.state === 'completed'
                ? 'st-ok'
                : activeJob.state === 'running'
                  ? 'st-running'
                  : 'st-warn'
            "
            data-testid="runtime-job-state"
          >
            {{
              activeJob.state === 'running'
                ? '正在安装…'
                : activeJob.state === 'completed'
                  ? '安装完成'
                  : activeJob.state === 'cancelled'
                    ? '已取消'
                    : '安装失败'
            }}
          </Tag>
          <div class="st-grow"></div>
          <Button
            v-if="activeJob.state === 'running'"
            variant="destructive"
            size="sm"
            data-testid="cancel-job-btn"
            :disabled="isCancellingJob"
            @click="onCancelJob"
          >
            {{ isCancellingJob ? '取消中…' : '取消安装' }}
          </Button>
        </div>
        <pre v-if="activeJob.output" class="st-mono job-output" data-testid="runtime-job-output">{{
          activeJob.output
        }}</pre>
        <div v-if="activeJob.error" class="st-warn" data-testid="runtime-job-error">
          {{ activeJob.error }}
        </div>
      </div>
    </div>

    <hr class="st-sep" />

    <!-- 凭据管理（只写不读回） -->
    <div class="cred-section">
      <strong class="setting-title">凭据管理 (App Secret)</strong>
      <p class="st-note">
        钥匙串中凭据只写不读回。当前状态：
        <strong data-testid="lark-secret-configured-status">
          {{ lk?.secret_configured ? '已配置' : '未配置' }}
        </strong>
      </p>

      <div class="cred-input-row">
        <TextField
          v-model="inputSecret"
          type="password"
          autocomplete="off"
          label="App Secret"
          placeholder="粘贴新的 App Secret；提交后立即清空"
          data-testid="lark-secret-input"
          class="cred-input"
          :disabled="busy || !writable || secretSubmitting"
        />
        <Button
          variant="primary"
          data-testid="save-lark-secret-btn"
          :disabled="!inputSecret || !lk?.app_id || busy || !writable || secretSubmitting"
          @click="onSaveSecret"
        >
          {{ secretSubmitting ? '保存中…' : '保存 Secret' }}
        </Button>
        <Button
          v-if="lk?.secret_configured"
          variant="destructive"
          data-testid="delete-lark-secret-btn"
          :disabled="busy || !writable"
          @click="onDeleteSecret"
        >
          删除 Secret
        </Button>
        <Button
          variant="default"
          data-testid="import-lark-secret-btn"
          :disabled="!lk?.app_id || busy || !writable"
          @click="onImportLegacySecret"
        >
          从旧应用导入
        </Button>
      </div>
    </div>

    <hr class="st-sep" />

    <!-- 服务配置项 -->
    <div class="config-section">
      <strong class="setting-title">服务参数设置</strong>
      <div class="config-grid">
        <div class="st-fld">
          <span class="lbl">App ID</span>
          <TextField
            v-model="editAppId"
            label="App ID"
            placeholder="cli_..."
            data-testid="lark-app-id-input"
            :disabled="busy || !writable"
          />
        </div>

        <div class="st-fld">
          <span class="lbl">域名 (Domain)</span>
          <select
            v-model="editDomain"
            class="st-select"
            data-testid="lark-domain-select"
            :disabled="busy || !writable"
          >
            <option value="https://open.larksuite.com">
              https://open.larksuite.com (Lark 海外)
            </option>
            <option value="https://open.feishu.cn">https://open.feishu.cn (飞书 国内)</option>
          </select>
        </div>

        <div class="st-fld">
          <span class="lbl">端口 (Port)</span>
          <TextField
            v-model="editPort"
            label="端口"
            placeholder="3000"
            data-testid="lark-port-input"
            :disabled="busy || !writable"
          />
        </div>

        <div class="st-fld">
          <span class="lbl">语言 (Language)</span>
          <select
            v-model="editLanguage"
            class="st-select"
            data-testid="lark-lang-select"
            :disabled="busy || !writable"
          >
            <option value="zh">中文 (zh)</option>
            <option value="en">English (en)</option>
          </select>
        </div>

        <div class="st-fld span-2">
          <span class="lbl">工具列表 (Tools)</span>
          <TextField
            v-model="editTools"
            label="工具列表"
            placeholder="preset.doc.default,docx.v1..."
            data-testid="lark-tools-input"
            :disabled="busy || !writable"
          />
        </div>

        <div class="st-fld span-2 row-center">
          <span class="lbl">应用启动时自动启动</span>
          <Switch
            :model-value="editAutostart"
            data-testid="lark-autostart-switch"
            :disabled="busy || !writable"
            @update:model-value="(val: boolean) => (editAutostart = val)"
          />
        </div>
      </div>

      <div class="config-actions">
        <Button
          variant="primary"
          data-testid="save-lark-settings-btn"
          :disabled="busy || !writable || settingsSubmitting"
          @click="onSaveSettings"
        >
          {{ settingsSubmitting ? '保存中…' : '保存服务设置' }}
        </Button>
        <span v-if="settingsMessage" class="st-ok" data-testid="lark-settings-msg">
          {{ settingsMessage }}
        </span>
      </div>
    </div>

    <!-- 所有权确认 Sheet -->
    <McpLarkOwnershipSheet
      :open="ownershipSheetOpen"
      :submitting="mcp.larkConfirmingOwner.value"
      :error="mcp.larkError.value"
      @confirm="onConfirmOwnership"
      @update:open="ownershipSheetOpen = $event"
    />
  </section>
</template>

<style scoped>
.control-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.banner-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.banner-col {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.status-summary-box {
  background: var(--bg-settings);
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.summary-col {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-body);
}
.summary-val {
  display: flex;
  align-items: center;
  gap: 8px;
}
.lbl {
  color: var(--mute);
  font-size: var(--text-sub);
  min-width: 80px;
}
.mute {
  color: var(--mute);
}
.runtime-section,
.cred-section,
.config-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.setting-title {
  font-size: var(--text-body);
}
.runtime-kv {
  margin: 0;
}
.job-box {
  background: var(--bg-window);
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.job-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.job-output {
  margin: 0;
  padding: 8px;
  background: var(--bg-settings);
  border-radius: var(--r-ctl);
  max-height: 140px;
  overflow: auto;
  font-size: 11.5px;
  white-space: pre-wrap;
}
.cred-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cred-input {
  flex: 1;
  min-width: 240px;
}
.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.span-2 {
  grid-column: span 2;
}
.row-center {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.st-select {
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-ctl);
  color: var(--text);
  padding: 0 8px;
  font-size: var(--text-body);
}
.config-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}
</style>
