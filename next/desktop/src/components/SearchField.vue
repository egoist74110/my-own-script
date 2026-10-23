<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Search } from 'lucide-vue-next'

/** ⌘K / Ctrl+K 聚焦，Esc 失焦。只是输入框，过滤由页面自己做。 */
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
  <label class="search">
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
  gap: 6px;
  min-height: var(--ctl-h);
  box-sizing: border-box;
  padding: 0 8px;
  border-radius: var(--r-row);
  background: var(--ctl);
  color: var(--mute-tint);
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
input::placeholder {
  color: var(--mute-tint);
}
kbd {
  font-size: 11px;
  color: var(--mute-tint);
}
.search:focus-within {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
}
input:focus-visible {
  outline: none;
}
</style>
