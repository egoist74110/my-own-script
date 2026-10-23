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
  <div role="group" aria-label="工具审批" class="approval" data-testid="approval-bar">
    <span class="ask">需要你的批准</span>
    <span class="cmd mono"><span class="prompt" aria-hidden="true">$</span> {{ command }}</span>
    <div class="acts">
      <button type="button" class="b" data-act="once" @click="emit('decide', 'once')">
        允许 <kbd class="mono">Y</kbd>
      </button>
      <button type="button" class="b" data-act="always" @click="emit('decide', 'always')">
        本会话总是 <kbd class="mono">A</kbd>
      </button>
      <button type="button" class="b" data-act="deny" @click="emit('decide', 'deny')">
        拒绝 <kbd class="mono">N</kbd>
      </button>
    </div>
  </div>
</template>

<style scoped>
.approval {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--bn-warn-bg);
  color: var(--bn-warn-fg);
  box-shadow: inset 0 0 0 1px var(--bn-warn-line);
}
.ask {
  font-size: var(--text-sub);
  font-weight: 700;
}
.cmd {
  flex: 1 1 240px;
  min-width: 0;
  font-size: var(--text-sub);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.acts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.b {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: var(--ctl-h);
  min-width: var(--target-min);
  padding: 0 12px;
  border: 0;
  border-radius: var(--r-ctl);
  background: var(--bg-window);
  color: var(--ink);
  font: inherit;
  font-size: var(--text-body);
  cursor: pointer;
  box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.18);
}
.b[data-act='once'] {
  background: var(--accent);
  color: var(--on-accent);
  font-weight: 600;
  box-shadow: none;
}
.b[data-act='deny'] {
  color: var(--danger);
}
kbd {
  font-size: 11px;
  padding: 0 4px;
  border-radius: 3px;
  box-shadow: inset 0 0 0 1px currentColor;
  opacity: 0.85;
}
</style>
