<script setup lang="ts">
import { computed } from 'vue'

/** 分段能量条：0..segments 段点亮。 */
const props = withDefaults(defineProps<{ value: number; segments?: number; label: string }>(), {
  segments: 20,
})
const lit = computed(() => Math.max(0, Math.min(props.segments, Math.round(props.value))))
</script>

<template>
  <div
    class="energy"
    role="meter"
    :aria-label="label"
    aria-valuemin="0"
    :aria-valuemax="segments"
    :aria-valuenow="lit"
  >
    <span v-for="i in segments" :key="i" class="cell" :data-on="i <= lit"></span>
  </div>
</template>

<style scoped>
.energy {
  display: flex;
  gap: 2px;
  flex: 1;
}
.cell {
  flex: 1;
  height: 8px;
  background: var(--faint);
}
.cell[data-on='true'] {
  background: var(--ink);
}
</style>
