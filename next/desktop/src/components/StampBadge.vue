<script setup lang="ts">
import { computed } from 'vue'

/** 结果印章：CLEAR / FAILED / ROLLBACK。 */
const props = defineProps<{ result: 'clear' | 'failed' | 'rollback' }>()
const text = computed(
  () => ({ clear: 'CLEAR', failed: 'FAILED', rollback: 'ROLLBACK' })[props.result],
)
</script>

<template>
  <span class="stamp ox skew" :data-result="result">{{ text }}</span>
</template>

<style scoped>
.stamp {
  display: inline-block;
  min-width: 64px;
  text-align: center;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 1px;
  padding: 2px 6px;
}
.stamp[data-result='clear'] {
  background: var(--acc);
  color: var(--ink);
}
.stamp[data-result='failed'] {
  background: var(--warn);
  color: var(--ink);
}
.stamp[data-result='rollback'] {
  background: var(--ink);
  color: #fff;
}
</style>
