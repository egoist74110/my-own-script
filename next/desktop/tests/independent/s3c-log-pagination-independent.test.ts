import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import type { components } from '@/api/schema'
import type { EventEnvelope } from '@/api/events'
import type { ApiClient } from '@/api/client'
import type { BackendRuntime } from '@/app/backend-runtime'
import { useRunLogs } from '@/features/tasks/useRunLogs'

type RunResponse = components['schemas']['RunResponse']
type RunEventData = components['schemas']['RunEventData']
const snapshot: RunResponse = {
  run_id: 'run-pages',
  task_id: 'task-pages',
  operation: 'sync_build_release',
  status: 'running',
  reason_code: null,
  summary: '快照摘要',
  config_revision: 1,
  phase: 'build',
  recovery_state: 'none',
  created_at: '2026-10-23T09:00:00Z',
  started_at: '2026-10-23T09:00:01Z',
  finished_at: null,
  cancel_requested_at: null,
  deadline_at: '2026-10-23T09:30:00Z',
  log_bytes: 0,
  last_seq: 2,
  request_hash: 'hash',
  request_id: 'request-pages',
  state_version: 1,
  stop_reason: null,
  updated_at: '2026-10-23T09:00:01Z',
  task_snapshot: {
    id: 'task-pages',
    name: '分页任务',
    enabled: true,
    sort_order: 1,
    local_repo_path: '/tmp/pages',
    tg_command: '',
    tg_desc: '',
  },
  steps: [],
  effects: [],
}
const ev = (seq: number, text: string): RunEventData => ({
  run_id: 'run-pages',
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

beforeEach(() => {
  document.body.innerHTML = ''
})
afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('S3-C 独立日志连续性', () => {
  it('回放与实时交界去重；乱序事件单飞补缺口并翻完 has_more，重连从连续水位订阅与补齐', async () => {
    const calls: Array<{ after?: number; limit?: number }> = []
    const ops: string[] = []
    let handler: ((e: EventEnvelope) => void) | undefined
    const online = ref(true)
    const api = {
      GET: vi.fn(
        (
          path: string,
          options?: {
            params?: { path?: { run_id?: string }; query?: { after_seq?: number; limit?: number } }
          },
        ) => {
          if (path === '/api/runs/{run_id}') return Promise.resolve(result(snapshot))
          const after = options?.params?.query?.after_seq
          calls.push({ after, limit: options?.params?.query?.limit })
          if (after === 0)
            return Promise.resolve(
              result({ items: [ev(1, '回放一')], next_seq: 1, has_more: true }),
            )
          if (after === 1)
            return Promise.resolve(
              result({ items: [ev(2, '回放二')], next_seq: 2, has_more: false }),
            )
          if (after === 2)
            return Promise.resolve(
              result({ items: [ev(3, '实时三')], next_seq: 3, has_more: true }),
            )
          if (after === 3)
            return Promise.resolve(
              result({ items: [ev(4, '实时四')], next_seq: 4, has_more: true }),
            )
          if (after === 4)
            return Promise.resolve(
              result({ items: [ev(5, '实时五')], next_seq: 5, has_more: true }),
            )
          if (after === 5)
            return Promise.resolve(
              result({ items: [ev(6, '实时六')], next_seq: 6, has_more: false }),
            )
          if (after === 6)
            return Promise.resolve(
              result({ items: [ev(7, '实时七')], next_seq: 7, has_more: false }),
            )
          if (after === 8)
            return Promise.resolve(
              result({ items: [ev(9, '重连九')], next_seq: 9, has_more: false }),
            )
          throw new Error(`unexpected after_seq=${after}`)
        },
      ),
      POST: vi.fn(),
    } as unknown as ApiClient
    const runtime: BackendRuntime = {
      api: () => api,
      start: () => undefined,
      stop: () => undefined,
      send: () => true,
      subscribeRun: (id, n) => {
        ops.push(`sub:${id}:${n}`)
        return true
      },
      unsubscribeRun: (id) => {
        ops.push(`unsub:${id}`)
        return true
      },
      onEvent: (cb) => {
        handler = cb
        return () => {
          handler = undefined
        }
      },
    }
    const id = ref<string | null>('run-pages')
    const Harness = defineComponent({
      setup() {
        const stream = useRunLogs(id, runtime, online, () => api)
        return () =>
          h(
            'div',
            stream.lines.value.map((line) => h('p', { key: line.seq }, `${line.seq}:${line.text}`)),
          )
      },
    })
    const wrapper = mount(Harness)
    for (let i = 0; i < 6; i++) {
      await flushPromises()
      await nextTick()
    }
    expect(ops[0]).toBe('sub:run-pages:0')
    expect(calls.slice(0, 2).map((c) => c.after)).toEqual([0, 1])
    expect(wrapper.text()).toContain('1:回放一')
    expect(wrapper.text()).toContain('2:回放二')

    // 服务回放含 seq2 后，WS 重复 seq2 不得再画一行；先到 seq4 后 seq3 由补齐填洞。
    handler?.(ws(ev(2, '重复二')))
    handler?.(ws(ev(8, '实时八')))
    handler?.(ws(ev(3, '实时三')))
    handler?.(ws(ev(8, '实时八')))
    for (let i = 0; i < 8; i++) {
      await flushPromises()
      await nextTick()
    }
    expect(calls.filter((c) => c.after === 2)).toHaveLength(1)
    expect(calls.map((c) => c.after)).toEqual([0, 1, 2, 3, 4, 5, 6])
    expect(wrapper.text()).toContain('3:实时三')
    expect(wrapper.text()).toContain('4:实时四')
    expect(wrapper.text()).toContain('5:实时五')
    expect(wrapper.text()).toContain('6:实时六')
    expect(wrapper.text()).toContain('7:实时七')
    expect(wrapper.text()).toContain('8:实时八')
    expect(wrapper.text().match(/8:实时八/g)).toHaveLength(1)
    expect(calls.filter((c) => [2, 3, 4, 5, 6, 7].includes(c.after ?? -1))).toHaveLength(5)

    online.value = false
    await nextTick()
    online.value = true
    await flushPromises()
    await nextTick()
    expect(ops).toContain('sub:run-pages:8')
    expect(calls.at(-1)?.after).toBe(8)
    expect(wrapper.text()).toContain('9:重连九')
    wrapper.unmount()
    expect(ops).toContain('unsub:run-pages')
    expect(api.POST).not.toHaveBeenCalled()
  })
})
