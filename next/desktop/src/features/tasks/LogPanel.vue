<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import ToolbarButton from '@/components/ToolbarButton.vue'
import { Copy, Check } from 'lucide-vue-next'
import type { LogLine } from './useRunLogs'

const props = defineProps<{
  lines: LogLine[]
  totalLineCount?: number
  loading?: boolean
  warning?: string | null
}>()

const logContainer = ref<HTMLElement | null>(null)
const copied = ref(false)

// 自动滚动到最新行
watch(
  () => props.lines.length,
  async () => {
    await nextTick()
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  },
)

async function copyLogs() {
  const text = props.lines.map((l) => l.text).join('\n')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    // 忽略剪贴板错误
  }
}
</script>

<template>
  <div class="log-panel" aria-label="实时日志">
    <div class="log-toolbar">
      <span class="log-meta mono">共 {{ totalLineCount ?? lines.length }} 行日志</span>
      <span v-if="warning" class="log-warning" data-testid="log-gap-warning">{{ warning }}</span>
      <ToolbarButton
        :label="copied ? '已复制' : '复制日志'"
        class="copy-btn"
        data-testid="copy-logs-btn"
        @click="copyLogs"
      >
        <Check v-if="copied" :size="13" aria-hidden="true" />
        <Copy v-else :size="13" aria-hidden="true" />
      </ToolbarButton>
    </div>
    <div ref="logContainer" class="log-content mono" data-testid="log-content">
      <div v-if="loading && lines.length === 0" class="log-placeholder">正在读取日志…</div>
      <div v-else-if="lines.length === 0" class="log-placeholder">暂无日志输出</div>
      <div v-for="l in lines" :key="l.seq" class="log-line">
        <span class="log-seq">{{ l.seq }}</span>
        <span class="log-text">{{ l.text }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-panel {
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border-left: 1px solid var(--line);
  min-height: 0;
  height: 100%;
}
.log-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--ink) 2%, transparent);
}
.log-meta {
  font-size: 11px;
  color: var(--mute);
}
.log-warning {
  font-size: 11px;
  color: var(--bn-warn-fg);
  background: var(--bn-warn-bg);
  padding: 1px 6px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--bn-warn-line);
}
.copy-btn {
  height: 22px;
  font-size: 11px;
  padding: 0 4px;
}
.log-content {
  flex: 1;
  overflow: auto;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-all;
  user-select: text;
}
.log-placeholder {
  color: var(--mute);
  text-align: center;
  padding: 24px;
  font-style: italic;
}
.log-line {
  display: flex;
  gap: 10px;
}
.log-seq {
  color: var(--disabled);
  flex: none;
  min-width: 32px;
  text-align: right;
  user-select: none;
}
.log-text {
  flex: 1;
}
.mono {
  font-family: var(--font-mono);
}
</style>
