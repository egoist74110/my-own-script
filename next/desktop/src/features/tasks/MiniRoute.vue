<script setup lang="ts">
import type { DotState } from './route'

/**
 * 迷你线路：一串 7px 圆点 + 短路段，表示一次运行各阶段的状态（列表项、运行记录共用）。
 * 纯装饰，状态由旁边的状态标签用文字表达，所以对读屏隐藏。线路色由外层的 --c 或 color 给出。
 */
defineProps<{ dots: DotState[]; color?: string }>()
</script>

<template>
  <span class="mini" :style="color ? { '--c': color } : undefined" aria-hidden="true">
    <template v-for="(d, i) in dots" :key="i">
      <span v-if="i > 0" class="seg" :data-full="dots[i - 1] === 'ok' ? 'true' : 'false'"></span>
      <span class="dot" :data-state="d"></span>
    </template>
  </span>
</template>

<style scoped>
.mini {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  flex: none;
}
.dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 1.5px solid var(--c);
  background: var(--bg-window);
  box-sizing: border-box;
}
.dot[data-state='ok'] {
  background: var(--c);
}
.dot[data-state='run'] {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--c) 25%, transparent);
}
.dot[data-state='bad'] {
  border-color: var(--st-failed-dot);
  background: var(--st-failed-dot);
}
.dot[data-state='warn'] {
  border-color: var(--st-verify-dot);
  background: var(--st-verify-dot);
}
.dot[data-state='idle'] {
  border-color: color-mix(in srgb, var(--c) 45%, var(--bg-window));
}
.seg {
  flex: none;
  width: 22px;
  height: 2px;
  background: var(--c);
  opacity: 0.3;
}
.seg[data-full='true'] {
  opacity: 1;
}
</style>
