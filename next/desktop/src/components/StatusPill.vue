<script setup lang="ts">
import { computed, type Component } from 'vue'
import { Ban, Check, CircleHelp, Clock, Loader, Minus, Square, X } from 'lucide-vue-next'
import { PILL_LABEL, type PillState } from './pill'

/** 运行状态标签（八态）：19px 高、图标 + 文字，任何宽度不折行；颜色只作底，不单靠颜色表达状态。 */
const props = defineProps<{ state: PillState; label?: string }>()
const text = computed(() => props.label || PILL_LABEL[props.state])
const ICONS: Record<PillState, Component> = {
  queued: Clock,
  running: Loader,
  stopping: Square,
  success: Check,
  failed: X,
  cancelled: Ban,
  verify: CircleHelp,
  disabled: Minus,
}
</script>

<template>
  <span class="pill" :data-state="state"
    ><component
      :is="ICONS[state]"
      class="dot"
      :size="11"
      :stroke-width="2.4"
      aria-hidden="true"
    /><slot>{{ text }}</slot></span
  >
</template>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  flex: none;
  gap: 4px;
  height: 19px;
  padding: 0 7px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  background: var(--pill-bg);
  color: var(--pill-fg);
}
.dot {
  flex: none;
}
.pill[data-state='running'] .dot {
  animation: pulse 1.6s ease-out infinite;
}
.pill[data-state='queued'] {
  --pill-bg: var(--st-queued-bg);
  --pill-fg: var(--st-queued-fg);
  --pill-dot: var(--st-queued-dot);
}
.pill[data-state='running'] {
  --pill-bg: var(--st-running-bg);
  --pill-fg: var(--st-running-fg);
  --pill-dot: var(--st-running-dot);
}
.pill[data-state='stopping'] {
  --pill-bg: var(--st-stopping-bg);
  --pill-fg: var(--st-stopping-fg);
  --pill-dot: var(--st-stopping-dot);
}
.pill[data-state='success'] {
  --pill-bg: var(--st-success-bg);
  --pill-fg: var(--st-success-fg);
  --pill-dot: var(--st-success-dot);
}
.pill[data-state='failed'] {
  --pill-bg: var(--st-failed-bg);
  --pill-fg: var(--st-failed-fg);
  --pill-dot: var(--st-failed-dot);
}
.pill[data-state='cancelled'] {
  --pill-bg: var(--st-cancelled-bg);
  --pill-fg: var(--st-cancelled-fg);
  --pill-dot: var(--st-cancelled-dot);
}
.pill[data-state='verify'] {
  --pill-bg: var(--st-verify-bg);
  --pill-fg: var(--st-verify-fg);
  --pill-dot: var(--st-verify-dot);
}
.pill[data-state='disabled'] {
  --pill-bg: var(--st-disabled-bg);
  --pill-fg: var(--st-disabled-fg);
  --pill-dot: var(--st-disabled-dot);
}
</style>
