<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

export type Decision = 'once' | 'always' | 'deny'

/** 内联审批条。Y 允许一次 / A 总是允许 / N 拒绝；输入框、文本域、可编辑区聚焦时不响应快捷键。 */
defineProps<{ command: string }>()
const emit = defineEmits<{ decide: [decision: Decision] }>()

const KEYS: Record<string, Decision> = { y: 'once', a: 'always', n: 'deny' }

function isTyping(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  return t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)
}

function onKey(e: KeyboardEvent) {
  if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return
  const d = KEYS[e.key.toLowerCase()]
  if (!d || isTyping(e.target) || isTyping(document.activeElement)) return
  e.preventDefault()
  emit('decide', d)
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div role="group" aria-label="工具审批" class="approval cut-xs" data-testid="approval-bar">
    <span class="stripe" aria-hidden="true"></span>
    <span class="ask ox">APPROVE?</span>
    <span class="cmd mono"><span class="prompt" aria-hidden="true">$</span> {{ command }}</span>
    <button type="button" class="b cut-xs" data-act="once" @click="emit('decide', 'once')">
      允许 <kbd class="mono">Y</kbd>
    </button>
    <button type="button" class="b cut-xs" data-act="always" @click="emit('decide', 'always')">
      本会话总是 <kbd class="mono">A</kbd>
    </button>
    <button type="button" class="b cut-xs" data-act="deny" @click="emit('decide', 'deny')">
      拒绝 <kbd class="mono">N</kbd>
    </button>
  </div>
</template>

<style scoped>
.approval {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 12px 8px 22px;
  background: var(--ink);
  color: #fff;
  overflow: hidden;
}
.stripe {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 8px;
  background-image: repeating-linear-gradient(-45deg, #ff6a00 0 6px, #14161a 6px 12px);
  background-size: 8px 24px;
  animation: nudge 1.6s ease-in-out infinite;
}
.ask {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1.6px;
  color: #ff9a4d;
}
.cmd {
  flex: 1 1 240px;
  min-width: 0;
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prompt {
  color: var(--acc);
}
.b {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: var(--target-min);
  padding: 0 12px;
  border: 0;
  cursor: pointer;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
}
.b[data-act='once'] {
  background: var(--acc);
  color: var(--ink);
}
.b[data-act='always'] {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}
.b[data-act='deny'] {
  background: transparent;
  color: #ffb27a;
  box-shadow: inset 0 0 0 1px #ff6a00;
}
kbd {
  font-size: 10px;
  padding: 0 5px;
  box-shadow: inset 0 0 0 1px currentColor;
}
</style>
