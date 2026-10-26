<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import StatusPill from '@/components/StatusPill.vue'
import TextField from '@/components/TextField.vue'
import Tag from '@/components/Tag.vue'
import type { PillState } from '@/components/pill'
import type { BinaryInfo, CodeServerSettings, ServiceView } from './api'
import { useServicesContext } from './useServices'

const props = defineProps<{
  service?: ServiceView
  binary?: BinaryInfo
  settings?: CodeServerSettings
  busy?: boolean
  writable?: boolean
}>()

const services = useServicesContext()

const cs = computed(() => props.service)
const bin = computed(() => props.binary)

// --- 状态与状态胶囊映射 ---
const pillState = computed<PillState>(() => {
  const s = cs.value?.state || 'stopped'
  switch (s) {
    case 'starting':
      return 'running'
    case 'running':
      return 'running'
    case 'stopping':
      return 'stopping'
    case 'external':
    case 'unhealthy':
      return 'verify'
    case 'failed':
      return 'failed'
    case 'stopped':
    default:
      return 'disabled'
  }
})

const pillLabel = computed<string>(() => {
  const s = cs.value?.state || 'stopped'
  switch (s) {
    case 'starting':
      return '启动中'
    case 'running':
      return '运行中'
    case 'stopping':
      return '停止中'
    case 'external':
      return '外部进程占用'
    case 'unhealthy':
      return '健康探测异常'
    case 'failed':
      return '服务异常'
    case 'stopped':
    default:
      return '已停止'
  }
})

const isExternal = computed(() => cs.value?.state === 'external')
const isRunning = computed(() => cs.value?.state === 'running' || cs.value?.state === 'unhealthy')
const isStarting = computed(
  () => services.codeServerStarting.value || cs.value?.state === 'starting',
)
const isStopping = computed(
  () => services.codeServerStopping.value || cs.value?.state === 'stopping',
)

// --- 错误信息 ---
const cardError = computed(() => {
  if (services.codeServerError.value) return services.codeServerError.value
  if (cs.value?.last_error === 'service_unsafe_config') {
    return 'code-server 配置为无认证且监听非回环地址，已拒绝启动；请在其 config.yaml 中启用密码认证'
  }
  if (cs.value?.last_error === 'service_binary_missing') {
    return '未找到服务二进制执行文件，请检查安装路径'
  }
  if (cs.value?.state === 'failed' && cs.value?.last_error) {
    return cs.value.last_error
  }
  return null
})

// --- 启停操作 ---
async function onStart() {
  await services.startCodeServer()
}

async function onStop() {
  await services.stopCodeServer()
}

// --- 日志查看 ---
const showLogs = ref(false)

async function onToggleLogs() {
  showLogs.value = !showLogs.value
  if (showLogs.value && !services.codeServerLogs.value) {
    await services.fetchCodeServerLogs()
  }
}

async function onRefreshLogs() {
  await services.fetchCodeServerLogs()
}

// --- URL 复制 ---
const urlCopied = ref(false)

