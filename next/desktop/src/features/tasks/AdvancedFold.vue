<script setup lang="ts">
import { ChevronDown, ChevronRight } from 'lucide-vue-next'

/** 默认收起的“高级”折叠区。内容始终在 DOM 里（v-show），收起时不可见也不可聚焦。 */
defineProps<{ title: string }>()
const open = defineModel<boolean>('open', { default: false })
</script>

<template>
  <section class="fold">
    <button
      type="button"
      class="fold-head"
      :aria-expanded="open"
      data-testid="fold-toggle"
      @click="open = !open"
    >
      <component :is="open ? ChevronDown : ChevronRight" :size="14" aria-hidden="true" />
      <span>{{ title }}</span>
    </button>
    <div v-show="open" class="fold-body" data-testid="fold-body"><slot /></div>
  </section>
</template>

<style scoped>
.fold {
  border-top: 1px solid var(--line);
  padding-top: 6px;
}
.fold-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  border: 0;
  background: transparent;
  color: var(--mute);
  font: inherit;
  font-size: var(--text-sub);
  font-weight: 600;
  cursor: pointer;
}
.fold-head:hover {
  color: var(--ink);
}
.fold-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 8px;
}
</style>
