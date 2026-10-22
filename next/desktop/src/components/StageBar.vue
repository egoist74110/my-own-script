<script setup lang="ts">
export type StageState = 'done' | 'run' | 'pending' | 'fail'
export interface Stage {
  code: string
  state: StageState
}
/** 分段阶段条；运行中段带流动斜纹。 */
defineProps<{ stages: Stage[] }>()
const LABEL: Record<StageState, string> = {
  done: '完成',
  run: '运行中',
  pending: '待定',
  fail: '失败',
}
</script>

<template>
  <span class="stages" role="list">
    <span
      v-for="(s, i) in stages"
      :key="i"
      role="listitem"
      class="seg skew ox"
      :class="{ chev: s.state === 'run' }"
      :data-state="s.state"
      :aria-label="`${s.code} ${LABEL[s.state]}`"
      >{{ s.code }}</span
    >
  </span>
</template>

<style scoped>
.stages {
  display: flex;
  gap: 2px;
  width: 100%;
}
.seg {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 18px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.6px;
}
.seg[data-state='done'] {
  background: var(--ink);
  color: var(--acc);
}
.seg[data-state='run'] {
  color: var(--ink);
}
.seg[data-state='fail'] {
  background: var(--warn);
  color: var(--ink);
}
.seg[data-state='pending'] {
  background: rgba(20, 22, 26, 0.07);
  color: var(--mute);
}
</style>
