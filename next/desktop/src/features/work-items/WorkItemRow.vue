<script setup lang="ts">
import { computed } from 'vue'

/**
 * 工单列表项：第一行标题（省略号）+ 优先级；第二行 #编号、指派人、日期（MM-DD）。
 * 任何宽度下都不折行。是个 button：Tab 可聚焦，Enter 选择；选中态用“选中”底色。
 */
const props = defineProps<{
  title: string
  id: number
  assignee?: string | null
  priority?: number | null
  /** 已格式化的 MM-DD。 */
  date: string
  /** 工单类型文字与其圆点颜色（CSS 颜色值）。 */
  type?: string | null
  kindColor: string
  selected?: boolean
}>()
const hasPri = computed(() => props.priority !== null && props.priority !== undefined)
</script>

<template>
  <button
    type="button"
    class="wi-item"
    :aria-current="selected ? 'true' : undefined"
    :data-selected="selected ? 'true' : 'false'"
  >
    <span class="l1">
      <span class="t" :title="title">{{ title }}</span>
      <span v-if="hasPri" class="pri" :data-p="priority">P{{ priority }}</span>
    </span>
    <span class="l2">
      <span class="kd" :style="{ background: kindColor }" :title="type ?? undefined"></span>
      <span class="num">#{{ id }}</span>
      <span class="who" :class="{ none: !assignee }">{{ assignee ?? '未指派' }}</span>
      <span class="num date">{{ date }}</span>
    </span>
  </button>
</template>

<style scoped>
.wi-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
  min-width: 0;
  padding: 9px 10px;
  border: 0;
  border-radius: var(--r-row);
  background: transparent;
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.wi-item:hover {
  background: var(--hover);
}
.wi-item[data-selected='true'] {
  background: var(--sel-blur);
}
.l1,
.l2 {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  white-space: nowrap;
}
.t {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: var(--text-body);
  font-weight: 600;
}
.pri {
  flex: none;
  color: var(--mute);
  font-size: 11px;
  font-weight: 700;
}
.pri[data-p='1'] {
  color: var(--p1);
}
.l2 {
  color: var(--faint);
  font-size: var(--text-sub);
  overflow: hidden;
}
.kd {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.num {
  flex: none;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.who {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--mute);
}
.who.none {
  color: var(--faint);
}
.date {
  margin-left: auto;
}
</style>
