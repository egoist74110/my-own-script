<script setup lang="ts">
/** 黑色块标签（编号 / 类型）。tone 只影响底色，文字始终是墨色或白色。 */
withDefaults(defineProps<{ tone?: 'ink' | 'acc' | 'warn' }>(), { tone: 'ink' })
</script>

<template>
  <span class="blk" :data-tone="tone"><slot /></span>
</template>

<style scoped>
.blk[data-tone='acc'] {
  background: var(--acc);
  color: var(--ink);
}
.blk[data-tone='warn'] {
  background: var(--warn);
  color: var(--ink);
}
</style>
