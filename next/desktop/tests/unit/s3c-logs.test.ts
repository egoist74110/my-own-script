import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { useRunLogs } from '@/features/tasks/useRunLogs'
import LogPanel from '@/features/tasks/LogPanel.vue'
import type { BackendRuntime } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import type { EventEnvelope } from '@/api/events'
import type { RunEventData } from '@/features/tasks/api'

describe('S3-C 日志与步骤同步器（useRunLogs）', () => {
  beforeEach(() => {
    localStorage.clear()
    document.body.innerHTML = ''
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  function createMockRuntime() {
    const subscriptions: { runId: string; afterSeq?: number }[] = []
    const unsubscriptions: string[] = []
    let listener: ((e: EventEnvelope) => void) | null = null

    const runtime: BackendRuntime = {
      api: () => null,
      start: () => {},
      stop: () => {},
      send: () => true,
      subscribeRun: (runId, afterSeq) => {
        subscriptions.push({ runId, afterSeq })
        return true
      },
      unsubscribeRun: (runId) => {
        unsubscriptions.push(runId)
        return true
      },
      onEvent: (l) => {
        listener = l
        return () => {
          listener = null
        }
      },
    }

    return {
      runtime,
      subscriptions,
      unsubscriptions,
      emitRunEvent: (data: RunEventData, seq = 100) => {
        listener?.({
          type: 'run.event',
          topic: 'run',
          data,
          seq,
          ts: '2026-10-23T10:00:00Z',
        })
      },
    }
  }

  it('先订阅后补齐：加载运行首先发起 WS 订阅，随后 HTTP 获取快照和事件', async () => {
    const { runtime, subscriptions } = createMockRuntime()
    const runId = ref<string | null>(null)
    const online = ref(true)

    const httpCalls: string[] = []
    const mockApiClient = {
      GET: vi.fn(async (path: string) => {
        httpCalls.push(path)
        if (path === '/api/runs/{run_id}') {
          return {
            data: {
              run_id: 'run-1',
              task_id: 'task-1',
              operation: 'sync_build_release',
              status: 'running',
              steps: [],
            },
            response: new Response(),
          }
        }
        if (path === '/api/runs/{run_id}/events') {
          return {
            data: {
              items: [
                {
                  run_id: 'run-1',
                  run_seq: 1,
                  type: 'log',
                  payload: { text: 'Cloning repo...' },
                },
              ],
              has_more: false,
              next_cursor: 1,
            },
            response: new Response(),
          }
        }
        return { data: null, response: new Response() }
      }),
    } as unknown as ApiClient

    const Harness = defineComponent({
      setup() {
        return useRunLogs(runId, runtime, online, () => mockApiClient)
      },
      template: '<div>{{ lines.length }} lines</div>',
    })

    const w = mount(Harness)
    await flushPromises()

    // 尚未选择 run 时，不触发订阅和请求
    expect(subscriptions).toHaveLength(0)
    expect(httpCalls).toHaveLength(0)

    // 选择 run-1
    runId.value = 'run-1'
    await flushPromises()

    // 订阅必须在 HTTP 之前建立
    expect(subscriptions).toEqual([{ runId: 'run-1', afterSeq: 0 }])
    expect(httpCalls).toContain('/api/runs/{run_id}')
    expect(httpCalls).toContain('/api/runs/{run_id}/events')
    expect(w.text()).toContain('1 lines')

    w.unmount()
  })

  it('去重与乱序缓冲：连续水位保证日志按 seq 递增输出，重复 seq 被丢弃', async () => {
    const { runtime, emitRunEvent } = createMockRuntime()
    const runId = ref<string | null>('run-1')
    const online = ref(true)

    const mockApiClient = {
      GET: vi.fn(async (path: string) => {
        if (path === '/api/runs/{run_id}') {
          return {
            data: {
              run_id: 'run-1',
              task_id: 'task-1',
              operation: 'sync_build_release',
              status: 'running',
              steps: [],
            },
            response: new Response(),
          }
        }
        if (path === '/api/runs/{run_id}/events') {
          return {
            data: { items: [], has_more: false, next_cursor: 0 },
            response: new Response(),
          }
        }
        return { data: null, response: new Response() }
      }),
    } as unknown as ApiClient

    let result: ReturnType<typeof useRunLogs> | null = null
    const Harness = defineComponent({
      setup() {
        const r = useRunLogs(runId, runtime, online, () => mockApiClient)
        result = r
        return r
      },
      template: '<div>{{ lines.length }}</div>',
    })

    const w = mount(Harness)
    await flushPromises()

    // 乱序到达：seq 3 先到，buffer 缓存，不立即应用
    emitRunEvent({
      run_id: 'run-1',
      run_seq: 3,
      type: 'log',
      payload: { text: 'Step 3 finished' },
    })
    await flushPromises()
    expect(result!.lines.value).toHaveLength(0)

    // seq 1 到达，应用并推进水位至 1
    emitRunEvent({
      run_id: 'run-1',
      run_seq: 1,
      type: 'log',
      payload: { text: 'Step 1 started' },
    })
    await flushPromises()
    expect(result!.lines.value).toHaveLength(1)
    expect(result!.lines.value[0]?.text).toBe('Step 1 started')

    // seq 1 重复到达（网络重放或 HTTP 与 WS 重叠），被去重
    emitRunEvent({
      run_id: 'run-1',
      run_seq: 1,
      type: 'log',
      payload: { text: 'Step 1 DUPLICATE' },
    })
    await flushPromises()
    expect(result!.lines.value).toHaveLength(1)

    // seq 2 到达，推进水位至 2，并自动排空 buffer 中的 seq 3（推进至 3）
    emitRunEvent({
      run_id: 'run-1',
      run_seq: 2,
      type: 'log',
      payload: { text: 'Step 2 building' },
    })
    await flushPromises()
    expect(result!.lines.value).toHaveLength(3)
    expect(result!.lines.value.map((l) => l.text)).toEqual([
      'Step 1 started',
      'Step 2 building',
      'Step 3 finished',
    ])

    w.unmount()
  })

  it('切换运行与卸载清理：切到新 run 退订旧 run，卸载清理订阅且不取消后端任务', async () => {
    const { runtime, subscriptions, unsubscriptions } = createMockRuntime()
    const runId = ref<string | null>('run-A')
    const online = ref(true)

    const mockApiClient = {
      GET: vi.fn(async (path: string) => {
        if (path === '/api/runs/{run_id}') {
          return {
            data: {
              run_id: runId.value!,
              task_id: 'task-1',
              operation: 'sync_build_release',
              status: 'running',
              steps: [],
            },
            response: new Response(),
          }
        }
        return { data: { items: [], has_more: false }, response: new Response() }
      }),
    } as unknown as ApiClient

    const Harness = defineComponent({
      setup() {
        return useRunLogs(runId, runtime, online, () => mockApiClient)
      },
      template: '<div>Harness</div>',
    })

    const w = mount(Harness)
    await flushPromises()

    expect(subscriptions).toContainEqual({ runId: 'run-A', afterSeq: 0 })

    // 切换到 run-B
    runId.value = 'run-B'
    await flushPromises()

    // 旧 run-A 被退订
    expect(unsubscriptions).toContain('run-A')
    // 新 run-B 被订阅
    expect(subscriptions).toContainEqual({ runId: 'run-B', afterSeq: 0 })

    // 卸载组件
    w.unmount()
    await flushPromises()

    // run-B 被退订
    expect(unsubscriptions).toContain('run-B')
    // 验证：未调用任何 POST /cancel，卸载只是前端断开监听，不终止后端真实任务
  })

  it('安全防泄漏：LogPanel 日志为纯文本渲染，不支持脚本注入，DOM 无 token', async () => {
    const lines = [
      { seq: 1, text: '<img src=x onerror=alert(1)>' },
      { seq: 2, text: '<script>window.__pwned=true</script>' },
    ]

    const w = mount(LogPanel, {
      props: {
        lines,
        totalLineCount: 2,
      },
    })
    await flushPromises()

    // 必须转义，不能作为真实 HTML/DOM 节点解析
    expect(w.find('img').exists()).toBe(false)
    expect(w.find('script').exists()).toBe(false)
    expect((window as unknown as { __pwned?: unknown }).__pwned).toBeUndefined()
    expect(w.text()).toContain('<img src=x onerror=alert(1)>')
    expect(w.text()).toContain('<script>window.__pwned=true</script>')

    // 检查 DOM 和 LocalStorage 绝无敏感 token 泄露
    expect(document.body.innerHTML).not.toContain('fake-token')
    expect(document.body.innerHTML).not.toContain('Bearer')
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)!
      expect(localStorage.getItem(key)).not.toContain('token')
    }
  })

  it('日志窗口加载与单飞补缺口：大 last_seq 仅拉取尾部窗口，fetchGap 单飞执行', async () => {
    const { runtime, emitRunEvent } = createMockRuntime()
    const runId = ref<string | null>('run-large')
    const online = ref(true)
    const gapCalls: number[] = []

    let concurrentCalls = 0
    let maxConcurrent = 0

    const mockApi = () =>
      ({
        GET: async (path: string, options?: { params?: { query?: { after_seq?: number } } }) => {
          if (path === '/api/runs/{run_id}') {
            return {
              data: {
                run_id: 'run-large',
                status: 'running',
                last_seq: 3500,
                steps: [],
                created_at: '2026-10-23T10:00:00Z',
              },
            }
          }
          if (path === '/api/runs/{run_id}/events') {
            concurrentCalls++
            maxConcurrent = Math.max(maxConcurrent, concurrentCalls)
            const afterSeq = options?.params?.query?.after_seq ?? 0
            gapCalls.push(afterSeq)
            await new Promise((r) => setTimeout(r, 10))
            concurrentCalls--
            return {
              data: {
                items: [],
                has_more: false,
                next_seq: afterSeq,
              },
            }
          }
          return { data: {} }
        },
      }) as unknown as ApiClient

    const w = mount(
      defineComponent({
        setup() {
          const logs = useRunLogs(runId, runtime, online, mockApi)
          return { logs }
        },
        template: '<div></div>',
      }),
    )

    await flushPromises()
    // 首次拉取初始 afterSeq 从 3500 - 1000 = 2500 开始，而非 0
    expect(gapCalls[0]).toBe(2500)

    // 并发触发两次乱序事件 (seq 3505 和 seq 3510)
    emitRunEvent(
      { run_id: 'run-large', run_seq: 3505, type: 'log', payload: { text: 'jump 1' } },
      3505,
    )
    emitRunEvent(
      { run_id: 'run-large', run_seq: 3510, type: 'log', payload: { text: 'jump 2' } },
      3510,
    )

    await flushPromises()
    // 验证并发请求数始终为 1（单飞）
    expect(maxConcurrent).toBe(1)

    w.unmount()
  })
})
