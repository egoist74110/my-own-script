<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Search } from 'lucide-vue-next'

/** ⌘K / Ctrl+K 聚焦，Esc 失焦。本轮只是输入框，不做真实搜索。 */
defineProps<{ label: string; placeholder?: string }>()
const model = defineModel<string>({ default: '' })
const el = ref<HTMLInputElement | null>(null)

function onKey(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    el.value?.focus()
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <label class="search cut-xs">
    <Search :size="14" aria-hidden="true" />
    <span class="sr-only">{{ label }}</span>
    <input
      ref="el"
      v-model="model"
      type="search"
      :placeholder="placeholder"
      @keydown.esc="el?.blur()"
    />
    <kbd class="mono" aria-hidden="true">⌘K</kbd>
  </label>
</template>

<style scoped>
.search {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: var(--target-min);
  width: 240px;
  max-width: 100%;
  box-sizing: border-box;
  padding: 0 10px;
  background: rgba(255, 255, 255, 0.75);
  box-shadow: inset 0 0 0 1px var(--line);
  color: var(--mute);
}
input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: 0;
  outline: none;
  font: inherit;
  color: var(--ink);
}
kbd {
  font-size: 10px;
  padding: 1px 5px;
  box-shadow: inset 0 0 0 1px var(--line);
}
.search:focus-within {
  outline: 2px solid var(--warn);
  outline-offset: -2px;
}
</style>
