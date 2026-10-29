<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import StatusPill from '@/components/StatusPill.vue'
import Tag from '@/components/Tag.vue'
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
  /** 仓库线路色（CSS 颜色值），缺省用中性线路色。 */
  color?: string
  /** 这次运行用的运行命令名称（配置下有多条命令，要标明是哪一条）。 */
  commandName?: string
  /** 命令用的分支，如“main 分支”。 */
  branchText?: string
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
    <h2 class="sec-title">本次运行</h2>
    <div class="run-card-header">
      <div class="run-card-status">
        <StatusPill :state="mapStatusToPill(true, run.status)" />
        <span v-if="commandName" class="run-command" data-testid="run-command-name">{{
          commandName
        }}</span>
        <span v-if="branchText" class="run-branch" data-testid="run-command-branch">{{
          branchText
        }}</span>
        <span class="run-op-name">{{ operationLabel(run.operation) }}</span>
        <Tag v-if="run.origin?.kind === 'telegram'" data-testid="run-origin-telegram">
          由 Telegram 触发
        </Tag>
        <span class="run-time-meta num">
          {{ formatTime(run.started_at ?? run.created_at) }} 开始，用时 {{ elapsedText }}
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

    <StepList
      :steps="steps"
      :run-status="run.status"
      :targets="run.task_snapshot?.targets"
      :effects="run.effects"
      :summary="run.summary"
      :color="color"
      :now="now"
    />

    <div class="run-log">
      <LogPanel
        :lines="lines"
        :total-line-count="totalLineCount"
        :loading="loading"
        :warning="warning"
        :run-status="run.status"
      />
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
          :run-status="run?.status"
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
  margin-top: 24px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.sec-title {
  margin: 0 0 8px;
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--mute);
}
.run-log :deep(.log-panel) {
  border-left: 0;
}
.run-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.run-card-status {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}
.run-command {
  font-weight: 600;
  color: var(--ink);
  min-width: 0;
  overflow-wrap: anywhere;
}
.run-branch {
  font-family: var(--font-mono);
  font-size: var(--text-sub);
  color: var(--mute);
}
.run-op-name {
  font-weight: 600;
  font-size: var(--text-sub);
  color: var(--mute);
}
.run-time-meta {
  color: var(--mute);
  font-size: var(--text-sub);
  white-space: nowrap;
}
.num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.run-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.run-log {
  height: 220px;
  margin-top: 12px;
  overflow: hidden;
  border-radius: var(--r-group);
  border: 1px solid var(--line);
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
  margin-top: 14px;
}
.full-log-modal {
  height: 60vh;
  min-height: 300px;
  overflow: hidden;
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
}
</style>
