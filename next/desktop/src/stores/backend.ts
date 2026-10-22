import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { AlertState, ConnectionState, EventEnvelope, HelloData } from '@/api/events'

const QUIET: AlertState = { active: false, reason: null, changed_at: '' }

function isAlertState(v: unknown): v is AlertState {
  if (typeof v !== 'object' || v === null) return false
  const a = v as Record<string, unknown>
  return (
    typeof a.active === 'boolean' &&
    (a.reason === null || typeof a.reason === 'string') &&
    typeof a.changed_at === 'string'
  )
}

/** 后端连接与告警态。告警只由后端 `system.alert` / `system.hello` 事件驱动。 */
export const useBackendStore = defineStore('backend', () => {
  const connection = ref<ConnectionState>('connecting')
  const pid = ref<number | null>(null)
  const version = ref<string | null>(null)
  const latencyMs = ref<number | null>(null)
  const alert = ref<AlertState>({ ...QUIET })
  const lastSeq = ref(-1)
  /** 最近一次 `settings.changed` 事件带的 revision；设置页据此让查询失效（不存放任何设置内容）。 */
  const settingsRevision = ref<number | null>(null)

  const denied = computed(() => (alert.value.active ? 1 : 0))

  function setConnection(state: ConnectionState) {
    connection.value = state
    if (state !== 'online') latencyMs.value = null
  }

  function setLatency(ms: number) {
    latencyMs.value = Math.round(ms)
  }

  function applyEvent(ev: EventEnvelope) {
    if (ev.type === 'system.hello') {
      const d = ev.data as Partial<HelloData>
      // hello 重新对齐 seq 基线（后端重启后 seq 会回退）
      lastSeq.value = ev.seq
      if (typeof d.pid === 'number') pid.value = d.pid
      if (typeof d.version === 'string') version.value = d.version
      if (isAlertState(d.alert)) alert.value = d.alert
      return
    }
    if (ev.seq <= lastSeq.value) return
    lastSeq.value = ev.seq
    if (ev.type === 'system.alert' && isAlertState(ev.data)) {
      alert.value = ev.data
    }
    if (ev.type === 'settings.changed' && typeof ev.data.revision === 'number') {
      settingsRevision.value = ev.data.revision
    }
  }

  return {
    connection,
    pid,
    version,
    latencyMs,
    alert,
    lastSeq,
    settingsRevision,
    denied,
    setConnection,
    setLatency,
    applyEvent,
  }
})
