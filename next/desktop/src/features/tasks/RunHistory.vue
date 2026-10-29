<script setup lang="ts">
import StatusPill from '@/components/StatusPill.vue'
import MiniRoute from './MiniRoute.vue'
import {
  formatDateTime,
  formatDuration,
  mapStatusToPill,
  operationLabel,
  type RunResponse,
} from './api'
import { runDots } from './route'

const props = defineProps<{
  runs: RunResponse[]
  selectedRunId?: string | null
  /** 仓库线路色（CSS 颜色值）。 */
  color?: string
  /** 运行命令 id 到名称的对照，用来标明每条记录是哪条命令。 */
  commandNames?: Record<string, string>
  /** 运行命令 id 到所用分支的对照，如“main 分支”。 */
  commandBranches?: Record<string, string>
}>()

const emit = defineEmits<{
  select: [run: RunResponse]
}>()

/** 这条记录对应的命令名：优先用配置里的命令名，其次回退到运行快照里的说明或 TG 命令。 */
function commandText(r: RunResponse): string {
  const n = props.commandNames?.[r.task_id]
  if (n) return n
  const snap = r.task_snapshot
  return snap?.tg_desc || snap?.tg_command || ''
}

/** 触发来源：写成人话，不用中点拼接。 */
function triggerText(r: RunResponse): string {
  if (r.origin?.kind === 'telegram') return '由 Telegram 触发'
  const snap = r.task_snapshot
  if (snap?.tg_command) return `Telegram 命令 ${snap.tg_command}`
  return '桌面'
}
</script>

<template>
  <div class="run-history" aria-label="运行历史" :style="color ? { '--c': color } : undefined">
    <h2 class="history-title">运行记录</h2>
    <div v-if="runs.length === 0" class="history-empty">暂无历史运行记录</div>
    <!-- 行不折行；窗口太窄时只在这个容器里横向滚动 -->
    <div v-else class="table-wrap">
      <div class="history-table" role="list" data-testid="runs-history-table">
        <div
          v-for="r in runs"
          :key="r.run_id"
          class="history-row"
          role="listitem"
          :data-testid="`run-history-row-${r.run_id}`"
          :data-selected="r.run_id === selectedRunId ? 'true' : 'false'"
          :aria-current="r.run_id === selectedRunId ? 'true' : undefined"
          tabindex="0"
          @click="emit('select', r)"
          @keydown.enter="emit('select', r)"
        >
          <span class="cell-result"><StatusPill :state="mapStatusToPill(true, r.status)" /></span>
          <span class="cell-route">
            <MiniRoute :dots="runDots(r.steps, r.status)" />
            <span v-if="commandText(r)" class="cmd" data-testid="run-history-command">{{
              commandText(r)
            }}</span>
            <span
              v-if="commandBranches?.[r.task_id]"
              class="branch mono"
              data-testid="run-history-branch"
              >{{ commandBranches[r.task_id] }}</span
            >
            <span v-if="r.operation !== 'sync_build_release'" class="op">{{
              operationLabel(r.operation)
            }}</span>
            <span class="trigger">{{ triggerText(r) }}</span>
          </span>
          <span class="cell-start num">{{ formatDateTime(r.started_at ?? r.created_at) }}</span>
          <span class="cell-dur num">
            {{ formatDuration(r.started_at ?? r.created_at, r.finished_at) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.run-history {
  --c: var(--l-8);
  margin-top: 24px;
  min-width: 0;
}
.history-title {
  margin: 0 0 8px;
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--mute);
}
.history-empty {
  color: var(--mute);
  font-size: var(--text-sub);
  padding: 12px 0;
}
.table-wrap {
  overflow-x: auto;
}
.history-table {
  display: flex;
  flex-direction: column;
  min-width: 460px;
}
.history-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) 92px 52px;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-radius: var(--r-row);
  white-space: nowrap;
  cursor: pointer;
}
.history-row:hover {
  background: var(--hover);
}
.history-row[data-selected='true'] {
  background: var(--sel-blur);
}
.cell-result {
  display: inline-flex;
}
.cell-route {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  overflow: hidden;
}
.branch {
  flex: none;
  font-size: var(--text-sub);
  color: var(--mute);
}
.cmd {
  flex: none;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 600;
  color: var(--ink);
}
.op {
  flex: none;
  font-weight: 600;
  color: var(--ink);
}
.trigger {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--mute);
}
.num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--text-sub);
}
.cell-start {
  color: var(--mute);
}
.cell-dur {
  color: var(--mute);
  text-align: right;
}
</style>
