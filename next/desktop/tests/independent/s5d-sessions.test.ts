// S5-D 独立测试（测试员）：新建会话 Sheet 与会话列表页的故障、幂等与错误文案。
// 后端以假 client 替身，WS 与 xterm 为替身；不连接真实后端或 CLI。
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'
import NewSessionSheet from '@/features/ai/NewSessionSheet.vue'
import AiSessionsPage from '@/features/ai/AiSessionsPage.vue'
import type { EventEnvelope } from '@/api/events'
import { inspectorHostKey } from '@/app/inspector'

vi.mock('vue-router', async (orig) => ({
  ...(await orig<typeof import('vue-router')>()),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    rows = 24
    cols = 80
    options: Record<string, unknown> = {}
    loadAddon() {}
    open() {}
    write() {}
    reset() {}
    onData() {
      return { dispose() {} }
    }
    dispose() {}
  },
}))
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit() {}
  },
}))
vi.mock('@xterm/xterm/css/xterm.css', () => ({}))

class SilentWS {
  static OPEN = 1
  readyState = 0
  onopen = null
  onmessage = null
  onclose = null
  onerror = null
  binaryType = ''
  send() {}
  close() {}
  constructor(readonly url: string) {}
}

const profiles = [
  {
    id: 'claude_code',
    name: 'Claude Code',
    cli: 'claude',
    command: 'claude',
    builtin: true,
    upgrade_command: '',
    resolved: { ok: true },
  },
  {
    id: 'codex',
    name: 'Codex',
    cli: 'codex',
    command: 'codex',
    builtin: true,
    upgrade_command: '',
    resolved: { ok: true },
  },
]
const repos = [{ id: 'repo_1', name: 'web-portal' }]

function sessionFixture(over: Record<string, unknown> = {}) {
  return {
    id: 'ais_0000000000000001',
    kind: 'terminal',
    cli: 'claude',
    profile: { id: 'claude_code', name: 'Claude Code' },
    repo: { id: 'repo_1', name: 'web-portal' },
    state: 'busy',
    created_at: '2026-10-23T10:00:00Z',
    last_seq: 3,
    ended_at: null,
    ended_reason: null,
    exit_code: null,
    warnings: [],
    origin: { kind: 'ui' },
    pending_approval: false,
    queue_len: 0,
    has_external_id: false,
    ...over,
  }
}

function okResp(data: unknown) {
  return { data, response: { status: 200 } }
}
function errResp(status: number, body: unknown) {
  return { error: body, response: { status } }
}

afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

beforeEach(() => {
  vi.stubGlobal('WebSocket', SilentWS)
  setActivePinia(createPinia())
})

function sheetRuntime(post: ReturnType<typeof vi.fn>) {
  return {
    api: () => ({ POST: post, GET: vi.fn() }),
    getConnection: () => ({ port: 5555, token: 'FAKE-TOKEN-sheet' }),
    start() {},
    stop() {},
    send: () => false,
    subscribeRun: () => false,
    unsubscribeRun: () => false,
    onEvent: () => () => {},
  }
}

async function mountSheet(post: ReturnType<typeof vi.fn>) {
  // 先以关闭状态挂载，再打开，才会触发 open 的默认值填充（与页面真实行为一致）
  const w = mount(NewSessionSheet, {
    props: { open: false, profiles, localRepos: repos },
    global: { provide: { [backendRuntimeKey as symbol]: sheetRuntime(post) } },
    attachTo: document.body,
  })
  await w.setProps({ open: true })
  await flushPromises()
  return w
}

