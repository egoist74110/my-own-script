<script setup lang="ts">
import { computed } from 'vue'
import { PILL_LABEL, type PillState } from './pill'

/** 运行状态胶囊（八态）：颜色只作底与圆点，文字始终是文案。 */
const props = defineProps<{ state: PillState; label?: string }>()
const text = computed(() => props.label || PILL_LABEL[props.state])
</script>

<template>
  <span class="pill" :data-state="state"
    ><span class="dot" aria-hidden="true"></span><slot>{{ text }}</slot></span
  >
</template>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  background: var(--pill-bg);
  color: var(--pill-fg);
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--pill-dot);
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
