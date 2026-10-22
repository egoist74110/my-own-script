<script setup lang="ts">
import { computed, ref } from 'vue'
import { MoreHorizontal, Play, Upload, X } from 'lucide-vue-next'
import { useBackendStore } from '@/stores/backend'
import { useUiStore } from '@/stores/ui'
import AppButton from '@/components/AppButton.vue'
import AppTabs from '@/components/AppTabs.vue'
import BlockTag from '@/components/BlockTag.vue'
import EnergyBar from '@/components/EnergyBar.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import IconButton from '@/components/IconButton.vue'
import InspectorPanel from '@/components/InspectorPanel.vue'
import SearchBox from '@/components/SearchBox.vue'
import StageBar from '@/components/StageBar.vue'
import StampBadge from '@/components/StampBadge.vue'
import StatusDot from '@/components/StatusDot.vue'
import { useTasks, type Task } from './mock/tasks'

const store = useBackendStore()
const ui = useUiStore()
const { tasks, addTask, runs, kpis, bars } = useTasks()

const view = ref('all')
const query = ref('')
const selectedId = ref('t1')
const alert = computed(() => store.alert.active)

const tabs = computed(() => [
  { value: 'all', label: '全部' },
  { value: 'run', label: '运行中' },
  { value: 'fav', label: '收藏' },
])

const rows = computed(() =>
  tasks.value.filter((t) => {
    if (view.value === 'run' && t.status !== 'run') return false
    if (view.value === 'fav' && !t.favorite) return false
    const q = query.value.trim().toLowerCase()
    return !q || `${t.name} ${t.target} ${t.branch}`.toLowerCase().includes(q)
  }),
)
const selected = computed<Task | undefined>(() =>
  tasks.value.find((t) => t.id === selectedId.value),
)
const summary = computed(() => {
  const all = tasks.value
  return `${all.length} 个任务 · ${all.filter((t) => t.status === 'run').length} 运行 · ${all.filter((t) => t.status === 'queued').length} 排队`
})

/** 告警态：标记为 errorOnAlert 的行以失败状态显示。 */
const isError = (t: Task) => alert.value && !!t.errorOnAlert
const stagesOf = (t: Task) => (isError(t) && t.alertStages ? t.alertStages : t.stages)
const STATUS_TEXT = { run: '运行中', queued: '排队', done: '完成', failed: '失败' } as const
const statusText = (t: Task) => (isError(t) ? '失败' : STATUS_TEXT[t.status])
const dotState = (t: Task) =>
  isError(t) || t.status === 'failed'
    ? 'warn'
    : t.status === 'run'
      ? 'run'
      : t.status === 'queued'
        ? 'idle'
        : 'ok'
const stamp = (t: Task) => (isError(t) ? 'failed' : t.result)
const logsOf = (t: Task) => (isError(t) && t.alertLogs ? t.alertLogs : t.logs)
const pct = (t: Task) => (isError(t) ? 'HALT' : `${Math.round((t.progress / 20) * 100)}%`)
const progress = (t: Task) => (isError(t) ? 15 : t.progress)
</script>

