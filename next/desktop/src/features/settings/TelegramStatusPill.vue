<script setup lang="ts">
import { computed } from 'vue'
import { POLLER_STATE_LABEL, type PollerView } from './api'

const props = defineProps<{ state: PollerView['state'] }>()

const label = computed(() => POLLER_STATE_LABEL[props.state] ?? props.state)

const colorState = computed(() => {
  switch (props.state) {
    case 'polling':
      return 'running'
    case 'starting':
      return 'queued'
    case 'stopping':
      return 'stopping'
    case 'backoff':
    case 'webhook_set':
      return 'verify'
    case 'conflict':
    case 'token_invalid':
    case 'store_unavailable':
      return 'failed'
    case 'disabled':
    default:
      return 'disabled'
  }
})
</script>

<template>
  <span class="pill" :data-state="colorState" :data-poller-state="state">
    <span class="dot" aria-hidden="true"></span>{{ label }}
  </span>
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
.pill[data-state='failed'] {
  --pill-bg: var(--st-failed-bg);
  --pill-fg: var(--st-failed-fg);
  --pill-dot: var(--st-failed-dot);
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
@keyframes pulse {
  0% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.4;
    transform: scale(0.85);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
