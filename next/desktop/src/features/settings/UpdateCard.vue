<script setup lang="ts">
// S9-C：“关于与更新”卡
// 展示当前版本、更新状态、下载进度、更新说明（纯文本），提供检查/下载/取消/重启操作
import { computed, ref } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import StatusPill from '@/components/StatusPill.vue'
import type { PillState } from '@/components/pill'
import { updateErrorMessage, useUpdate, type UpdateSources } from './useUpdate'

const props = withDefaults(
  defineProps<{
    sources?: UpdateSources
    busy?: boolean
  }>(),
  {
    sources: undefined,
    busy: false,
  },
)

const update = useUpdate(props.sources)
const confirmRestart = ref(false)

const isCheckDisabled = computed(() => {
  const s = update.status.value.state
  return (
    s === 'disabled' ||
    s === 'checking' ||
    s === 'downloading' ||
    s === 'ready' ||
    update.loading.value
  )
})

const pillState = computed<PillState>(() => {
  switch (update.status.value.state) {
    case 'disabled':
      return 'disabled'
    case 'checking':
    case 'downloading':
      return 'running'
    case 'up_to_date':
    case 'ready':
      return 'success'
    case 'available':
      return 'verify'
    case 'error':
      return 'failed'
    case 'idle':
    default:
      return 'queued'
  }
})

const pillLabel = computed(() => {
  switch (update.status.value.state) {
    case 'disabled':
      return '已停用'
    case 'checking':
      return '检查中'
    case 'downloading':
      return '下载中'
    case 'up_to_date':
      return '已是最新'
    case 'available':
      return '发现新版本'
    case 'ready':
      return '待重启'
    case 'error':
      return '错误'
    case 'idle':
    default:
      return '就绪'
  }
})

const stateDisplayText = computed(() => {
  switch (update.status.value.state) {
    case 'disabled':
      return update.disabledReason.value || '已停用'
    case 'idle':
      return '空闲就绪'
    case 'checking':
      return '正在检查更新…'
    case 'up_to_date':
      return '当前已是最新版本'
    case 'available':
      return '发现新版本'
    case 'downloading':
      return '正在下载更新…'
    case 'ready':
      return '新版本已安装，待重启'
    case 'error':
      return '发生错误'
    default:
      return '未知状态'
  }
})

const errorMessage = computed(() => {
  if (update.error.value) return update.error.value
  if (update.status.value.error_code) {
    return updateErrorMessage(update.status.value.error_code)
  }
  return '更新操作失败'
})

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const u = units[Math.min(i, units.length - 1)]
  const v = (bytes / Math.pow(1024, Math.min(i, units.length - 1))).toFixed(1)
  return `${v.endsWith('.0') ? v.slice(0, -2) : v} ${u}`
}

const progressPercent = computed(() => {
  const p = update.status.value.progress
  if (!p || p.total === null || p.total <= 0) return 0
  return Math.min(100, Math.max(0, Math.round((p.downloaded / p.total) * 100)))
})

const progressText = computed(() => {
  const p = update.status.value.progress
  if (!p) return ''
  if (p.total === null) {
    return `已下载 ${formatBytes(p.downloaded)}`
  }
  return `已下载 ${formatBytes(p.downloaded)} / ${formatBytes(p.total)} (${progressPercent.value}%)`
})

const checkedAtText = computed(() => {
  const ts = update.status.value.checked_at
  if (ts === null || ts === undefined || isNaN(ts)) {
    return '上次检查：从未'
  }
  const date = new Date(ts * 1000)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  const ss = String(date.getSeconds()).padStart(2, '0')
  return `上次检查：${y}-${m}-${d} ${hh}:${mm}:${ss}`
})

async function onConfirmRestart() {
  confirmRestart.value = false
  await update.restartUpdate()
}
</script>