describe('S5-D 独立：新建会话 Sheet 的提交幂等与输入形态', () => {
  it('快速重复提交只发出一次请求，且 request_id 为 UUID', async () => {
    let resolve!: (v: unknown) => void
    const post = vi.fn(() => new Promise((r) => (resolve = r)))
    await mountSheet(post)
    const form = document.querySelector<HTMLFormElement>('form[data-testid="new-session-form"]')!
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    expect(post).toHaveBeenCalledTimes(1)
    const body = (post.mock.calls[0] as unknown[])[1] as { body: Record<string, unknown> }
    expect(String(body.body.request_id)).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    )
    resolve(okResp(sessionFixture()))
    await flushPromises()
  })

  it('失败后再次提交复用同一 request_id（幂等键在同一次打开内保持不变）', async () => {
    const post = vi
      .fn()
      .mockResolvedValueOnce(errResp(409, { detail: { code: 'ai_session_limit' } }))
      .mockResolvedValueOnce(okResp(sessionFixture()))
    await mountSheet(post)
    const form = document.querySelector<HTMLFormElement>('form[data-testid="new-session-form"]')!
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    expect(post).toHaveBeenCalledTimes(2)
    const ids = post.mock.calls.map(
      (c) => (c[1] as { body: { request_id: string } }).body.request_id,
    )
    expect(ids[0]).toBe(ids[1])
  })

  it('没有任何路径输入框：工作目录只能从已配置仓库下拉选择', async () => {
    await mountSheet(vi.fn())
    const textInputs = document.querySelectorAll(
      'input[type="text"], input:not([type]), input[type="url"]',
    )
    expect(textInputs.length).toBe(0)
    expect(document.querySelector('[data-testid="repo-select"]')).not.toBeNull()
    expect(document.body.innerHTML).not.toMatch(/路径|path/i)
  })

  it('没有已配置仓库时不提供提交按钮可用的状态（不能回落到手输路径）', async () => {
    const post = vi.fn()
    const w = mount(NewSessionSheet, {
      props: { open: false, profiles, localRepos: [] },
      global: { provide: { [backendRuntimeKey as symbol]: sheetRuntime(post) } },
      attachTo: document.body,
    })
    await w.setProps({ open: true })
    await flushPromises()
    const btn = document.querySelector('[data-testid="confirm-create-btn"]') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(document.querySelector('[data-testid="jump-to-repos-btn"]')).not.toBeNull()
  })
})

describe('S5-D 独立：新建会话错误码文案', () => {
  const cases: Array<[string, number, string]> = [
    ['ai_session_limit', 409, '活动终端会话已达上限'],
    ['cli_not_found', 409, '未找到对应的 AI CLI 可执行文件'],
    ['repo_missing', 409, '本地仓库不存在或已被删除'],
    ['unsupported_cli', 409, '该 CLI 不支持当前类型的会话'],
    ['ai_store_unavailable', 503, 'AI 存储不可用'],
  ]
  for (const [code, status, zh] of cases) {
    it(`${status} ${code} 显示中文文案，且不回显服务端原始 message`, async () => {
      const RAW = `RAW_SERVER_ECHO_${code}_/Users/secret/home`
      const post = vi.fn().mockResolvedValue(errResp(status, { detail: { code, message: RAW } }))
      await mountSheet(post)
      document
        .querySelector<HTMLFormElement>('[data-testid="new-session-form"]')!
        .dispatchEvent(new Event('submit', { cancelable: true }))
      await flushPromises()
      const banner = document.querySelector('[data-testid="session-error-banner"]')
      expect(banner?.textContent ?? '').toContain(zh)
      expect(banner?.textContent ?? '').not.toContain(RAW)
      expect(document.body.innerHTML).not.toContain('/Users/secret')
    })
  }

  it('high_risk_ack_required：显示中文文案并展开高权限确认框', async () => {
    const post = vi
      .fn()
      .mockResolvedValue(
        errResp(409, { detail: { code: 'high_risk_ack_required', message: 'RAW_HR' } }),
      )
    await mountSheet(post)
    document
      .querySelector<HTMLFormElement>('[data-testid="new-session-form"]')!
      .dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    const banner = document.querySelector('[data-testid="session-error-banner"]')
    expect(banner?.textContent ?? '').toContain('高权限档位需要二次确认')
    expect(banner?.textContent ?? '').not.toContain('RAW_HR')
    expect(document.querySelector('[data-testid="high-risk-box"]')).not.toBeNull()
  })

  it('422 校验错误（pydantic 数组 detail，内含用户输入回显）不回显任何原文', async () => {
    const ECHO = 'ECHO_INPUT_VALUE_777'
    const post = vi.fn().mockResolvedValue(
      errResp(422, {
        detail: [{ loc: ['body', 'repo_id'], msg: 'string too long', input: ECHO }],
      }),
    )
    await mountSheet(post)
    document
      .querySelector<HTMLFormElement>('[data-testid="new-session-form"]')!
      .dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    const text = document.querySelector('[data-testid="session-error-banner"]')?.textContent ?? ''
    expect(text).not.toContain(ECHO)
    expect(text).not.toContain('string too long')
    expect(text.length).toBeGreaterThan(0)
  })

  it('503 且 detail 为字符串时不得把服务端原文直接显示给用户', async () => {
    const RAW = 'RAW_DB_PATH /Users/wesker/.local/ai.sqlite3 corrupt'
    const post = vi.fn().mockResolvedValue(errResp(503, { detail: RAW }))
    await mountSheet(post)
    document
      .querySelector<HTMLFormElement>('[data-testid="new-session-form"]')!
      .dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    const text = document.querySelector('[data-testid="session-error-banner"]')?.textContent ?? ''
    expect(text).not.toContain(RAW)
    expect(text).not.toContain('sqlite3')
  })
})

