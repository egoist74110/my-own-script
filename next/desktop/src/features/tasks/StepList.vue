<script setup lang="ts">
import { computed, type Component } from 'vue'
import { Check, CircleHelp, GitPullRequest, Hammer, Send, Undo2, X } from 'lucide-vue-next'
import { openExternal } from '@/components/open-external'
import type { EffectView, RunStatus, StepView, TargetInput } from './api'
import { buildStations, type Station } from './route'

/**
 * 本次运行的线路图：每个步骤是一站。已完成实心、当前站带光晕、没执行的站虚线灰色；
 * 站名下方一行小字写用时 / 构建号 / “没有执行”。路段走过为实线，没走为虚线。
 * 站点状态由 runStatus 修正：运行已结束时，没走完的步骤不再显示“运行中”。
 */
const props = defineProps<{
  steps: StepView[]
  runStatus?: RunStatus | null
  /** 仓库线路色（CSS 颜色值）。 */
  color?: string
  /** 运行快照里的目标（站名用目标名称、副标题写构建定义与环境）。 */
  targets?: TargetInput[] | null
  /** 已发生的远端副作用（Release / 构建在 ADO 创建的编号）。 */
  effects?: EffectView[] | null
  /** 运行的失败原因。 */
  summary?: string | null
  /** 活动运行的“现在”（毫秒），用于当前站的用时；缺省取当前时间。 */
  now?: number
}>()

const stations = computed<Station[]>(() =>
  buildStations(props.steps, props.runStatus, props.now, {
    targets: props.targets,
    effects: props.effects,
    summary: props.summary,
  }),
)

const KIND_ICON: Record<string, Component> = {
  git: GitPullRequest,
  build: Hammer,
  release: Send,
  rollback: Undo2,
}
function iconFor(s: Station): Component {
  if (s.state === 'fail') return X
  if (s.state === 'verify') return CircleHelp
  return KIND_ICON[s.kind] ?? Check
}
</script>

<template>
  <div class="route" aria-label="执行步骤" :style="color ? { '--c': color } : undefined">
    <div v-if="steps.length === 0" class="steps-empty">等待开始…</div>
    <ol v-else class="track" :style="{ '--n': stations.length }">
      <li
        v-for="(s, i) in stations"
        :key="s.key"
        class="stn"
        :data-state="s.state"
        :data-prev="i > 0 ? stations[i - 1]!.state : undefined"
        :title="`${s.name}：${s.sub}`"
      >
        <i class="node"><component :is="iconFor(s)" :size="14" aria-hidden="true" /></i>
        <b class="name" :data-testid="`station-name-${s.key}`">{{ s.name }}</b>
        <small class="sub" :data-testid="`station-sub-${s.key}`">{{ s.sub }}</small>
        <small v-if="s.detail" class="sub detail" :data-testid="`station-detail-${s.key}`">{{
          s.detail
        }}</small>
        <a
          v-if="s.link"
          class="stn-link"
          :href="s.link"
          :data-testid="`station-link-${s.key}`"
          @click.prevent="openExternal(s.link)"
          >在 ADO 中打开</a
        >
      </li>
    </ol>
  </div>
</template>

<style scoped>
.route {
  --c: var(--l-8);
  padding: 18px 8px 4px;
  /* 站多时只在这条线路自己的容器里横向滚动，不撑宽整页 */
  overflow-x: auto;
}
.stn-link {
  font-size: var(--text-sub);
  color: var(--link);
  cursor: pointer;
}
.steps-empty {
  padding: 16px;
  color: var(--mute);
  font-size: var(--text-sub);
  text-align: center;
}
.track {
  display: grid;
  grid-template-columns: repeat(var(--n), minmax(104px, 1fr));
  margin: 0;
  padding: 0;
  list-style: none;
}
.stn {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
  text-align: center;
}
/* 路段：从上一站圆心到本站圆心。上一站已走完（done）才是实线，否则虚线 */
.stn:not(:first-child)::before {
  content: '';
  position: absolute;
  left: -50%;
  width: 100%;
  top: 13px;
  height: 4px;
  border-radius: 2px;
  background: repeating-linear-gradient(90deg, var(--c) 0 8px, transparent 8px 14px);
  opacity: 0.4;
}
.stn[data-prev='done']:not(:first-child)::before {
  background: var(--c);
  opacity: 1;
}
.node {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  box-sizing: border-box;
  border-radius: 50%;
  border: 4px solid var(--c);
  background: var(--bg-window);
  color: var(--c);
}
.stn[data-state='done'] .node,
.stn[data-state='here'] .node {
  background: var(--c);
  color: var(--bg-window);
}
.stn[data-state='here'] .node {
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--c) 22%, transparent);
}
.stn[data-state='fail'] .node {
  border-color: var(--st-failed-dot);
  background: var(--st-failed-dot);
  color: #fff;
}
.stn[data-state='verify'] .node {
  border-color: var(--st-verify-dot);
  background: var(--st-verify-dot);
  color: #fff;
}
.stn[data-state='skip'] .node,
.stn[data-state='wait'] .node {
  border-style: dashed;
  border-color: var(--faint);
  color: var(--faint);
}
.name {
  margin-top: 8px;
  max-width: 100%;
  font-size: var(--text-body);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sub {
  max-width: 100%;
  margin-top: 1px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--text-sub);
  color: var(--mute);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stn[data-state='skip'] .sub,
.stn[data-state='wait'] .sub {
  font-family: var(--font-sans);
}
.stn[data-state='fail'] .sub {
  color: var(--st-failed-fg);
}
.stn[data-state='verify'] .sub {
  color: var(--st-verify-fg);
}
</style>
