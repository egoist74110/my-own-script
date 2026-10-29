<script setup lang="ts">
import { computed } from 'vue'
import { Check } from 'lucide-vue-next'

/**
 * 工单所在看板列的站点线路：已过的站实心、当前站实心带光晕、之后的站虚线灰。
 * 站点就是接口给的看板列，按顺序排；工单的 board_column 不在其中时不画（不猜位置）。
 */
const props = defineProps<{ columns: string[]; current?: string | null }>()
const at = computed(() => (props.current ? props.columns.indexOf(props.current) : -1))
function state(i: number): 'done' | 'here' | 'wait' {
  return i < at.value ? 'done' : i === at.value ? 'here' : 'wait'
}
const SUB = { done: '已过', here: '停在这里', wait: '' } as const
</script>

<template>
  <div v-if="at >= 0" class="route" aria-label="看板列线路">
    <ol class="track" :style="{ '--n': columns.length }">
      <li
        v-for="(c, i) in columns"
        :key="c"
        class="stn"
        :data-state="state(i)"
        :data-prev="i > 0 ? state(i - 1) : undefined"
        :aria-current="state(i) === 'here' ? 'step' : undefined"
      >
        <i class="node"
          ><Check v-if="state(i) === 'done'" :size="14" aria-hidden="true" /><b
            v-else-if="state(i) === 'here'"
            class="core"
            aria-hidden="true"
          ></b
        ></i>
        <b class="name">{{ c }}</b>
        <small class="sub">{{ SUB[state(i)] }}</small>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.route {
  --c: var(--l-8);
  padding: 18px 0 4px;
  max-width: 560px;
  /* 详情区是 overflow:auto 的 flex 列：overflow-x 非 visible 的子项 min-height:auto 会变 0，
     默认 flex-shrink:1 会把它压成一条细带（只剩圆圈上半截 + 纵向滚动条）。不许收缩，高度由内容撑。 */
  flex: none;
  /* 站多时只在这条线路自己的容器里横向滚动，不撑宽整页；纵向不滚（overflow-y 显式 hidden，
     底部 padding 已留出光晕和小字空间） */
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 8px;
}
.track {
  display: grid;
  grid-template-columns: repeat(var(--n), minmax(72px, 1fr));
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
/* 路段：从上一站圆心到本站圆心。上一站已过才是实线，否则虚线 */
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
.stn:not(:first-child)[data-prev='done']::before,
.stn[data-state='here']:not(:first-child)::before {
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
.stn[data-state='wait'] .node {
  border-style: dashed;
  border-color: var(--faint);
}
.core {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--bg-window);
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
.stn[data-state='wait'] .name {
  color: var(--mute);
  font-weight: 500;
}
.sub {
  min-height: 1.4em;
  margin-top: 1px;
  color: var(--faint);
  font-size: var(--text-sub);
  white-space: nowrap;
}
@media (prefers-reduced-motion: no-preference) {
  .stn[data-state='here'] .node {
    transition: box-shadow 0.2s;
  }
}
</style>
