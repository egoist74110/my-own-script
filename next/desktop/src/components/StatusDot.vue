<script setup lang="ts">
/** 状态点：ok / run（脉冲）/ warn / idle。形状之外另有文字，不单靠颜色传达状态。 */
defineProps<{ state: 'ok' | 'run' | 'warn' | 'idle' }>()
</script>

<template>
  <span class="dot" :data-state="state" aria-hidden="true"></span>
</template>

<style scoped>
.dot {
  display: inline-block;
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--st-queued-dot);
}
.dot[data-state='ok'] {
  background: var(--st-success-dot);
}
.dot[data-state='run'] {
  background: var(--st-running-dot);
  animation: pulse 1.6s ease-out infinite;
}
.dot[data-state='warn'] {
  background: var(--st-stopping-dot);
}
</style>
