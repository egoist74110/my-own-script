<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Ellipsis } from 'lucide-vue-next'

/**
 * 「⋯」下拉菜单：次要操作收在这里。菜单项由插槽提供，写成 `<button role="menuitem">`（可用 .menu-item 样式类）。
 * 菜单面板用 v-show 保持在 DOM 里，点任意菜单项后自动收起；Esc、点菜单外也会收起，Esc 把焦点还给触发按钮。
 * 方向键在菜单项之间移动。
 */
defineProps<{ label: string }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)

function items(): HTMLButtonElement[] {
  return Array.from(
    panel.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [],
  ).filter((el) => !el.disabled && getComputedStyle(el).display !== 'none')
}
async function toggle() {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    items()[0]?.focus()
  }
}
function close(restoreFocus: boolean) {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}
function onPanelClick(e: MouseEvent) {
  const t = e.target as Element | null
  if (t?.closest('[role="menuitem"]')) close(false)
}
function onPanelKey(e: KeyboardEvent) {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  const list = items()
  if (list.length === 0) return
  e.preventDefault()
  const i = list.indexOf(document.activeElement as HTMLButtonElement)
  const next = e.key === 'ArrowDown' ? (i + 1) % list.length : (i - 1 + list.length) % list.length
  list[next]?.focus()
}
function onDocPointer(e: Event) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) close(false)
}
function onDocKey(e: KeyboardEvent) {
  if (open.value && e.key === 'Escape') {
    e.stopPropagation()
    close(true)
  }
}
onMounted(() => {
  document.addEventListener('pointerdown', onDocPointer)
  document.addEventListener('keydown', onDocKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocPointer)
  document.removeEventListener('keydown', onDocKey)
})
</script>

<template>
  <div ref="root" class="overflow-menu">
    <button
      ref="trigger"
      type="button"
      class="trigger"
      :aria-label="label"
      :title="label"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="toggle"
    >
      <Ellipsis :size="16" aria-hidden="true" />
    </button>
    <div
      v-show="open"
      ref="panel"
      class="panel"
      role="menu"
      :aria-label="label"
      @click="onPanelClick"
      @keydown="onPanelKey"
    >
      <slot />
    </div>
  </div>
</template>

<style scoped>
.overflow-menu {
  position: relative;
  display: inline-flex;
}
.trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--target-min);
  height: var(--ctl-h);
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  background: var(--bg-window);
  color: var(--ink);
  cursor: pointer;
}
.trigger:hover,
.trigger[aria-expanded='true'] {
  background: var(--hover);
}
.panel {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  min-width: 168px;
  padding: 4px;
  border-radius: var(--r-group);
  background: var(--bg-window);
  box-shadow:
    0 0 0 0.5px var(--line),
    0 8px 24px rgba(0, 0, 0, 0.18);
}
.panel :slotted(.menu-item) {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: var(--ctl-h);
  padding: 0 10px;
  border: 0;
  border-radius: var(--r-ctl);
  background: transparent;
  color: var(--ink);
  font: inherit;
  font-size: var(--text-body);
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
}
.panel :slotted(.menu-item:hover:not(:disabled)),
.panel :slotted(.menu-item:focus-visible) {
  background: var(--hover);
}
.panel :slotted(.menu-item:disabled) {
  color: var(--disabled);
  cursor: not-allowed;
}
.panel :slotted(.menu-item[data-danger='true']) {
  color: var(--danger);
}
.panel :slotted(.menu-sep) {
  height: 1px;
  margin: 4px 2px;
  background: var(--line);
}
</style>
