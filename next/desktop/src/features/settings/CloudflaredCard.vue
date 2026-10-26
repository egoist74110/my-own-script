<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import StatusPill from '@/components/StatusPill.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import type { PillState } from '@/components/pill'
import type { BinaryInfo, CloudflaredSettings, CloudflaredView } from './api'
import CloudflaredImportSheet from './CloudflaredImportSheet.vue'
import CloudflaredTunnelSheet from './CloudflaredTunnelSheet.vue'
import { useServicesContext } from './useServices'

const props = defineProps<{
  cloudflared?: CloudflaredView
  binary?: BinaryInfo
  settings?: CloudflaredSettings
  busy?: boolean
  writable?: boolean
}>()

const services = useServicesContext()

const cf = computed(() => props.cloudflared)
const bin = computed(() => props.binary)
const globalTunnel = computed(() => cf.value?.global)
const tunnels = computed(() => cf.value?.tunnels ?? [])

// --- 全局隧道状态映射 ---
const globalPillState = computed<PillState>(() => {
  const s = globalTunnel.value?.state || 'stopped'
  switch (s) {
    case 'starting':
      return 'running'
    case 'running':
      return 'running'
    case 'stopping':
      return 'stopping'
    case 'unhealthy':
      return 'verify'
    case 'failed':
      return 'failed'
    case 'stopped':
    default:
      return 'disabled'
  }
})

const globalPillLabel = computed<string>(() => {
  const s = globalTunnel.value?.state || 'stopped'
  switch (s) {
    case 'starting':
      return '启动中'
    case 'running':
      return '运行中'
    case 'stopping':
      return '停止中'
    case 'unhealthy':
      return '健康探测异常'
    case 'failed':
      return '异常失败'
    case 'stopped':
    default:
      return '已停止'
  }
})

const isGlobalRunning = computed(
  () => globalTunnel.value?.state === 'running' || globalTunnel.value?.state === 'unhealthy',
)
const isGlobalStarting = computed(
  () => services.globalTunnelStarting.value || globalTunnel.value?.state === 'starting',
)
const isGlobalStopping = computed(
  () => services.globalTunnelStopping.value || globalTunnel.value?.state === 'stopping',
)

// --- 全局隧道启停 ---
async function onStartGlobal() {
  await services.startGlobalTunnel()
}

async function onStopGlobal() {
  await services.stopGlobalTunnel()
}

// --- 域名复制 ---
const globalUrlCopied = ref(false)

async function onCopyGlobalUrl() {
  const url = globalTunnel.value?.url
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    globalUrlCopied.value = true
    setTimeout(() => {
      globalUrlCopied.value = false
    }, 2000)
  } catch {
    // 忽略剪贴板写入异常
  }
}

const copiedTunnelIds = ref<Record<string, boolean>>({})

async function onCopyTunnelUrl(id: string, url: string) {
  try {
    await navigator.clipboard.writeText(url)
    copiedTunnelIds.value = { ...copiedTunnelIds.value, [id]: true }
    setTimeout(() => {
      copiedTunnelIds.value = { ...copiedTunnelIds.value, [id]: false }
    }, 2000)
  } catch {
    // 忽略剪贴板写入异常
  }
}

// --- 协议切换 ---
const protocolOptions = [
  { value: 'http2', label: 'HTTP/2' },
  { value: 'quic', label: 'QUIC' },
]

const currentProtocol = computed(() => props.settings?.protocol ?? 'http2')

async function onProtocolChange(val: string) {
  if (val === 'http2' || val === 'quic') {
    await services.updateProtocol(val)
  }
}

// --- 自定义隧道 Sheet & 导入 Sheet ---
const tunnelSheetOpen = ref(false)
const importSheetOpen = ref(false)

function onOpenTunnelSheet() {
  tunnelSheetOpen.value = true
}

function onOpenImportSheet() {
  importSheetOpen.value = true
}

async function onDeleteTunnel(identifier: string) {
  await services.deleteCustomTunnel(identifier)
}

function getTunnelPillState(state?: string): PillState {
  switch (state) {
    case 'starting':
      return 'running'
    case 'running':
      return 'running'
    case 'stopping':
      return 'stopping'
    case 'failed':
      return 'failed'
    case 'stopped':
    default:
      return 'disabled'
  }
}

function getTunnelPillLabel(state?: string): string {
  switch (state) {
    case 'starting':
      return '启动中'
    case 'running':
      return '运行中'
    case 'stopping':
      return '停止中'
    case 'failed':
      return '失败'
    case 'stopped':
    default:
      return '已停止'
  }
}

// --- 高级设置项（max_tunnels & binaries.cloudflared） ---
const editMaxTunnels = ref(String(props.settings?.max_tunnels ?? 5))
const editBinaryPath = ref(props.binary?.path ?? '')
const settingsSubmitting = ref(false)
const settingsSuccess = ref<string | null>(null)