describe('S5-D 独立：会话列表页的数据来源与事件一致性', () => {
  function pageRuntime(listeners: Array<(e: EventEnvelope) => void>) {
    return {
      api: () => client,
      getConnection: () => ({ port: 5555, token: 'FAKE-TOKEN-page' }),
      start() {},
      stop() {},
      send: () => false,
      subscribeRun: () => false,
      unsubscribeRun: () => false,
      subscribeAi: () => true,
      unsubscribeAi: () => true,
      onEvent: (l: (e: EventEnvelope) => void) => {
        listeners.push(l)
        return () => {}
      },
    }
  }
  let client: { GET: ReturnType<typeof vi.fn>; POST: ReturnType<typeof vi.fn> }

  function emit(listeners: Array<(e: EventEnvelope) => void>, type: string, data: object) {
    for (const l of listeners) {
      l({ seq: 1, topic: 'ai', type, ts: '2026-10-23T10:00:00Z', data } as unknown as EventEnvelope)
    }
  }

  async function mountPage(
    sessionsResponder: () => Promise<unknown>,
  ): Promise<{ qc: QueryClient; listeners: Array<(e: EventEnvelope) => void> }> {
    const listeners: Array<(e: EventEnvelope) => void> = []
    client = {
      GET: vi.fn((path: string) => {
        if (path === '/api/ai/sessions') return sessionsResponder()
        if (path === '/api/ai') {
          return Promise.resolve(
            okResp({
              revision: 1,
              profiles,
              selected_profile_id: 'claude_code',
              defaults: {},
              analysis: {},
              model_presets: {},
              store_state: 'ready',
              warnings: [],
              limits: {},
            }),
          )
        }
        if (path === '/api/ado') return Promise.resolve(okResp({ local_repos: repos }))
        return Promise.resolve(okResp({}))
      }),
      POST: vi.fn(),
    }
    useBackendStore().setConnection('online')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    // 检查器通过 Teleport 进入 App 壳提供的宿主节点，测试中以一个等价的 div 充当宿主
    const host = document.createElement('div')
    host.id = 'inspector-host'
    document.body.appendChild(host)
    mount(AiSessionsPage, {
      global: {
        plugins: [[VueQueryPlugin, { queryClient: qc }]],
        provide: {
          [backendRuntimeKey as symbol]: pageRuntime(listeners),
          [inspectorHostKey as symbol]: ref(host),
        },
      },
      attachTo: document.body,
    })
    await flushPromises()
    return { qc, listeners }
  }

  const rowText = (id: string) =>
    document.querySelector(`[data-testid="session-${id}"]`)?.textContent ?? ''

  it('会话列表 GET 失败（如 503 ai_store_unavailable）时不得显示 mock 假会话冒充真实数据', async () => {
    await mountPage(() =>
      Promise.resolve(errResp(503, { detail: { code: 'ai_store_unavailable', message: 'x' } })),
    )
    const html = document.body.innerHTML
    expect(html).not.toContain('权限缓存未刷新')
    expect(html).not.toContain('web-portal (终端)')
  })

  it('ai.session 事件晚于在途 GET 返回时，旧 GET 结果不回滚状态', async () => {
    let resolveGet!: (v: unknown) => void
    const pending = new Promise((r) => (resolveGet = r))
    const { listeners } = await mountPage(() => pending)
    emit(listeners, 'ai.session', {
      session_id: 'ais_0000000000000001',
      state: 'ended',
      ended_reason: 'process_exited',
      last_seq: 9,
    })
    await flushPromises()
    resolveGet(okResp({ items: [sessionFixture({ state: 'busy', last_seq: 3 })] }))
    await flushPromises()
    expect(rowText('ais_0000000000000001')).toContain('已结束')
  })

  it('后到的、更新的 GET 快照应覆盖较早的 ai.session 事件（事件丢失后的补齐）', async () => {
    let calls = 0
    const { listeners, qc } = await mountPage(() => {
      calls++
      return Promise.resolve(
        okResp({
          items: [
            calls === 1
              ? sessionFixture({ state: 'busy', last_seq: 3 })
              : sessionFixture({ state: 'ended', ended_reason: 'process_exited', last_seq: 8 }),
          ],
        }),
      )
    })
    expect(rowText('ais_0000000000000001')).toContain('运行中')
    emit(listeners, 'ai.session', {
      session_id: 'ais_0000000000000001',
      state: 'busy',
      last_seq: 4,
    })
    await flushPromises()
    // 断线期间会话已结束、事件丢失；随后的刷新拿到更新快照
    await qc.invalidateQueries({ queryKey: ['ai', 'sessions'] })
    await flushPromises()
    expect(rowText('ais_0000000000000001')).toContain('已结束')
  })

  it('对照组：无事件时刷新拿到的新快照被正确显示（验证本页夹具与刷新路径可用）', async () => {
    let calls = 0
    const { qc } = await mountPage(() => {
      calls++
      return Promise.resolve(
        okResp({
          items: [
            calls === 1
              ? sessionFixture({ state: 'busy', last_seq: 3 })
              : sessionFixture({ state: 'ended', ended_reason: 'process_exited', last_seq: 8 }),
          ],
        }),
      )
    })
    await qc.invalidateQueries({ queryKey: ['ai', 'sessions'] })
    await flushPromises()
    expect(rowText('ais_0000000000000001')).toContain('已结束')
  })

  it('未知会话 id 的事件不产生新行、不报错', async () => {
    const { listeners } = await mountPage(() =>
      Promise.resolve(okResp({ items: [sessionFixture()] })),
    )
    const before = document.querySelectorAll('[data-testid^="session-"]').length
    emit(listeners, 'ai.session', { session_id: 'ais_ghost', state: 'failed', last_seq: 1 })
    await flushPromises()
    expect(document.querySelectorAll('[data-testid^="session-"]').length).toBe(before)
    expect(document.querySelector('[data-testid="session-ais_ghost"]')).toBeNull()
  })

  it('failed 会话显示结束原因与告警（kill_failed 可见，列表有告警标记）', async () => {
    await mountPage(() =>
      Promise.resolve(
        okResp({
          items: [
            sessionFixture({
              state: 'failed',
              ended_reason: 'start_failed',
              exit_code: 2,
              warnings: ['kill_failed'],
            }),
          ],
        }),
      ),
    )
    document
      .querySelector<HTMLButtonElement>('[data-testid="session-ais_0000000000000001"]')!
      .click()
    await flushPromises()
    const inspector =
      document.querySelector('[data-testid="ai-terminal-inspector"]')?.textContent ?? ''
    expect(inspector).toContain('启动失败')
    expect(inspector).toContain('kill_failed')
    expect(document.querySelector('.warning-badge')).not.toBeNull()
  })
})
