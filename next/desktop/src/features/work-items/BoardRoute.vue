<script setup lang="ts">
import { TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { tabTriggerId } from '@/components/tabs'

/**
 * 看板列线路（列表顶部的筛选）：每个看板列是一站，站内圆圈写该列条数，点站切换列，当前站墨色实心。
 * 仍是 Reka Tabs（方向键切换、roving focus）；各站 aria-controls 指向页面上承载列表的容器
 * （该容器须设 role="tabpanel"、id=panelId、aria-labelledby=tabTriggerId(panelId, 当前列)）。
 * 条数只有读到过该列的列表才知道；没读到的站圆圈留空，不猜数。
 */
const props = defineProps<{
  columns: string[]
  /** 列名 → 条数文案（如 `12`、`500+`）；缺省表示还没读到。 */
  counts: Record<string, string | undefined>
  label: string
  panelId: string
}>()
const model = defineModel<string>({ required: true })
const attrs = (value: string) => ({
  id: tabTriggerId(props.panelId, value),
  'aria-controls': props.panelId,
})
</script>

<template>
  <TabsRoot v-model="model" orientation="horizontal" class="board-root">
    <TabsList :aria-label="label" class="board" :style="{ '--n': columns.length }">
      <TabsTrigger v-for="c in columns" :key="c" :value="c" as-child>
        <button type="button" class="bst" v-bind="attrs(c)">
          <span class="nm">{{ c }}</span>
          <i class="cnt">{{ counts[c] === undefined ? '' : ' ' + counts[c] }}</i>
        </button>
      </TabsTrigger>
    </TabsList>
  </TabsRoot>
</template>

<style scoped>
.board {
  --c: var(--l-8);
  position: relative;
  display: grid;
  grid-template-columns: repeat(var(--n), minmax(0, 1fr));
  padding: 2px 0 0;
}
/* 穿过各站圆心的一条底线，从第一站圆心到最后一站圆心 */
.board::before {
  content: '';
  position: absolute;
  top: 11px;
  left: calc(50% / var(--n));
  right: calc(50% / var(--n));
  height: 2px;
  background: var(--field-line);
}
.bst {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
  padding: 0 0 4px;
  border: 0;
  border-radius: var(--r-ctl);
  background: none;
  color: var(--mute);
  font: inherit;
  cursor: pointer;
}
/* 站名在 DOM 里排在前面（读屏先读“开发中 3”），视觉上圆圈在上、站名在下 */
.cnt {
  order: -1;
  display: grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  box-sizing: border-box;
  border-radius: 10px;
  border: 2px solid var(--faint);
  background: var(--bg-list);
  color: var(--mute);
  font-style: normal;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}
.nm {
  max-width: 100%;
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
}
.bst:hover .cnt {
  border-color: var(--c);
}
.bst[data-state='active'] {
  color: var(--ink);
  font-weight: 600;
}
.bst[data-state='active'] .cnt {
  border-color: var(--c);
  background: var(--c);
  color: var(--bg-list);
}
</style>
