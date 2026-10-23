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

const taskSnapshot: components['schemas']['TaskSnapshot'] = {
  id: 'task-stream',
  name: '隔离任务',
  enabled: true,
  sort_order: 1,
  local_repo_path: '/tmp/repo',
  tg_command: '',
  tg_desc: '',
}

function run(runId: string, summary: string): RunResponse {
  return {
    run_id: runId,
    task_id: taskSnapshot.id,
    operation: 'sync_build_release',
    status: 'running',
    reason_code: null,
    summary,
    config_revision: 1,
    phase: 'git',
    recovery_state: 'none',
    created_at: '2026-10-23T09:00:00Z',
    started_at: '2026-10-23T09:00:01Z',
    finished_at: null,
    cancel_requested_at: null,
    deadline_at: '2026-10-23T09:30:00Z',
    log_bytes: 0,
    last_seq: 0,
    request_hash: 'hash',
    request_id: `request-${runId}`,
    state_version: 1,
    stop_reason: null,
    updated_at: '2026-10-23T09:00:01Z',
    task_snapshot: { ...taskSnapshot },
    steps: [],
    effects: [],
  }
}

function response<T>(data: T) {
  return { data, response: new Response() }
}

function logEvent(runId: string, runSeq: number, text: string): EventEnvelope {
  const data: RunEventData = { run_id: runId, run_seq: runSeq, type: 'log', payload: { text } }
  return {
    seq: runSeq,
    topic: 'run',
    type: 'run.event',
    ts: '2026-10-23T09:00:02Z',
    data: data as unknown as Record<string, unknown>,
  }
}

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('S3-C 独立运行隔离', () => {
  it('任务切换先退订旧 run；旧快照晚到和交错事件都不能覆盖或污染新 run', async () => {
    const runA = run('run-a', '旧任务快照')
    const runB = run('run-b', '新任务快照')
    let resolveA!: (value: ReturnType<typeof response<RunResponse>>) => void
    let eventHandler: ((event: EventEnvelope) => void) | undefined
    const operations: string[] = []
    const api = {
      GET: vi.fn((path: string, options?: { params?: { path?: { run_id?: string } } }) => {
        const id = options?.params?.path?.run_id
        operations.push(`GET ${id ?? path}`)
        if (path === '/api/runs/{run_id}' && id === 'run-a') {
          return new Promise((resolve) => {
            resolveA = resolve as (value: ReturnType<typeof response<RunResponse>>) => void
          })
        }
        if (path === '/api/runs/{run_id}' && id === 'run-b') {
          return Promise.resolve(response(runB))
        }
        if (path === '/api/runs/{run_id}/events') {
          return Promise.resolve(response({ items: [], next_seq: 0, has_more: false }))
        }
        throw new Error(`unexpected GET ${path}`)
      }),
    } as unknown as ApiClient
    const runtime: BackendRuntime = {
      api: () => api,
      start: () => undefined,
      stop: () => undefined,
      send: () => true,
      subscribeRun: (id, afterSeq) => {
        operations.push(`subscribe ${id} ${afterSeq}`)
        return true
      },
      unsubscribeRun: (id) => {
        operations.push(`unsubscribe ${id}`)
        return true
      },
      onEvent: (handler) => {
        eventHandler = handler
        return () => {
          eventHandler = undefined
        }
      },
    }
    const selectedRunId = ref<string | null>('run-a')
    const online = ref(true)
    const harness = defineComponent({
      setup() {
        const logs = useRunLogs(selectedRunId, runtime, online, () => api)
        return () =>
          h('div', { 'data-testid': 'stream-probe' }, [
            h('span', { 'data-testid': 'stream-status' }, logs.status.value ?? ''),
            h('span', { 'data-testid': 'stream-summary' }, logs.currentRun.value?.summary ?? ''),
            ...logs.lines.value.map((line) => h('p', { key: line.seq }, line.text)),
          ])
      },
    })
    const wrapper = mount(harness)
    await nextTick()

    expect(operations.slice(0, 2)).toEqual(['subscribe run-a 0', 'GET run-a'])
    selectedRunId.value = 'run-b'
    await flushPromises()
    await nextTick()
    expect(operations).toContain('unsubscribe run-a')
    expect(operations.indexOf('unsubscribe run-a')).toBeLessThan(
      operations.indexOf('subscribe run-b 0'),
    )

    eventHandler?.(logEvent('run-a', 1, '旧 run 日志'))
    eventHandler?.(logEvent('run-b', 1, '新 run 日志'))
    await flushPromises()
    expect(wrapper.get('[data-testid="stream-summary"]').text()).toBe('新任务快照')
    expect(wrapper.text()).toContain('新 run 日志')
    expect(wrapper.text()).not.toContain('旧 run 日志')

    resolveA(response(runA))
    await flushPromises()
    expect(wrapper.get('[data-testid="stream-summary"]').text()).toBe('新任务快照')
    wrapper.unmount()
    expect(operations).toContain('unsubscribe run-b')
    expect(api.GET).toHaveBeenCalledTimes(3)
  })
})
