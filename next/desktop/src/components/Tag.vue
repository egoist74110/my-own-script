<script setup lang="ts">
/** 中性小标签（标签 / 计数 / 状态词）。tone 只影响底色与文字加深色。 */
withDefaults(defineProps<{ tone?: 'neutral' | 'ok' | 'warn' }>(), { tone: 'neutral' })
</script>

<template>
  <span class="tag" :data-tone="tone"><slot /></span>
</template>

<style scoped>
.tag {
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--ctl);
  color: var(--ink);
  font-size: var(--text-sub);
  line-height: 18px;
}
.tag[data-tone='ok'] {
  background: var(--st-success-bg);
  color: var(--st-success-fg);
}
.tag[data-tone='warn'] {
  background: var(--st-verify-bg);
  color: var(--st-verify-fg);
}
</style>
