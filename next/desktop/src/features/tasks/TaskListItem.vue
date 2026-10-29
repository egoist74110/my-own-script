<script setup lang="ts">
import { computed } from 'vue'
import StatusPill from '@/components/StatusPill.vue'
import type { PillState } from '@/components/pill'
import MiniRoute from './MiniRoute.vue'
import type { DotState } from './route'

/**
 * 任务列表项：任务名；状态标签 + 时间；底部一条与仓库线路色同色的小线路。
 * 是个 button：Tab 可聚焦，Enter 选择；选中态用“选中”底色，不改文字色。
 */
const props = defineProps<{
  name: string
  /** 右侧时间/进度文案，如“34 分钟前”“从未运行”。 */
  when: string
  pill: PillState | null
  dots: DotState[]
  /** 仓库线路色（CSS 颜色值）。 */
  color: string
  selected?: boolean
}>()
const style = computed(() => ({ '--c': props.color }))
</script>

<template>
  <button
    type="button"
    class="task-item"
    :style="style"
    :aria-current="selected ? 'true' : undefined"
    :data-selected="selected ? 'true' : 'false'"
  >
    <span class="n1" :title="name">{{ name }}</span>
    <span class="n2">
      <span v-if="pill" class="row-pill-wrap"><StatusPill :state="pill" /></span>
      <span class="when">{{ when }}</span>
    </span>
    <MiniRoute :dots="dots" class="route" />
  </button>
</template>

<style scoped>
.task-item {
  display: flex;
  flex-direction: column;
  align-items: stretch;
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
.task-item:hover {
  background: var(--hover);
}
.task-item[data-selected='true'] {
  background: var(--sel-blur);
}
.n1 {
  font-size: var(--text-body);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.n2 {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: var(--text-sub);
  color: var(--mute);
  white-space: nowrap;
  overflow: hidden;
}
.row-pill-wrap {
  display: inline-flex;
  flex: none;
}
.when {
  overflow: hidden;
  text-overflow: ellipsis;
}
.route {
  margin-top: 3px;
}
</style>