async function onCopyUrl() {
  const url = cs.value?.url
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

// --- 设置项（超时时间 & 二进制路径确认） ---
const editTimeout = ref(String(props.settings?.start_timeout_s ?? 30))
const editBinaryPath = ref(props.binary?.path ?? '')
const settingsSubmitting = ref(false)
const settingsSuccess = ref<string | null>(null)

watch(
  () => props.settings?.start_timeout_s,
  (val) => {
    if (val !== undefined) editTimeout.value = String(val)
  },
)

watch(
  () => props.binary?.path,
  (val) => {
    if (val !== undefined && val !== null) editBinaryPath.value = val
  },
)

async function onSaveSettings() {
  settingsSubmitting.value = true
  settingsSuccess.value = null
  try {
    const timeout = parseInt(editTimeout.value, 10)
    const ok = await services.updateServicesSettings({
      code_server: {
        start_timeout_s: isNaN(timeout) || timeout <= 0 ? 30 : timeout,
      },
      binaries: {
        code_server: editBinaryPath.value.trim() || null,
      },
    })
    if (ok) {
      settingsSuccess.value = '设置已保存'
      setTimeout(() => {
        settingsSuccess.value = null
      }, 2000)
    }
  } finally {
    settingsSubmitting.value = false
  }
}
</script>

<template>
  <section class="st-section" aria-label="code-server" data-testid="code-server-card">
    <div class="st-head">
      <div class="title-row">
        <h2>code-server</h2>
        <StatusPill :state="pillState" :label="pillLabel" data-testid="code-server-status-pill" />
        <Tag v-if="bin?.version" data-testid="code-server-version-tag">
          {{ bin.version }}
        </Tag>
      </div>

      <div class="st-grow"></div>

      <!-- 控制按钮组：单个按钮状态机与 loading 态 -->
      <div class="control-actions">
        <template v-if="isExternal">
          <Button
            variant="default"
            disabled
            title="该端口已被非本应用启动的进程占用，应用不会停止它"
            data-testid="code-server-external-btn"
          >
            外部进程运行中
          </Button>
        </template>
        <template v-else-if="isRunning">
          <Button
            variant="default"
            data-testid="code-server-stop-btn"
            :disabled="isStopping || busy || !writable"
            @click="onStop"
          >
            {{ isStopping ? '停止中…' : '停止' }}
          </Button>
        </template>
        <template v-else>
          <Button
            variant="primary"
            data-testid="code-server-start-btn"
            :disabled="isStarting || busy || !writable"
            @click="onStart"
          >
            {{ isStarting ? '启动中…' : '启动' }}
          </Button>
        </template>
      </div>
    </div>

    <!-- 外部实例提示（不可停止） -->
    <Banner v-if="isExternal" kind="warn" class="mb-3" data-testid="code-server-external-banner">
      该端口已被非本应用启动的进程占用，应用不会停止它
    </Banner>

    <!-- 二进制缺失提示 -->
    <Banner
      v-if="bin && !bin.found"
      kind="warn"
      class="mb-3"
      data-testid="code-server-binary-missing-banner"
    >
      未找到服务二进制执行文件，请检查安装路径
    </Banner>

    <!-- 错误反馈 Banner（含 service_unsafe_config） -->
    <Banner v-if="cardError" kind="error" class="mb-3" data-testid="code-server-error-banner">
      {{ cardError }}
    </Banner>

    <!-- 访问信息展示（只展示后端给的字段） -->
    <div class="st-card">
      <div class="st-row">
        <div class="st-field">
          <span class="st-label">端口</span>
          <span class="st-val st-mono" data-testid="code-server-port">
            {{ cs?.port ? cs.port : '—' }}
          </span>
        </div>
        <div class="st-field grow">
          <span class="st-label">访问地址</span>
          <div class="url-display">
            <span v-if="cs?.url" class="st-val st-mono" data-testid="code-server-url">
              {{ cs.url }}
            </span>
            <span v-else class="st-val st-mute" data-testid="code-server-url-empty">
              未运行或尚未分配
            </span>
            <Button
              v-if="cs?.url"
              size="sm"
              data-testid="copy-code-server-url-btn"
              class="ml-2"
              @click="onCopyUrl"
            >
              {{ urlCopied ? '已复制' : '复制地址' }}
            </Button>
          </div>
        </div>
      </div>

      <div class="st-row border-top">
        <div class="st-field grow">
          <span class="st-label">执行程序路径</span>
          <span v-if="bin?.path" class="st-val st-mono path-text" data-testid="code-server-path">
            {{ bin.path }}
          </span>
          <span v-else class="st-val st-mute">未检测到</span>
          <Tag v-if="bin?.confirmed" class="ml-2" data-testid="code-server-confirmed-tag"
            >已确认</Tag
          >
        </div>
      </div>
    </div>

    <!-- 日志查看区 -->
    <div class="logs-section">
      <div class="logs-head">
        <Button size="sm" data-testid="code-server-toggle-logs-btn" @click="onToggleLogs">
          {{ showLogs ? '收起日志' : '查看日志' }}
        </Button>
        <Button
          v-if="showLogs"
          size="sm"
          class="ml-2"
          data-testid="code-server-refresh-logs-btn"
          :disabled="services.codeServerLogsLoading.value"
          @click="onRefreshLogs"
        >
          {{ services.codeServerLogsLoading.value ? '刷新中…' : '刷新日志' }}
        </Button>
      </div>

      <div v-if="showLogs" class="logs-container" data-testid="code-server-logs-container">
        <Banner v-if="services.codeServerLogsError.value" kind="error" class="mb-2">
          {{ services.codeServerLogsError.value }}
        </Banner>
        <pre
          v-if="services.codeServerLogs.value"
          class="st-mono log-box"
          data-testid="code-server-logs-pre"
          >{{ services.codeServerLogs.value }}</pre>
        <div v-else-if="services.codeServerLogsLoading.value" class="st-mute log-loading">
          正在读取日志…
        </div>
        <div v-else class="st-mute log-empty" data-testid="code-server-logs-empty">
          暂无日志输出
        </div>
      </div>
    </div>

    <!-- 高级配置折叠 / 展开 -->
    <details class="st-details" data-testid="code-server-settings-details">
      <summary class="st-summary">配置项（启动超时 & 二进制确认）</summary>
      <div class="st-settings-form">
        <div class="form-row">
          <label class="form-label" for="cs-timeout">启动超时（秒）</label>
          <TextField
            id="cs-timeout"
            v-model="editTimeout"
            label="启动超时（秒）"
            class="input-sm"
            data-testid="code-server-timeout-input"
            :disabled="settingsSubmitting || !writable || isRunning"
          />
        </div>

        <div class="form-row">
          <label class="form-label" for="cs-bin-path">指定 code-server 路径</label>
          <TextField
            id="cs-bin-path"
            v-model="editBinaryPath"
            label="指定 code-server 路径"
            placeholder="留空自动检测"
            class="input-lg"
            data-testid="code-server-bin-input"
            :disabled="settingsSubmitting || !writable || isRunning"
          />
        </div>

        <Banner v-if="services.settingsError.value" kind="error" class="mb-2">
          {{ services.settingsError.value }}
        </Banner>
        <Banner v-if="settingsSuccess" kind="info" class="mb-2">
          {{ settingsSuccess }}
        </Banner>

        <div class="form-actions">
          <Button
            size="sm"
            variant="default"
            data-testid="save-code-server-settings-btn"
            :disabled="settingsSubmitting || !writable || isRunning"
            @click="onSaveSettings"
          >
            {{ settingsSubmitting ? '保存中…' : '保存设置' }}
          </Button>
          <span v-if="isRunning" class="running-hint"> 服务运行中不可更改配置，请先停止服务 </span>
        </div>
      </div>
    </details>
  </section>
</template>

<style scoped>
.st-section {
  display: flex;
  flex-direction: column;
  background: var(--bg-window);
  border: 1px solid var(--line);
  border-radius: var(--radius-group);
  padding: 16px;
  margin-bottom: 16px;
}
.st-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
h2 {
  margin: 0;
  font-size: var(--text-section);
  font-weight: 600;
  color: var(--fg);
}
.st-grow {
  flex: 1;
}
.control-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mb-2 {
  margin-bottom: 8px;
}
.mb-3 {
  margin-bottom: 12px;
}
.ml-2 {
  margin-left: 8px;
}
.st-card {
  background: var(--bg-sub);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  padding: 12px 14px;
}
.st-row {
  display: flex;
  align-items: center;
  gap: 20px;
}
.border-top {
  border-top: 1px solid var(--line);
  margin-top: 10px;
  padding-top: 10px;
}
.st-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.st-field.grow {
  flex: 1;
  min-width: 0;
}
.st-label {
  font-size: var(--text-sub);
  color: var(--mute);
}
.st-val {
  font-size: var(--text-base);
  color: var(--fg);
}
.st-mute {
  color: var(--mute);
}
.url-display {
  display: flex;
  align-items: center;
}
.path-text {
  word-break: break-all;
}
.logs-section {
  margin-top: 12px;
}
.logs-head {
  display: flex;
  align-items: center;
}
.logs-container {
  margin-top: 8px;
}
.log-box {
  background: var(--bg-sub);
  color: var(--fg);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 11.5px;
  line-height: 1.45;
  margin: 0;
}
.log-loading,
.log-empty {
  padding: 12px;
  font-size: var(--text-sub);
}
.st-details {
  margin-top: 12px;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}
.st-summary {
  cursor: pointer;
  color: var(--mute);
  font-size: var(--text-sub);
  user-select: none;
}
.st-settings-form {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-label {
  font-size: var(--text-sub);
  color: var(--mute);
}
.input-sm {
  max-width: 120px;
}
.input-lg {
  max-width: 480px;
}
.form-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}
.running-hint {
  font-size: var(--text-sub);
  color: var(--mute);
}
</style>
