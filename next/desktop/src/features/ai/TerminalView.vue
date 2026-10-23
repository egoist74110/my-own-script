<script setup lang="ts">
import { inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { backendRuntimeKey } from '@/app/backend-runtime'
import {
  createAttachFrame,
  createAuthFrame,
  createInputFrames,
  createResizeFrame,
  formatEndedReason,
  formatSessionState,
  parseBinaryFrame,
} from './terminal-protocol'

const props = defineProps<{
  sessionId: string
  sessionState: string
  exitCode?: number | null
  endedReason?: string | null
}>()

const runtime = inject(backendRuntimeKey)

const containerRef = ref<HTMLDivElement | null>(null)
const isConnected = ref(false)
const connectionError = ref<string | null>(null)

let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let ws: WebSocket | null = null
let ro: ResizeObserver | null = null
let watermark = 0n
let retryTimer: ReturnType<typeof setTimeout> | null = null
let stableTimer: ReturnType<typeof setTimeout> | null = null
let retryCount = 0
let unmounted = false

function isEnded(): boolean {
  return props.sessionState === 'ended' || props.sessionState === 'failed'
}

function cleanupWs() {
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  if (stableTimer) {
    clearTimeout(stableTimer)
    stableTimer = null
  }
  if (ws) {
    ws.onopen = null
    ws.onmessage = null
    ws.onerror = null
    ws.onclose = null
    try {
      ws.close()
    } catch {
      // 忽略已关闭异常
    }
    ws = null
  }
  isConnected.value = false
}

function initTerminal() {
  if (!containerRef.value) return
  if (term) return

  term = new Terminal({
    cursorBlink: true,
    fontFamily: 'ui-monospace, SF Mono, Menlo, Monaco, "Cascadia Mono", monospace',
    fontSize: 13,
    lineHeight: 1.35,
    theme: {
      background: '#141416',
      foreground: '#f4f4f5',
      cursor: '#0a63d6',
      selectionBackground: 'rgba(10, 99, 214, 0.3)',
    },
    convertEol: true,
    disableStdin: isEnded(),
  })

  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)

  try {
    term.open(containerRef.value)
    fitAddon.fit()
  } catch {
    // jsdom 环境兼容
  }

  term.onData((data: string) => {
    if (isEnded()) return
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    const frames = createInputFrames(data)
    for (const frame of frames) {
      ws.send(frame)
    }
  })

  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    ro = new ResizeObserver(() => {
      if (!term || !fitAddon) return
      try {
        fitAddon.fit()
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(createResizeFrame(term.rows, term.cols))
        }
      } catch {
        // 忽略布局异常
      }
    })
    ro.observe(containerRef.value)
  }
}

function connectWs() {
  cleanupWs()
  if (unmounted) return

  const conn = runtime?.getConnection?.()
  if (!conn) {
    connectionError.value = '未检测到后端连接凭据'
    return
  }

  connectionError.value = null
  const url = `ws://127.0.0.1:${conn.port}/api/ai/terminals/${props.sessionId}/ws`

  try {
    ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
  } catch {
    scheduleRetry()
    return
  }

  ws.onopen = () => {
    isConnected.value = true
    if (stableTimer) {
      clearTimeout(stableTimer)
    }
    // 只有在连接持续稳定 ≥10 秒后才把重连计数清零，避免“接受后立即断开”时以 500ms 固定间隔无限重连
    stableTimer = setTimeout(() => {
      retryCount = 0
      stableTimer = null
    }, 10_000)

    if (!ws) return
    // 首帧 auth，token 仅在内存传递，不进 URL、DOM、storage 与日志
    ws.send(createAuthFrame(conn.token))
    // 续接当前已接收的最高水位，后端负责回放窗口内剩余字节并转为实时流
    ws.send(createAttachFrame(watermark))
    if (term) {
      ws.send(createResizeFrame(term.rows, term.cols))
    }
  }

  ws.onmessage = (event: MessageEvent) => {
    if (event.data instanceof ArrayBuffer || event.data instanceof Uint8Array) {
      const { payload, nextWatermark } = parseBinaryFrame(event.data, watermark)
      watermark = nextWatermark
      if (payload && payload.length > 0 && term) {
        term.write(payload)
      }
    }
  }

  ws.onerror = () => {
    // 由 onclose 统一调度重连
  }

  ws.onclose = () => {
    if (stableTimer) {
      clearTimeout(stableTimer)
      stableTimer = null
    }
    isConnected.value = false
    if (!unmounted && !isEnded()) {
      scheduleRetry()
    }
  }
}

function scheduleRetry() {
  if (unmounted || isEnded()) return
  if (retryTimer) return
  const delay = Math.min(500 * 2 ** retryCount, 5000)
  retryCount++
  retryTimer = setTimeout(() => {
    retryTimer = null
    connectWs()
  }, delay)
}

watch(
  () => props.sessionState,
  (state) => {
    if (term) {
      term.options.disableStdin = state === 'ended' || state === 'failed'
    }
    if (state === 'ended' || state === 'failed') {
      if (retryTimer) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      if (stableTimer) {
        clearTimeout(stableTimer)
        stableTimer = null
      }
    }
  },
)

watch(
  () => props.sessionId,
  () => {
    watermark = 0n
    retryCount = 0
    if (term) {
      term.reset()
      term.options.disableStdin = isEnded()
    }
    connectWs()
  },
)

onMounted(() => {
  unmounted = false
  initTerminal()
  connectWs()
})

onUnmounted(() => {
  unmounted = true
  cleanupWs()
  if (ro) {
    ro.disconnect()
    ro = null
  }
  if (term) {
    term.dispose()
    term = null
  }
  fitAddon = null
})
</script>

<template>
  <div class="term-wrapper" data-testid="terminal-view">
    <div
      v-if="isEnded()"
      class="term-status-bar"
      :data-state="props.sessionState"
      role="status"
      data-testid="terminal-status-bar"
    >
      <span class="term-status-badge">{{ formatSessionState(props.sessionState) }}</span>
      <span class="term-status-info">
        结束原因：{{ formatEndedReason(props.endedReason) }}
        <template v-if="props.exitCode !== null && props.exitCode !== undefined">
          · 退出码：{{ props.exitCode }}
        </template>
        · 终端已进入只读回放状态
      </span>
    </div>
    <div v-else-if="connectionError" class="term-error-bar" role="alert">
      {{ connectionError }}
    </div>
    <div ref="containerRef" class="term-container" tabindex="0" aria-label="终端输出"></div>
  </div>
</template>

<style scoped>
.term-wrapper {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #141416;
  position: relative;
}
.term-status-bar {
  flex: none;
  height: 32px;
  background: #1f1f23;
  border-bottom: 1px solid #2d2d34;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  font-size: 12px;
  color: #a1a1aa;
}
.term-status-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
  background: #27272a;
  color: #e4e4e7;
}
.term-status-bar[data-state='ended'] .term-status-badge {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}
.term-status-bar[data-state='failed'] .term-status-badge {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}
.term-status-info {
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.term-error-bar {
  flex: none;
  background: rgba(239, 68, 68, 0.2);
  color: #fca5a5;
  padding: 6px 14px;
  font-size: 12px;
  border-bottom: 1px solid rgba(239, 68, 68, 0.3);
}
.term-container {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 8px 12px;
  outline: none;
}
.term-container :deep(.xterm) {
  height: 100%;
}
.term-container :deep(.xterm-viewport) {
  background: #141416 !important;
}
</style>
