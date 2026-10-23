// 运行日志与步骤事件同步器：WS 订阅 + HTTP 补齐、乱序缓冲、去重与连续 run_seq 水位
import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import type { BackendRuntime } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import type { EventEnvelope } from '@/api/events'
import {
  unwrap,
  type LogPayload,
  type RunEventData,
  type RunResponse,
  type RunStatus,
  type StatePayload,
  type StepView,
} from './api'

export interface LogLine {
  seq: number
  text: string
}

export function useRunLogs(
  runIdRef: Ref<string | null>,
  runtime: BackendRuntime | undefined,
  online: Ref<boolean>,
  api: () => ApiClient | null,
) {
  const lines = ref<LogLine[]>([])
  const currentRun = ref<RunResponse | null>(null)
  const steps = ref<StepView[]>([])
  const status = ref<RunStatus | null>(null)
  const reasonCode = ref<string | null>(null)
  const summary = ref<string>('')
  const watermark = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const gapWarning = ref<string | null>(null)

  const buffer = new Map<number, RunEventData>()
  let abortCtrl: AbortController | null = null
  let activeRunId: string | null = null

  // 内存上限与 DOM 上限，避免几十 MiB 历史造成内存溢出与卡顿
  const MAX_MEMORY_LINES = 2000
  const MAX_DOM_LINES = 1000
  const visibleLines = computed(() => {
    if (lines.value.length <= MAX_DOM_LINES) return lines.value
    return lines.value.slice(lines.value.length - MAX_DOM_LINES)
  })

  // 节流快照刷新
  let snapshotTimer: ReturnType<typeof setTimeout> | null = null
  let snapshotReqId = 0

  // 初次同步回放期间不逐个刷新快照：回放结束后统一刷新一次，避免请求突发
  let refreshAfterLoad = false
  let snapshotInFlight = false
  let snapshotPending = false

  function scheduleSnapshotRefresh(delayMs = 80) {
    if (loading.value) {
      refreshAfterLoad = true
      return
    }
    if (snapshotTimer) {
      clearTimeout(snapshotTimer)
      snapshotTimer = null
    }
    if (delayMs <= 0) {
      void refreshSnapshot()
    } else {
      snapshotTimer = setTimeout(() => {
        snapshotTimer = null
        void refreshSnapshot()
      }, delayMs)
    }
  }

  async function refreshSnapshot() {
    const id = activeRunId
    if (!id || !online.value) return
    // 单飞：在途时只记一次待刷新，结束后再取一次最新快照
    if (snapshotInFlight) {
      snapshotPending = true
      return
    }
    snapshotInFlight = true
    const reqId = ++snapshotReqId
    try {
      const client = api()
      if (!client) return
      const snap = await unwrap(
        client.GET('/api/runs/{run_id}', {
          params: { path: { run_id: id } },
        }),
      )
      if (activeRunId !== id || reqId !== snapshotReqId) return
      currentRun.value = snap
      steps.value = snap.steps ?? []
      status.value = snap.status
      reasonCode.value = snap.reason_code
      summary.value = snap.summary
    } catch {
      // 忽略后台刷新失败
    } finally {
      snapshotInFlight = false
      if (snapshotPending && activeRunId === id) {
        snapshotPending = false
        void refreshSnapshot()
      }
    }
  }

  function applyPayload(data: RunEventData) {
    if (data.type === 'log') {
      const p = data.payload as LogPayload
      if (typeof p?.text === 'string') {
        lines.value.push({
          seq: data.run_seq,
          text: p.text,
        })
        if (lines.value.length > MAX_MEMORY_LINES) {
          lines.value = lines.value.slice(lines.value.length - MAX_MEMORY_LINES)
        }
      }
    } else if (data.type === 'checkpoint') {
      scheduleSnapshotRefresh(0)
    } else if (data.type === 'state') {
      const p = data.payload as StatePayload
      if (p.status) {
        status.value = p.status
        if (currentRun.value) {
          currentRun.value.status = p.status
          if (
            p.status === 'succeeded' ||
            p.status === 'failed' ||
            p.status === 'cancelled' ||
            p.status === 'unknown'
          ) {
            if (!currentRun.value.finished_at) {
              currentRun.value.finished_at = new Date().toISOString()
            }
          }
        }
      }
      if (p.reason_code !== undefined) {
        reasonCode.value = p.reason_code
        if (currentRun.value) currentRun.value.reason_code = p.reason_code
      }
      if (p.summary) {
        summary.value = p.summary
        if (currentRun.value) currentRun.value.summary = p.summary
      }
      scheduleSnapshotRefresh(0)
    }
  }

  function processEvent(data: RunEventData) {
    if (data.run_id !== activeRunId) return
    const seq = data.run_seq

    // 已经处理过的持久 seq，忽略（去重）
    if (seq <= watermark.value) return

    // 恰好是期待的下一个连续 seq
    if (seq === watermark.value + 1) {
      applyPayload(data)
      watermark.value = seq

      // 排空 buffer 中连续后续 seq
      while (buffer.has(watermark.value + 1)) {
        const next = buffer.get(watermark.value + 1)!
        buffer.delete(watermark.value + 1)
        applyPayload(next)
        watermark.value = next.run_seq
      }
      return
    }

    // seq > watermark + 1：乱序到达，存入 buffer 并触发单飞补缺口
    buffer.set(seq, data)
    if (!loading.value) {
      void fetchGap(seq)
    }
  }

  // 单飞补齐：同时只有一个补齐循环在跑；若 has_more 为真则持续翻页直到追平水位
  let fetchingGap = false
  let gapTargetSeq = 0

  async function fetchGap(targetSeq?: number) {
    const id = activeRunId
    if (!id || !online.value) return
    if (targetSeq && targetSeq > gapTargetSeq) {
      gapTargetSeq = targetSeq
    }
    if (fetchingGap) return
    fetchingGap = true

    try {
      const client = api()
      if (!client) return

      let retryCount = 0
      const maxRetries = 3

      while (activeRunId === id && online.value) {
        // 排空已到位的连续缓冲区
        while (buffer.has(watermark.value + 1)) {
          const next = buffer.get(watermark.value + 1)!
          buffer.delete(watermark.value + 1)
          applyPayload(next)
          watermark.value = next.run_seq
        }

        // 清理已过期的旧 buffer 键
        for (const k of Array.from(buffer.keys())) {
          if (k <= watermark.value) buffer.delete(k)
        }

        const prevWatermark = watermark.value

        const res = await unwrap(
          client.GET('/api/runs/{run_id}/events', {
            params: { path: { run_id: id }, query: { after_seq: watermark.value, limit: 200 } },
          }),
        )
        if (activeRunId !== id || !online.value) break

        if (res.items && res.items.length > 0) {
          for (const item of res.items) {
            processEvent(item)
          }
        }

        while (buffer.has(watermark.value + 1)) {
          const next = buffer.get(watermark.value + 1)!
          buffer.delete(watermark.value + 1)
          applyPayload(next)
          watermark.value = next.run_seq
        }

        for (const k of Array.from(buffer.keys())) {
          if (k <= watermark.value) buffer.delete(k)
        }

        const remainingBufferMax = buffer.size > 0 ? Math.max(...buffer.keys()) : 0
        const stillHasGap = remainingBufferMax > watermark.value

        // 如果服务端表明还有更多数据，重置重试计数继续翻页
        if (res.has_more) {
          retryCount = 0
          continue
        }

        // 没有更多数据且缓冲区没有更高 seq（缺口已完全闭合），成功结束
        if (!stillHasGap && buffer.size === 0) {
          gapWarning.value = null
          gapTargetSeq = 0
          break
        }

        // has_more 为 false 但缓冲区仍有更高 seq（缺口未填平）
        if (watermark.value > prevWatermark) {
          // 本轮有新事件使水位推进，重置重试计数继续请求下一页
          retryCount = 0
          continue
        }

        // 水位未推进，进入有界重试
        retryCount++
        if (retryCount > maxRetries) {
          // 超过重试上限，停止循环并保留缓冲，提示用户
          gapWarning.value = '日志可能不完整，可刷新'
          break
        }

        // 短退避后再次尝试从当前水位请求
        await new Promise((resolve) => setTimeout(resolve, 50))
      }
    } catch {
      // 补齐失败由下一次事件重试
    } finally {
      fetchingGap = false
    }
  }

  async function syncRun(id: string) {
    activeRunId = id
    watermark.value = 0
    refreshAfterLoad = false
    buffer.clear()
    lines.value = []
    loading.value = true
    error.value = null
    gapWarning.value = null

    abortCtrl?.abort()
    const ctrl = new AbortController()
    abortCtrl = ctrl

    // 先订阅 WS：确保新产生的实时增量进入队列，避免在 GET 快照与订阅之间漏事件
    if (online.value) {
      runtime?.subscribeRun(id, 0)
    }

    try {
      const client = api()
      if (!client) throw new Error('API 客户端未就绪')

      // 获取当前快照（包含当前步骤、初始状态与 last_seq）
      const snapshot = await unwrap(
        client.GET('/api/runs/{run_id}', {
          signal: ctrl.signal,
          params: { path: { run_id: id } },
        }),
      )
      if (activeRunId !== id) return
      currentRun.value = snapshot
      steps.value = snapshot.steps ?? []
      status.value = snapshot.status
      reasonCode.value = snapshot.reason_code
      summary.value = snapshot.summary

      // 初次只拉取最近若干页（如最近 1000 条），避免全量 20MB 日志进内存
      const startAfterSeq = Math.max(0, (snapshot.last_seq ?? 0) - 1000)
      // 快照在途时 WS 回放可能已推进水位：水位只进不退，否则 HTTP 回放会重复追加日志
      if (watermark.value < startAfterSeq) watermark.value = startAfterSeq

      let cursor = watermark.value
      let hasMore = true
      while (hasMore) {
        const evs = await unwrap(
          client.GET('/api/runs/{run_id}/events', {
            signal: ctrl.signal,
            params: { path: { run_id: id }, query: { after_seq: cursor, limit: 500 } },
          }),
        )
        if (activeRunId !== id) return
        if (!evs?.items || evs.items.length === 0) break
        for (const item of evs.items) {
          processEvent(item)
        }
        hasMore = Boolean(evs.has_more)
        cursor = evs.next_seq
      }

      if (typeof snapshot.last_seq === 'number' && watermark.value < snapshot.last_seq) {
        watermark.value = snapshot.last_seq
        while (buffer.has(watermark.value + 1)) {
          const next = buffer.get(watermark.value + 1)!
          buffer.delete(watermark.value + 1)
          applyPayload(next)
          watermark.value = next.run_seq
        }
      }
    } catch (e: unknown) {
      if (activeRunId === id && !(e instanceof DOMException && e.name === 'AbortError')) {
        error.value = e instanceof Error ? e.message : '读取运行记录失败'
      }
    } finally {
      if (activeRunId === id) {
        loading.value = false
        if (refreshAfterLoad) {
          refreshAfterLoad = false
          scheduleSnapshotRefresh(0)
        }
        if (buffer.size > 0) {
          void fetchGap()
        }
      }
    }
  }

  function handleWsEnvelope(ev: EventEnvelope) {
    if (ev.topic !== 'run' || !activeRunId) return
    if (ev.type === 'run.event') {
      const data = ev.data as unknown as RunEventData
      if (data && data.run_id === activeRunId) {
        processEvent(data)
      }
    }
  }

  // 监听 WS 事件分发
  const unlisten = runtime?.onEvent(handleWsEnvelope)

  // 监听 runId 改变：切换时先退订旧 run，清空状态并开启新 run 同步
  watch(
    runIdRef,
    (newId, oldId) => {
      if (oldId) {
        runtime?.unsubscribeRun(oldId)
      }
      if (newId) {
        void syncRun(newId)
      } else {
        activeRunId = null
        abortCtrl?.abort()
        currentRun.value = null
        steps.value = []
        status.value = null
        lines.value = []
        watermark.value = 0
        buffer.clear()
      }
    },
    { immediate: true },
  )

  // 重新连接恢复时重新订阅并对齐
  watch(online, (isOnline) => {
    if (isOnline && activeRunId) {
      runtime?.subscribeRun(activeRunId, watermark.value)
      void fetchGap(watermark.value)
    }
  })

  // 页面卸载：清理监听器、abort 请求、退订 run，不取消后端任务
  onUnmounted(() => {
    unlisten?.()
    abortCtrl?.abort()
    if (snapshotTimer) clearTimeout(snapshotTimer)
    if (activeRunId) {
      runtime?.unsubscribeRun(activeRunId)
    }
  })

  return {
    lines: visibleLines,
    totalLineCount: computed(() => lines.value.length),
    currentRun,
    steps,
    status,
    reasonCode,
    summary,
    watermark,
    loading,
    error,
    gapWarning,
    refresh: () => {
      if (activeRunId) void syncRun(activeRunId)
    },
  }
}
