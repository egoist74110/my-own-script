import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { useRunLogs } from '@/features/tasks/useRunLogs'
import type { BackendRuntime } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import type { EventEnvelope } from '@/api/events'
import type { RunEventData, RunResponse } from '@/features/tasks/api'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

const snapshot: RunResponse = {
  run_id: 'run-test-gap',
  task_id: 'task-1',
  operation: 'sync_build_release',
  status: 'running',
  reason_code: null,
  summary: '',
  config_revision: 1,
  phase: 'build',
  recovery_state: 'none',
  created_at: '2026-10-23T09:00:00Z',
  started_at: '2026-10-23T09:00:01Z',
  finished_at: null,
  cancel_requested_at: null,
  stop_reason: null,
  deadline_at: '2026-10-23T09:30:00Z',
  log_bytes: 0,
  last_seq: 2,
  request_hash: 'h',
  request_id: 'r',
  state_version: 1,
  task_snapshot: {} as unknown as RunResponse['task_snapshot'],
  updated_at: '2026-10-23T09:00:01Z',
  steps: [],
  effects: [],
}

const ev = (seq: number, text: string): RunEventData => ({
  run_id: 'run-test-gap',
  run_seq: seq,
  type: 'log',
  payload: { text },
})

const ws = (data: RunEventData): EventEnvelope => ({
  seq: data.run_seq,
  topic: 'run',
  type: 'run.event',
  ts: '2026-10-23T09:00:02Z',
  data: data as unknown as Record<string, unknown>,
})

const result = <T>(data: T) => ({ data, response: new Response() })

describe('S3-C 第五轮修复验证（TDD 失败断言）', () => {
  it('1. 当 has_more 为 false 且缓冲区有更高未连续 seq 时，持续翻页请求直到填平缺口', async () => {
    const calls: number[] = []
    let handler: ((e: EventEnvelope) => void) | undefined
    const online = ref(true)

    const api = {
      GET: vi.fn((path: string, options?: { params?: { query?: { after_seq?: number } } }) => {
        if (path === '/api/runs/{run_id}') return Promise.resolve(result(snapshot))
        const after = options?.params?.query?.after_seq ?? 0
        calls.push(after)
        if (after === 0) {
          return Promise.resolve(result({ items: [ev(1, '第1行')], next_seq: 1, has_more: true }))
        }
        if (after === 1) {
          return Promise.resolve(result({ items: [ev(2, '第2行')], next_seq: 2, has_more: false }))
        }
        if (after === 2) {
          // 补齐 3，但 has_more 标为 false，next_seq 为 3
          return Promise.resolve(result({ items: [ev(3, '第3行')], next_seq: 3, has_more: false }))
        }
        if (after === 3) {
          // 补齐 4
          return Promise.resolve(result({ items: [ev(4, '第4行')], next_seq: 4, has_more: false }))
        }
        return Promise.resolve(result({ items: [], next_seq: after, has_more: false }))
      }),
      POST: vi.fn(),
    } as unknown as ApiClient

    const runtime: BackendRuntime = {
      api: () => api,
      start: () => undefined,
      stop: () => undefined,
      send: () => true,
      subscribeRun: () => true,
      unsubscribeRun: () => true,
      onEvent: (cb) => {
        handler = cb
        return () => {
          handler = undefined
        }
      },
    }

    const id = ref<string | null>('run-test-gap')
    let streamRef: ReturnType<typeof useRunLogs> | undefined
    const Harness = defineComponent({
      setup() {
        const stream = useRunLogs(id, runtime, online, () => api)
        streamRef = stream
        return () =>
          h(
            'div',
            stream.lines.value.map((l) => h('p', { key: l.seq }, l.text)),
          )
      },
    })

    const w = mount(Harness)
    for (let i = 0; i < 4; i++) {
      await flushPromises()
      await nextTick()
    }

    expect(calls).toEqual([0, 1])

    // WS 推送乱序 seq 5（缺失 3 和 4）
    handler?.(ws(ev(5, '第5行')))

    for (let i = 0; i < 6; i++) {
      await flushPromises()
      await nextTick()
    }

    // 应该依次调用 after_seq: 2, 3，成功将缺口连续到 5
    expect(calls).toEqual([0, 1, 2, 3])
    expect(w.text()).toContain('第3行')
    expect(w.text()).toContain('第4行')
    expect(w.text()).toContain('第5行')
    expect(streamRef?.gapWarning.value).toBeNull()
    w.unmount()
  })

  it('2. 当服务端无法返回缺失事件时，最多有界重试 3 次后停止循环并给出“日志可能不完整，可刷新”提示', async () => {
    const calls: number[] = []
    let handler: ((e: EventEnvelope) => void) | undefined
    const online = ref(true)

    const api = {
      GET: vi.fn((path: string, options?: { params?: { query?: { after_seq?: number } } }) => {
        if (path === '/api/runs/{run_id}') return Promise.resolve(result(snapshot))
        const after = options?.params?.query?.after_seq ?? 0
        calls.push(after)
        if (after === 0) {
          return Promise.resolve(result({ items: [ev(1, '第1行')], next_seq: 1, has_more: true }))
        }
        if (after === 1) {
          return Promise.resolve(result({ items: [ev(2, '第2行')], next_seq: 2, has_more: false }))
        }
        // after === 2 时，服务端始终返回空数组且 has_more: false（确实无法提供 3）
        return Promise.resolve(result({ items: [], next_seq: 2, has_more: false }))
      }),
      POST: vi.fn(),
    } as unknown as ApiClient

    const runtime: BackendRuntime = {
      api: () => api,
      start: () => undefined,
      stop: () => undefined,
      send: () => true,
      subscribeRun: () => true,
      unsubscribeRun: () => true,
      onEvent: (cb) => {
        handler = cb
        return () => {
          handler = undefined
        }
      },
    }

    const id = ref<string | null>('run-test-gap')
    let streamRef: ReturnType<typeof useRunLogs> | undefined
    const Harness = defineComponent({
      setup() {
        const stream = useRunLogs(id, runtime, online, () => api)
        streamRef = stream
        return () =>
          h(
            'div',
            stream.lines.value.map((l) => h('p', { key: l.seq }, l.text)),
          )
      },
    })

    const w = mount(Harness)
    for (let i = 0; i < 4; i++) {
      await flushPromises()
      await nextTick()
    }

    expect(calls).toEqual([0, 1])

    // WS 推送乱序 seq 5（由于服务端只有 up to 2，缺失 3,4）
    handler?.(ws(ev(5, '第5行')))

    // 等待重试完成（有界重试 3 次）
    for (let i = 0; i < 15; i++) {
      await flushPromises()
      await nextTick()
      await new Promise((r) => setTimeout(r, 60))
    }

    // 初始 1 次请求 + 最多 3 次重试 = 4 次 after=2 请求
    const after2Calls = calls.filter((c) => c === 2)
    expect(after2Calls.length).toBeGreaterThanOrEqual(1)
    expect(after2Calls.length).toBeLessThanOrEqual(4)

    // 应该给出警告提示
    expect(streamRef?.gapWarning.value).toBe('日志可能不完整，可刷新')
    w.unmount()
  })
})