watch(
  () => props.settings?.max_tunnels,
  (val) => {
    if (val !== undefined) editMaxTunnels.value = String(val)
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
    const maxTunnels = parseInt(editMaxTunnels.value, 10)
    const ok = await services.updateServicesSettings({
      cloudflared: {
        max_tunnels: isNaN(maxTunnels) || maxTunnels <= 0 ? 5 : maxTunnels,
        protocol: currentProtocol.value,
      },
      binaries: {
        cloudflared: editBinaryPath.value.trim() || null,
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
  <section class="st-section" aria-label="cloudflared" data-testid="cloudflared-card">
    <div class="st-head">
      <div class="title-row">
        <h2>Cloudflare 隧道 (cloudflared)</h2>
        <StatusPill
          :state="globalPillState"
          :label="globalPillLabel"
          data-testid="global-tunnel-status-pill"
        />
        <Tag v-if="bin?.version" data-testid="cloudflared-version-tag">
          {{ bin.version }}
        </Tag>
      </div>

      <div class="st-grow"></div>

      <!-- 全局隧道启停按钮 -->
      <div class="control-actions">
        <template v-if="isGlobalRunning">
          <Button
            variant="default"
            data-testid="global-tunnel-stop-btn"
            :disabled="isGlobalStopping || busy || !writable"
            @click="onStopGlobal"
          >
            {{ isGlobalStopping ? '停止中…' : '停止全局隧道' }}
          </Button>
        </template>
        <template v-else>
          <Button
            variant="primary"
            data-testid="global-tunnel-start-btn"
            :disabled="isGlobalStarting || busy || !writable"
            @click="onStartGlobal"
          >
            {{ isGlobalStarting ? '启动中…' : '启动全局隧道' }}
          </Button>
        </template>
      </div>
    </div>

    <!-- 协议变更提示（不自动重启） -->
    <Banner
      v-if="services.protocolNotice.value"
      kind="warn"
      class="mb-3"
      data-testid="protocol-restart-banner"
    >
      {{ services.protocolNotice.value }}
    </Banner>

    <!-- 二进制缺失提示 -->
    <Banner
      v-if="bin && !bin.found"
      kind="warn"
      class="mb-3"
      data-testid="cloudflared-binary-missing-banner"
    >
      未找到服务二进制执行文件，请检查安装路径
    </Banner>

    <!-- 错误反馈 -->
    <Banner
      v-if="services.globalTunnelError.value"
      kind="error"
      class="mb-3"
      data-testid="global-tunnel-error-banner"
    >
      {{ services.globalTunnelError.value }}
    </Banner>
    <Banner
      v-if="services.protocolError.value"
      kind="error"
      class="mb-3"
      data-testid="protocol-error-banner"
    >
      {{ services.protocolError.value }}
    </Banner>

    <!-- 全局隧道信息卡片 -->
    <div class="st-card">
      <div class="card-subtitle">全局 Quick 隧道（固定指向 code-server 端口）</div>
      <div class="st-row">
        <div class="st-field grow">
          <span class="st-label">公网临时域名</span>
          <div class="url-display">
            <span v-if="globalTunnel?.url" class="st-val st-mono" data-testid="global-tunnel-url">
              {{ globalTunnel.url }}
            </span>
            <span v-else class="st-val st-mute" data-testid="global-tunnel-url-empty">
              未运行或正在生成域名
            </span>
            <Button
              v-if="globalTunnel?.url"
              size="sm"
              data-testid="copy-global-tunnel-url-btn"
              class="ml-2"
              @click="onCopyGlobalUrl"
            >
              {{ globalUrlCopied ? '已复制' : '复制域名' }}
            </Button>
          </div>
        </div>
      </div>

      <!-- 协议偏好设置 -->
      <div class="st-row border-top">
        <div class="st-field grow">
          <div class="protocol-row">
            <div>
              <span class="st-label">隧道传输协议</span>
              <div class="protocol-controls">
                <SegmentedControl
                  :model-value="currentProtocol"
                  :items="protocolOptions"
                  label="隧道协议"
                  class="protocol-seg"
                  data-testid="protocol-segmented-control"
                  :disabled="services.protocolUpdating.value || !writable"
                  @update:model-value="onProtocolChange"
                />
                <Button
                  size="sm"
                  data-testid="open-import-pref-btn"
                  :disabled="services.legacyImporting.value || !writable"
                  @click="onOpenImportSheet"
                >
                  从旧应用导入协议偏好
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 自定义隧道管理区 -->
    <div class="custom-tunnels-section">
      <div class="section-head">
        <div>
          <h3>自定义 Quick 隧道</h3>
          <span class="count-sub">
            （{{ tunnels.length }} / {{ settings?.max_tunnels ?? 5 }}）
          </span>
        </div>
        <Button
          size="sm"
          variant="default"
          data-testid="open-add-tunnel-sheet-btn"
          :disabled="tunnels.length >= (settings?.max_tunnels ?? 5) || !writable"
          @click="onOpenTunnelSheet"
        >
          添加自定义隧道
        </Button>
      </div>

      <Banner
        v-if="services.deleteTunnelError.value"
        kind="error"
        class="mb-2"
        data-testid="delete-tunnel-error-banner"
      >
        {{ services.deleteTunnelError.value }}
      </Banner>

      <!-- 隧道列表 -->
      <div v-if="tunnels.length > 0" class="tunnels-list" data-testid="custom-tunnels-list">
        <div
          v-for="(t, index) in tunnels"
          :key="t.id || t.target_url || index"
          class="tunnel-item"
          :data-testid="`custom-tunnel-item-${t.id}`"
        >
          <div class="tunnel-info">
            <div class="tunnel-line">
              <span class="target-badge">目标</span>
              <span class="st-mono tunnel-target" data-testid="tunnel-target-text">
                {{ t.target_url }}
              </span>
              <StatusPill
                :state="getTunnelPillState(t.state)"
                :label="getTunnelPillLabel(t.state)"
                data-testid="tunnel-status-pill"
              />
            </div>
            <div class="tunnel-line sub">
              <span class="domain-label">域名：</span>
              <span v-if="t.url" class="st-mono tunnel-url" data-testid="tunnel-domain-text">
                {{ t.url }}
              </span>
              <span v-else class="st-mute">正在分配域名…</span>
              <Button
                v-if="t.url"
                size="sm"
                class="copy-btn-sm"
                data-testid="copy-tunnel-domain-btn"
                @click="onCopyTunnelUrl(t.id || '', t.url)"
              >
                {{ t.id && copiedTunnelIds[t.id] ? '已复制' : '复制' }}
              </Button>
            </div>
          </div>

          <Button
            size="sm"
            variant="destructive"
            data-testid="close-tunnel-btn"
            :disabled="services.deletingTunnelId.value === t.id || !writable"
            @click="t.id && onDeleteTunnel(t.id)"
          >
            {{ services.deletingTunnelId.value === t.id ? '关闭中…' : '关闭' }}
          </Button>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else class="tunnels-empty" data-testid="custom-tunnels-empty">
        暂无自定义隧道，点击上方按钮可添加暴露回环端口的临时 Quick 隧道。
      </div>
    </div>

    <!-- 高级配置折叠 / 展开 -->
    <details class="st-details" data-testid="cloudflared-settings-details">
      <summary class="st-summary">配置项（最大隧道数 & 二进制路径确认）</summary>
      <div class="st-settings-form">
        <div class="form-row">
          <label class="form-label" for="cf-max-tunnels">最大允许自定义隧道数</label>
          <TextField
            id="cf-max-tunnels"
            v-model="editMaxTunnels"
            label="最大允许自定义隧道数"
            class="input-sm"
            data-testid="cf-max-tunnels-input"
            :disabled="settingsSubmitting || !writable || isGlobalRunning"
          />
        </div>

        <div class="form-row">
          <label class="form-label" for="cf-bin-path">指定 cloudflared 路径</label>
          <TextField
            id="cf-bin-path"
            v-model="editBinaryPath"
            label="指定 cloudflared 路径"
            placeholder="留空自动检测"
            class="input-lg"
            data-testid="cf-bin-input"
            :disabled="settingsSubmitting || !writable || isGlobalRunning"
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
            data-testid="save-cloudflared-settings-btn"
            :disabled="settingsSubmitting || !writable || isGlobalRunning"
            @click="onSaveSettings"
          >
            {{ settingsSubmitting ? '保存中…' : '保存设置' }}
          </Button>
          <span v-if="isGlobalRunning" class="running-hint">
            服务运行中不可更改配置，请先停止服务
          </span>
        </div>
      </div>
    </details>

    <!-- 添加自定义隧道 Sheet -->
    <CloudflaredTunnelSheet v-model:open="tunnelSheetOpen" />

    <!-- 导入协议偏好 Sheet -->
    <CloudflaredImportSheet v-model:open="importSheetOpen" />
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
.card-subtitle {
  font-size: var(--text-sub);
  color: var(--mute);
  margin-bottom: 8px;
  font-weight: 500;
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
.protocol-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.protocol-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}
.protocol-seg {
  max-width: 200px;
}
.custom-tunnels-section {
  margin-top: 16px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.section-head h3 {
  display: inline;
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--fg);
}
.count-sub {
  font-size: var(--text-sub);
  color: var(--mute);
}
.tunnels-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tunnel-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--bg-sub);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  gap: 12px;
}
.tunnel-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}
.tunnel-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tunnel-line.sub {
  font-size: var(--text-sub);
}
.target-badge {
  font-size: 11px;
  font-weight: 500;
  background: var(--bg-hover);
  padding: 1px 6px;
  border-radius: 4px;
  color: var(--mute);
}
.tunnel-target {
  font-weight: 600;
  color: var(--fg);
}
.domain-label {
  color: var(--mute);
}
.tunnel-url {
  color: var(--fg);
}
.copy-btn-sm {
  height: 20px;
  padding: 0 6px;
  font-size: 11px;
}
.tunnels-empty {
  padding: 16px;
  text-align: center;
  color: var(--mute);
  font-size: var(--text-sub);
  background: var(--bg-sub);
  border: 1px dashed var(--line);
  border-radius: var(--radius-sm);
}
.st-details {
  margin-top: 16px;
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
