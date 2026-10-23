<script setup lang="ts">
import StatusPill from '@/components/StatusPill.vue'
import {
  formatDateTime,
  formatDuration,
  mapStatusToPill,
  operationLabel,
  type RunResponse,
} from './api'

defineProps<{
  runs: RunResponse[]
  selectedRunId?: string | null
}>()

const emit = defineEmits<{
  select: [run: RunResponse]
}>()

function triggerText(r: RunResponse): string {
  if (r.origin?.kind === 'telegram') return '由 Telegram 触发'
  const snap = r.task_snapshot
  if (snap?.tg_command) return `TG · ${snap.tg_command}`
  return '本机'
}
</script>

<template>
  <div class="run-history" aria-label="运行历史">
    <h3 class="history-title">运行历史</h3>
    <div v-if="runs.length === 0" class="history-empty">暂无历史运行记录</div>
    <div v-else class="table-wrap">
      <table class="history-table" data-testid="runs-history-table">
        <thead>
          <tr>
            <th class="th-result">结果</th>
            <th class="th-op">操作</th>
            <th class="th-trigger">触发</th>
            <th class="th-start">开始</th>
            <th class="th-dur">耗时</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in runs"
            :key="r.run_id"
            class="history-row"
            :data-testid="`run-history-row-${r.run_id}`"
            :data-selected="r.run_id === selectedRunId ? 'true' : 'false'"
            :aria-current="r.run_id === selectedRunId ? 'true' : undefined"
            tabindex="0"
            @click="emit('select', r)"
            @keydown.enter="emit('select', r)"
          >
            <td class="td-result">
              <StatusPill :state="mapStatusToPill(true, r.status)" />
            </td>
            <td class="td-op">{{ operationLabel(r.operation) }}</td>
            <td class="td-trigger muted">{{ triggerText(r) }}</td>
            <td class="td-start muted">{{ formatDateTime(r.started_at ?? r.created_at) }}</td>
            <td class="td-dur mono muted">
              {{ formatDuration(r.started_at ?? r.created_at, r.finished_at) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.run-history {
  margin-top: 24px;
}
.history-title {
  margin: 0 0 10px;
  font-size: var(--text-body);
  font-weight: 700;
  color: var(--ink);
}
.history-empty {
  color: var(--mute);
  font-size: var(--text-sub);
  padding: 12px 0;
}
.table-wrap {
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  overflow: hidden;
}
.history-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: var(--text-sub);
}
th {
  padding: 7px 10px;
  background: color-mix(in srgb, var(--ink) 2%, transparent);
  border-bottom: 1px solid var(--line);
  font-weight: 600;
  color: var(--mute);
}
.th-dur {
  text-align: right;
}
.history-row {
  cursor: pointer;
  transition: background 0.12s;
}
.history-row:hover {
  background: color-mix(in srgb, var(--ink) 4%, transparent);
}
.history-row[data-selected='true'] {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  color: var(--ink);
  white-space: nowrap;
}
.history-row:last-child td {
  border-bottom: none;
}
.td-dur {
  text-align: right;
}
.muted {
  color: var(--mute);
}
.mono {
  font-family: var(--font-mono);
}
</style>