<template>
  <div class="st-section" data-testid="update-card">
    <!-- 头部：标题、状态胶囊、主动作 -->
    <div class="st-head">
      <div class="title-with-icon">
        <span class="card-icon" aria-hidden="true">🔄</span>
        <h2>关于与更新</h2>
      </div>
      <StatusPill :state="pillState" :label="pillLabel" data-testid="update-status-pill" />
      <div class="st-grow" />

      <!-- 操作按钮行 -->
      <div class="actions-row">
        <Button
          variant="primary"
          data-testid="update-check-btn"
          :disabled="props.busy || isCheckDisabled"
          @click="update.checkUpdate()"
        >
          {{ update.status.value.state === 'checking' ? '检查中…' : '检查更新' }}
        </Button>

        <Button
          v-if="update.status.value.state === 'available'"
          variant="primary"
          data-testid="update-install-btn"
          :disabled="props.busy || update.loading.value"
          @click="update.installUpdate()"
        >
          下载并安装
        </Button>

        <Button
          v-if="
            update.status.value.state === 'checking' || update.status.value.state === 'downloading'
          "
          variant="destructive"
          data-testid="update-cancel-btn"
          :disabled="props.busy"
          @click="update.cancelUpdate()"
        >
          取消
        </Button>

        <Button
          v-if="update.status.value.state === 'ready'"
          variant="primary"
          data-testid="update-restart-btn"
          :disabled="props.busy"
          @click="confirmRestart = true"
        >
          重启以完成更新
        </Button>
      </div>
    </div>

    <!-- 二次确认弹窗：重启需关闭后端并重启应用 -->
    <div
      v-if="confirmRestart"
      class="confirm-box"
      data-testid="update-restart-confirm-box"
      role="dialog"
      aria-modal="true"
      aria-label="重启确认"
    >
      <span class="confirm-tip">将关闭后端服务并重启应用以完成更新，是否继续？</span>
      <div class="confirm-actions">
        <Button
          variant="destructive"
          data-testid="update-restart-confirm-btn"
          @click="onConfirmRestart"
        >
          确认重启
        </Button>
        <Button
          variant="default"
          data-testid="update-restart-cancel-btn"
          @click="confirmRestart = false"
        >
          取消
        </Button>
      </div>
    </div>

    <!-- 错误横幅 -->
    <Banner
      v-if="update.status.value.state === 'error' || update.error.value"
      kind="error"
      data-testid="update-error-banner"
      class="banner-block"
    >
      <span data-testid="update-error-text">{{ errorMessage }}</span>
    </Banner>

    <!-- 状态行（可访问性：aria-live="polite"） -->
    <div class="status-row" aria-live="polite" data-testid="update-status">
      <div class="status-main">
        <span class="status-label">状态：</span>
        <span class="status-value" data-testid="update-state-text">{{ stateDisplayText }}</span>
        <span
          v-if="update.status.value.state === 'available' && update.status.value.available_version"
          class="available-version"
          data-testid="update-available-version"
        >
          v{{ update.status.value.available_version }}
        </span>
      </div>

      <div
        v-if="update.disabledReason.value"
        class="disabled-reason"
        data-testid="update-disabled-reason"
      >
        {{ update.disabledReason.value }}
      </div>

      <!-- 下载进度条与已下载/总量（仅 downloading） -->
      <div v-if="update.status.value.state === 'downloading'" class="progress-section">
        <div
          class="progress-track"
          role="progressbar"
          :aria-valuenow="progressPercent"
          aria-valuemin="0"
          aria-valuemax="100"
          data-testid="update-progress-bar"
        >
          <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <div class="progress-info">
          <span class="progress-text" data-testid="update-progress-text">{{ progressText }}</span>
        </div>
      </div>

      <!-- 更新说明：纯文本，保留换行，绝对不用 v-html -->
      <div
        v-if="update.status.value.state === 'available' && update.status.value.notes"
        class="notes-box"
      >
        <span class="notes-title">更新说明：</span>
        <div class="notes-content" data-testid="update-notes">{{ update.status.value.notes }}</div>
      </div>
    </div>

    <!-- 底部信息条：当前版本与上次检查时间 -->
    <div class="info-bar" data-testid="update-info-bar">
      <div class="info-item">
        <span class="info-label">当前版本：</span>
        <span class="st-mono info-value" data-testid="update-current-version">{{
          update.status.value.current_version
        }}</span>
      </div>
      <div class="info-item">
        <span class="info-value checked-at" data-testid="update-checked-at">{{
          checkedAtText
        }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.title-with-icon {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-icon {
  font-size: 16px;
  line-height: 1;
}
.actions-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.banner-block {
  margin-top: 4px;
}
.status-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--r-ctl);
  background: var(--bg-window);
  border: 1px solid var(--line);
  font-size: var(--text-body);
}
.status-main {
  display: flex;
  align-items: center;
  gap: 6px;
}
.status-label {
  color: var(--mute);
}
.status-value {
  font-weight: 600;
  color: var(--ink);
}
.available-version {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--ink);
}
.disabled-reason {
  font-size: var(--text-sub);
  color: var(--st-verify-fg);
}
.progress-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
}
.progress-track {
  width: 100%;
  height: 8px;
  border-radius: 4px;
  background: var(--ctl);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.2s ease-in-out;
}
.progress-info {
  display: flex;
  justify-content: flex-end;
}
.progress-text {
  font-size: var(--text-sub);
  font-family: var(--font-mono);
  color: var(--mute);
}
.notes-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
  padding: 8px 10px;
  border-radius: var(--r-ctl);
  background: var(--ctl);
}
.notes-title {
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--mute);
}
.notes-content {
  font-size: var(--text-body);
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--ink);
  max-height: 200px;
  overflow-y: auto;
}
.info-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 2px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.info-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.info-label {
  color: var(--mute);
}
.info-value {
  color: var(--ink);
}
.checked-at {
  font-size: var(--text-sub);
  color: var(--mute);
}
.confirm-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-radius: var(--r-ctl);
  background: var(--st-verify-bg);
  border: 1px solid var(--st-verify-dot);
}
.confirm-tip {
  font-size: var(--text-body);
  color: var(--st-verify-fg);
  font-weight: 600;
}
.confirm-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