<template>
  <GlassPanel class="toolbar">
    <div class="title">
      <BlockTag>02</BlockTag>
      <h1>任务</h1>
      <span class="lbl" data-testid="task-summary">{{ summary }}</span>
    </div>
    <AppTabs v-model="view" :items="tabs" label="视图" />
    <span class="grow"></span>
    <SearchBox v-model="query" label="搜索任务" placeholder="搜索任务、目标、分支" />
    <AppButton data-testid="add-task" @click="addTask">＋ 新建任务</AppButton>
  </GlassPanel>

  <GlassPanel as="section" aria-label="任务列表" class="table-wrap">
    <table class="tasks">
      <thead class="lbl">
        <tr>
          <th scope="col">任务</th>
          <th scope="col">目标</th>
          <th scope="col">阶段</th>
          <th scope="col">状态</th>
          <th scope="col">耗时</th>
          <th scope="col">结果</th>
          <th scope="col"><span class="sr-only">操作</span></th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="t in rows"
          :key="t.id"
          tabindex="0"
          :aria-selected="t.id === selectedId"
          :data-selected="t.id === selectedId"
          :data-alert="isError(t) ? 'true' : undefined"
          :data-testid="`task-row-${t.id}`"
          @click="selectedId = t.id"
          @keydown.enter.self="selectedId = t.id"
        >
          <td>
            <span class="name">{{ t.name }}</span>
            <span class="branch mono">{{ t.branch }}</span>
          </td>
          <td class="target">{{ t.target }}</td>
          <td class="stagecell"><StageBar :stages="stagesOf(t)" /></td>
          <td>
            <span class="state"><StatusDot :state="dotState(t)" />{{ statusText(t) }}</span>
          </td>
          <td class="mono">{{ t.dur }}</td>
          <td><StampBadge v-if="stamp(t)" :result="stamp(t)!" /></td>
          <td class="ops">
            <IconButton label="运行" @click.stop><Play :size="13" aria-hidden="true" /></IconButton>
            <IconButton label="仅发布" @click.stop
              ><Upload :size="14" aria-hidden="true"
            /></IconButton>
            <IconButton label="更多" @click.stop
              ><MoreHorizontal :size="14" aria-hidden="true"
            /></IconButton>
          </td>
        </tr>
      </tbody>
    </table>
  </GlassPanel>

  <div class="bottom">
    <GlassPanel as="section" aria-label="最近运行" class="runs">
      <div class="panel-head">
        <span><BlockTag>LOG</BlockTag> 最近运行</span>
      </div>
      <div v-for="r in runs" :key="r.name" class="run">
        <StampBadge :result="r.result" />
        <span class="run-name">{{ r.name }}</span>
        <span class="mono meta">{{ r.meta }}</span>
      </div>
    </GlassPanel>
    <GlassPanel as="section" aria-label="本周" class="kpis">
      <div v-for="k in kpis" :key="k.label" class="kpi">
        <span class="lbl">{{ k.label }}</span>
        <span class="ox kv">{{ k.value }}</span>
        <span class="kd">{{ k.delta }}</span>
      </div>
      <div class="bars" aria-hidden="true">
        <span
          v-for="(h, i) in bars"
          :key="i"
          class="skew"
          :class="{ last: i === bars.length - 1 }"
          :style="{ height: h + '%' }"
        ></span>
      </div>
    </GlassPanel>
  </div>

  <InspectorPanel v-if="selected" label="任务详情" :alert="isError(selected)">
    <div
      class="insp"
      :data-alert="isError(selected) ? 'true' : undefined"
      data-testid="task-inspector"
    >
      <header class="insp-head">
        <div class="insp-line">
          <BlockTag
            :tone="isError(selected) ? 'warn' : selected.status === 'run' ? 'acc' : 'ink'"
            >{{ statusText(selected) }}</BlockTag
          >
          <span class="mono muted">{{ selected.build.split(' ')[0] }} · {{ selected.dur }}</span>
          <span class="grow"></span>
          <IconButton label="关闭详情" @click="ui.toggleInspector()"
            ><X :size="14" aria-hidden="true"
          /></IconButton>
        </div>
        <h2>{{ selected.name }} → {{ selected.target.split(' ')[0] }}</h2>
        <div class="insp-line">
          <EnergyBar :value="progress(selected)" :segments="20" label="任务进度" />
          <span class="ox pct">{{ pct(selected) }}</span>
        </div>
      </header>
      <dl class="detail">
        <dt class="lbl">Branch</dt>
        <dd class="mono">{{ selected.branch }}</dd>
        <dt class="lbl">Build</dt>
        <dd class="mono">{{ selected.build }}</dd>
        <dt class="lbl">Agent</dt>
        <dd class="mono">{{ selected.agent }}</dd>
        <dt class="lbl">Targets</dt>
        <dd class="mono">{{ selected.target }}</dd>
        <dt class="lbl">Policy</dt>
        <dd class="mono">{{ selected.policy }}</dd>
      </dl>
      <div class="insp-actions">
        <AppButton variant="ghost">完整日志</AppButton>
        <AppButton variant="ghost" class="stop">停止</AppButton>
      </div>
      <div class="loghead"><span class="lbl">Live log</span></div>
      <div class="log mono" role="log" aria-label="实时日志">
        <div v-for="(l, i) in logsOf(selected)" :key="i">
          <span class="lt">{{ l.t }}</span>
          <span :class="l.tone">{{ l.msg }}</span>
        </div>
      </div>
    </div>
  </InspectorPanel>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 14px;
}
.title {
  display: flex;
  align-items: center;
  gap: 8px;
}
h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}
.grow {
  flex: 1;
}
.table-wrap {
  padding: 4px 0 6px;
  overflow-x: auto;
}
.tasks {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
}
.tasks th {
  text-align: left;
  font-weight: 400;
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--line);
}
.tasks td {
  height: var(--row-h);
  padding: 0 12px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
.tasks tbody tr {
  cursor: pointer;
}
.tasks tbody tr:hover {
  background: rgba(255, 255, 255, 0.7);
}
.tasks tbody tr[data-selected='true'] {
  background: rgba(255, 255, 255, 0.8);
  box-shadow: inset 3px 0 0 var(--acc);
}
.tasks tbody tr[data-alert='true'] {
  background: rgba(255, 106, 0, 0.1);
  box-shadow: inset 3px 0 0 var(--warn);
}
.name {
  display: block;
  font-weight: 600;
}
.branch {
  display: block;
  font-size: 10.5px;
  color: var(--mute);
}
.target {
  color: #2a2e36;
}
.stagecell {
  min-width: 200px;
}
.state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.ops {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  height: var(--row-h);
}
.bottom {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.runs {
  flex: 3 1 380px;
  min-width: 0;
  padding: 4px 0;
}
.panel-head {
  padding: 10px 14px 6px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}
.run {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 36px;
  padding: 0 14px;
  border-top: 1px solid var(--line);
}
.run-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta,
.muted {
  font-size: 11px;
  color: var(--mute);
}
.kpis {
  flex: 2 1 260px;
  min-width: 0;
  padding: 12px 14px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  align-content: start;
}
.kpi {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kv {
  font-size: 22px;
  font-weight: 700;
}
.kd {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ok-ink);
}
.bars {
  grid-column: 1 / -1;
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 40px;
  margin-top: 4px;
}
.bars span {
  flex: 1;
  background: rgba(20, 22, 26, 0.16);
}
.bars span.last {
  background: var(--acc);
}
.insp {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.insp[data-alert='true'] {
  box-shadow: inset 4px 0 0 var(--warn);
  background: rgba(255, 106, 0, 0.06);
}
.insp-head {
  padding: 14px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-bottom: 1px solid var(--line);
}
.insp-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
}
.pct {
  font-size: 15px;
  font-weight: 700;
}
.detail {
  margin: 0;
  padding: 12px 16px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 7px 14px;
  border-bottom: 1px solid var(--line);
}
.detail dd {
  margin: 0;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.insp-actions {
  display: flex;
  gap: 6px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
}
.insp-actions > * {
  flex: 1;
}
.insp-actions button.stop {
  color: var(--warn-ink);
  box-shadow: inset 0 0 0 1.5px var(--warn);
}
.loghead {
  padding: 10px 16px 6px;
}
.log {
  flex: 1;
  min-height: 160px;
  margin: 0 10px 10px;
  padding: 10px 12px;
  background: rgba(20, 22, 26, 0.9);
  color: #d9dce3;
  font-size: 11.5px;
  line-height: 1.8;
  overflow: auto;
}
.lt {
  color: #a3a8b5;
  margin-right: 6px;
}
.ok {
  color: #c8f56a;
}
.bad {
  color: #ffb27a;
}
</style>
