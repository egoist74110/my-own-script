<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import StatusPill from '@/components/StatusPill.vue'
import StepList from './StepList.vue'
import LogPanel from './LogPanel.vue'
import {
  formatDuration,
  formatRunReason,
  formatTime,
  mapStatusToPill,
  operationLabel,
  type RunResponse,
  type StepView,
} from './api'
import type { LogLine } from './useRunLogs'

const props = defineProps<{
  run: RunResponse | null
  steps: StepView[]
  lines: LogLine[]
  totalLineCount?: number
  loading?: boolean
  warning?: string | null
}>()

const emit = defineEmits<{
  cancel: [runId: string]
}>()

const showCancelConfirm = ref(false)
const fullLogOpen = ref(false)

const isStopping = computed(() => props.run?.status === 'cancelling')
const isUnknown = computed(() => props.run?.status === 'unknown')
const isActive = computed(
  () =>
    props.run?.status === 'queued' ||
    props.run?.status === 'running' ||
    props.run?.status === 'cancelling',
)

const now = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | null = null

watch(
  isActive,
  (active) => {
    if (active) {
      if (!ticker) {
        now.value = Date.now()
        ticker = setInterval(() => {
          now.value = Date.now()
        }, 500)
      }
    } else {
      if (ticker) {
        clearInterval(ticker)
        ticker = null
      }
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  if (ticker) {
    clearInterval(ticker)
    ticker = null
  }
})

const elapsedText = computed(() => {
  const start = props.run?.started_at ?? props.run?.created_at
  const finish = props.run?.finished_at
  return formatDuration(start, finish, now.value)
})

const isFailedOrUnknownOrCancelled = computed(
  () =>
    props.run?.status === 'failed' ||
    props.run?.status === 'unknown' ||
    props.run?.status === 'cancelled',
)

const runReasonText = computed(() => {
  if (!isFailedOrUnknownOrCancelled.value || !props.run) return ''
  const reasonText = formatRunReason(props.run.reason_code)
  const summary = props.run.summary?.trim() || ''
  if (reasonText && summary) {
    if (summary === reasonText) return summary
    return `${reasonText}：${summary}`
  }
  return reasonText || summary
})

function onCancelClick() {
  showCancelConfirm.value = true
}

function confirmCancel() {
  showCancelConfirm.value = false
  if (props.run?.run_id) {
    emit('cancel', props.run.run_id)
  }
}
</script>

<template>
  <div v-if="run" class="run-card" data-testid="run-card">
    <div class="run-card-header">
      <div class="run-card-status">
        <StatusPill :state="mapStatusToPill(true, run.status)" />
        <span class="run-op-name">{{ operationLabel(run.operation) }}</span>
        <span class="run-time-meta">
          {{ formatTime(run.started_at ?? run.created_at) }} 开始 · 已用
          {{ elapsedText }}
        </span>
      </div>
      <div class="run-card-actions">
        <Button variant="default" data-testid="toggle-full-log" @click="fullLogOpen = true">
          完整日志
        </Button>
        <Button
          v-if="isActive"
          variant="destructive"
          data-testid="cancel-run-btn"
          :disabled="isStopping"
          @click="onCancelClick"
        >
          {{ isStopping ? '停止中…' : '停止' }}
        </Button>
      </div>
    </div>

    <!-- 失败/核实/取消原因提示（纯文本，来源于服务的 reason_code 与 summary） -->
    <Banner
      v-if="runReasonText"
      :kind="run.status === 'failed' ? 'error' : 'warn'"
      class="run-reason-banner"
      data-testid="run-reason-banner"
    >
      {{ runReasonText }}
    </Banner>

    <div class="run-card-grid">
      <div class="grid-left">
        <StepList :steps="steps" />
      </div>
      <div class="grid-right">
        <LogPanel
          :lines="lines"
          :total-line-count="totalLineCount"
          :loading="loading"
          :warning="warning"
        />
      </div>
    </div>

    <!-- 停止确认 Sheet -->
    <Sheet
      v-model:open="showCancelConfirm"
      title="停止本次运行？"
      :description="
        isUnknown
          ? '远端部署可能仍在继续；停止不会回滚已部署内容。'
          : '将向正在执行的步骤发送取消请求。'
      "
    >
      <div class="cancel-desc">
        <p>确认要终止当前任务运行吗？正在进行中的远端构建或发布可能会保持当前状态。</p>
        <p v-if="isUnknown" class="warn-text">
          警告：当前运行结果需要核实，停止不会撤回或回滚已经推送或部署的改动。
        </p>
      </div>
      <template #actions>
        <Button variant="destructive" data-testid="confirm-cancel-btn" @click="confirmCancel">
          确认停止
        </Button>
        <Button @click="showCancelConfirm = false">取消</Button>
      </template>
    </Sheet>

    <!-- 完整日志弹窗 Sheet -->
    <Sheet v-model:open="fullLogOpen" title="完整运行日志">
      <div class="full-log-modal">
        <LogPanel
          :lines="lines"
          :total-line-count="totalLineCount"
          :loading="loading"
          :warning="warning"
        />
      </div>
      <template #actions>
        <Button @click="fullLogOpen = false">关闭</Button>
      </template>
    </Sheet>
  </div>
</template>

<style scoped>
.run-card {
  margin-top: 16px;
  border-radius: var(--r-group);
  border: 1px solid var(--line);
  overflow: hidden;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
}
.run-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  background: color-mix(in srgb, var(--ink) 2%, transparent);
  border-bottom: 1px solid var(--line);
}
.run-card-status {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.run-op-name {
  font-weight: 600;
  font-size: var(--text-body);
  color: var(--ink);
}
.run-time-meta {
  color: var(--mute);
  font-size: var(--text-sub);
}
.run-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.run-card-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 220px;
  max-height: 380px;
}
.grid-left {
  overflow: auto;
}
.grid-right {
  overflow: hidden;
}
.cancel-desc {
  font-size: var(--text-body);
  color: var(--ink);
}
.cancel-desc p {
  margin: 4px 0;
}
.warn-text {
  color: var(--bn-warn-fg);
  font-weight: 600;
}
.run-reason-banner {
  margin: 10px 14px 0 14px;
}
.full-log-modal {
  height: 60vh;
  min-height: 300px;
  overflow: hidden;
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
}
@media (max-width: 900px) {
  .run-card-grid {
    grid-template-columns: 1fr;
    max-height: none;
  }
}
</style>
