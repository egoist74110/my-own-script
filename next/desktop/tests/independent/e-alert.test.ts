// 方向 E 告警态（独立编写）：横幅 / 任务行 / 检查器 / 导航角标 / 告警开关。
// 只用假 socket 与假 fetch，不连真实后端。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot, json, openConnection } from '../unit/boot'
import { FakeSocket, env, resetSeq } from '../unit/helpers'
import { createWiFake, summary } from '../unit/wi-fake'

const DEFAULT_REASON = '后端报告告警（未提供原因）'
const QUIET = { active: false, reason: null, changed_at: '2026-10-22T10:00:00Z' }
const ALERT = (reason: unknown = 'S0 DEMO ALERT') => ({
  active: true,
  reason,
  changed_at: '2026-10-22T10:01:00Z',
})

function alertEnv(seq: number, active: boolean, reason: unknown = null) {
  return env('system.alert', { active, reason, changed_at: '2026-10-22T10:01:00Z' }, { seq })
}
function helloEnv(seq: number, alert: unknown = QUIET, pid = 4242) {
  return env('system.hello', { pid, version: '0.0.0-indep', alert }, { seq })
}

// ── S5D2 独立夹具：按正式 DTO（contracts/openapi.json）构造的假 AI 后端，只在本文件内使用 ──
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- 测试夹具按 DTO 动态构造
type Fx = Record<string, any>
interface FakeReq {
  method: string
  path: string
  search: URLSearchParams
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- 测试夹具按 DTO 动态构造
  body: any
}
const fxJson = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

export function fxSession(over: Fx): Fx {
  return {
    kind: 'chat',
    cli: 'claude',
    profile: 'prof-1',
    repo: { id: 'repo-1', name: 'my-own-script' },
    state: 'idle',
    created_at: '2026-10-24T09:00:00Z',
    last_seq: 0,
    pending_approval: false,
    queue_len: 0,
    warnings: [],
    ...over,
  }
}

export function fxEvent(
  sid: string,
  seq: number,
  kind: string,
  payload: Fx,
  ts = '2026-10-24T09:00:00Z',
): Fx {
  return { session_id: sid, session_seq: seq, ts, kind, payload }
}

export function fxApprovalPending(
  sid: string,
  seq: number,
  aid = 'ap-1',
  summary = 'pnpm vitest run',
): Fx {
  return fxEvent(sid, seq, 'approval', {
    approval_id: aid,
    state: 'pending',
    tool: 'Bash',
    summary,
  })
}

/** 假后端：GET 会话/事件、POST 审批/消息；记录全部请求；可注入覆盖响应。 */
export class FakeAi {
  reqs: FakeReq[] = []
  settled = new Set<string>()
  override?: (r: FakeReq) => Response | undefined
  private events = new Map<string, Fx[]>()
  constructor(
    public sessions: Fx[],
    events: Record<string, Fx[]>,
  ) {
    for (const [sid, list] of Object.entries(events)) this.events.set(sid, [...list])
  }
  fetch = ((req: Request) => this.route(req)) as unknown as typeof fetch
  appendEvent(sid: string, kind: string, payload: Fx): Fx {
    const list = this.events.get(sid) ?? []
    const ev = fxEvent(sid, (list.at(-1)?.session_seq ?? 0) + 1, kind, payload)
    list.push(ev)
    this.events.set(sid, list)
    return ev
  }
  posts(suffix: string): FakeReq[] {
    return this.reqs.filter((r) => r.method === 'POST' && r.path.endsWith(suffix))
  }
  private async route(req: Request): Promise<Response> {
    const u = new URL(req.url)
    const p = u.pathname
    const body =
      req.method === 'GET'
        ? undefined
        : await req
            .clone()
            .json()
            .catch(() => undefined)
    const r: FakeReq = { method: req.method, path: p, search: u.searchParams, body }
    this.reqs.push(r)
    const o = this.override?.(r)
    if (o) return o
    if (p === '/health')
      return fxJson({ status: 'ok', version: '0.0.0-s5d2', pid: 4242, uptime_s: 1, alert: false })
    if (p === '/api/system/alert') return fxJson({ active: false, reason: null, changed_at: 't' })
    if (p === '/api/ai')
      return fxJson({
        revision: 1,
        profiles: [],
        selected_profile_id: null,
        defaults: {},
        analysis: {},
        model_presets: {},
        store_state: 'ready',
      })
    if (p === '/api/ado') return fxJson({ local_repos: [{ id: 'repo-1', name: 'my-own-script' }] })
    if (p === '/api/ai/sessions' && req.method === 'GET') return fxJson({ items: this.sessions })
    let m = p.match(/^\/api\/ai\/sessions\/([^/]+)\/events$/)
    if (m && req.method === 'GET') {
      const sid = m[1]!
      const after = Number(u.searchParams.get('after_seq') ?? 0)
      const all = this.events.get(sid) ?? []
      return fxJson({
        items: all.filter((e) => e.session_seq > after),
        last_seq: all.at(-1)?.session_seq ?? 0,
      })
    }
    m = p.match(/^\/api\/ai\/sessions\/([^/]+)\/approvals\/([^/]+)$/)
    if (m && req.method === 'POST') {
      const [, sid, aid] = m as unknown as [string, string, string]
      const pending = (this.events.get(sid) ?? []).find(
        (e) => e.kind === 'approval' && e.payload.approval_id === aid,
      )
      if (!pending) return fxJson({ code: 'approval_not_found', detail: 'fake' }, 404)
      if (this.settled.has(aid)) return fxJson({ code: 'approval_settled', detail: 'fake' }, 409)
      this.settled.add(aid)
      const state = body?.decision === 'deny' ? 'denied' : 'allowed'
      this.appendEvent(sid, 'approval', { ...pending.payload, state, decision: body?.decision })
      return fxJson({ approval_id: aid, state })
    }
    m = p.match(/^\/api\/ai\/sessions\/([^/]+)\/messages$/)
    if (m && req.method === 'POST') return fxJson({ status: 'sent', position: 0 })
    return fxJson({ code: 'not_found', detail: 'fake' }, 404)
  }
}

/** 向后端 WS 推送一条 ai 主题事件（模拟后端推送，不是页面内部状态）。 */
export function pushAi(sock: FakeSocket, type: string, data: Fx) {
  sock.emit(env(type, data, { topic: 'ai' }))
}

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
})
afterEach(() => {
  document.body.innerHTML = ''
  vi.useRealTimers()
})

describe('告警态：同时出现在横幅、任务行、检查器、导航角标', () => {
  it('告警开启后：页面区顶部 warn 横幅、侧栏连接状态行变橙；没有导航角标', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, 'S0 DEMO ALERT'))
    await flushPromises()

    const banner = b.wrapper.get('[data-testid=alert-banner]')
    expect(banner.attributes('role')).toBe('alert')
    expect(banner.attributes('data-tone')).toBe('warn')
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe('S0 DEMO ALERT')
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-alert')).toBe('true')
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('true')
    expect(b.wrapper.find('[data-testid=nav-alert-badge]').exists()).toBe(false)
    await b.done()
  })

  it('告警解除后横幅与连接状态行的告警态全部还原', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, 'x'))
    await flushPromises()
    b.sock.emit(alertEnv(101, false, null))
    await flushPromises()

    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-alert')).toBe('false')
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('false')
    await b.done()
  })

  it('reason 为 null 或空串时显示默认文案（含「未提供原因」）', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, null))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe(DEFAULT_REASON)

    b.sock.emit(alertEnv(101, true, ''))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe(DEFAULT_REASON)
    await b.done()
  })

  it('reason 为纯空白（"   "）时也应回落到默认文案（边界：空白等同于空）', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, '   '))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text().trim()).toBe(DEFAULT_REASON)
    await b.done()
  })

  it('超长 reason 完整出现在横幅文本中，不被截断', async () => {
    const long = 'R'.repeat(2000) + '-END'
    const b = await boot()
    b.sock.emit(alertEnv(100, true, long))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe(long)
    await b.done()
  })

  it('reason 含 HTML 时按文本显示，不生成元素也不执行脚本', async () => {
    const payload = '<img src=x onerror="window.__alertXss=1"><b id="pwn">boom</b>'
    const b = await boot()
    b.sock.emit(alertEnv(100, true, payload))
    await flushPromises()
    const reason = b.wrapper.get('[data-testid=alert-reason]')
    expect(reason.text()).toBe(payload)
    expect(reason.find('img').exists()).toBe(false)
    expect(reason.find('#pwn').exists()).toBe(false)
    expect((window as unknown as Record<string, unknown>).__alertXss).toBeUndefined()
    await b.done()
  })

  it('reason 为非字符串（数字）时事件被忽略，告警不生效', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, 42))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    expect(b.store.alert.active).toBe(false)
    await b.done()
  })

  it('告警态下工作区仍可交互：刷新、点行选中、导航切换、⌘K 聚焦', async () => {
    const wi = createWiFake()
    wi.lists['proj:a|开发中'] = { items: [summary(7), summary(8)], truncated: false, omitted: 0 }
    const b = await boot({ path: '/work-items', fetchImpl: wi.fetch })
    b.sock.emit(helloEnv(99))
    b.sock.emit(alertEnv(100, true, 'x'))
    await vi.waitFor(() => expect(b.wrapper.find('[data-testid=wi-row-7]').exists()).toBe(true))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)

    const calls = () => wi.calls.length
    const n = calls()
    await b.wrapper.get('[data-testid=refresh]').trigger('click')
    await flushPromises()
    expect(calls()).toBeGreaterThan(n)

    await b.wrapper.get('[data-testid=wi-row-8]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=wi-row-8]').attributes('data-selected')).toBe('true')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }))
    await flushPromises()
    expect(document.activeElement).toBe(b.wrapper.get('input[type=search]').element)

    await b.wrapper.get('nav a[href="/ai"]').trigger('click')
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe('/ai'))
    await b.done()
  })

  it('告警横幅没有遮罩或模态层（无 dialog / aria-modal / 全屏覆盖）', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, 'x'))
    await flushPromises()
    expect(document.querySelector('[aria-modal=true], dialog, [role=dialog]')).toBeNull()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
    await b.done()
  })

  it('告警横幅在 /work-items 与 /ai 页同样出现，页面内容仍渲染', async () => {
    // /work-items 页内容由真实接口提供（假后端），不再是 mock 行
    const wi = createWiFake()
    wi.lists['proj:a|开发中'] = { items: [summary(7)], truncated: false, omitted: 0 }
    // S5D2 迁移：/ai 使用按正式 DTO 构造的假 AI 后端（会话列表由 GET /api/ai/sessions 提供）
    const ai = new FakeAi([fxSession({ id: 's1', state: 'idle' })], { s1: [] })
    for (const path of ['/work-items', '/ai']) {
      const b = await boot({ path, fetchImpl: path === '/work-items' ? wi.fetch : ai.fetch })
      b.sock.emit(helloEnv(99))
      b.sock.emit(alertEnv(100, true, 'x'))
      await flushPromises()
      await vi.waitFor(() => {
        expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
      })
      if (path === '/work-items') {
        await vi.waitFor(() => expect(b.wrapper.find('[data-testid=wi-row-7]').exists()).toBe(true))
      } else {
        expect(b.wrapper.find('[data-testid=session-s1]').exists()).toBe(true)
      }
      await b.done()
    }
  })
})

describe('系统事件 seq 基线与 hello 对齐', () => {
  it('seq 倒退或相等的 alert 事件被忽略，严格递增的才生效', async () => {
    const b = await boot()
    b.sock.emit(helloEnv(100))
    await flushPromises()

    b.sock.emit(alertEnv(50, true, 'stale'))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)

    b.sock.emit(alertEnv(100, true, 'same-seq'))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)

    b.sock.emit(alertEnv(101, true, 'fresh'))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe('fresh')

    b.sock.emit(alertEnv(101, false, null))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe('fresh')
    await b.done()
  })

  it('system.hello 携带 alert=active 时，连接即刻显示告警（无需单独 alert 事件）', async () => {
    const b = await boot()
    b.sock.emit(helloEnv(7, ALERT('from-hello')))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe('from-hello')
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('true')
    await b.done()
  })

  it('后端重启后 hello 重新对齐 seq 基线：之后 seq=2 的 alert 必须生效', async () => {
    const b = await boot()
    b.sock.emit(helloEnv(500, QUIET))
    await flushPromises()
    b.sock.emit(helloEnv(1, ALERT('after-restart')))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe('after-restart')

    b.sock.emit(alertEnv(2, false, null))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    await b.done()
  })

  it('畸形 alert 载荷（active 非布尔）被忽略', async () => {
    const b = await boot()
    b.sock.emit(env('system.alert', { active: 'yes', reason: null, changed_at: '' }, { seq: 200 }))
    await flushPromises()
    expect(b.store.alert.active).toBe(false)
    await b.done()
  })
})

describe('告警开关：只请求后端，不本地切换', () => {
  it('点击开关发出带 Bearer 的 POST，本地状态不变，直到 alert 事件到达', async () => {
    const b = await boot()
    await openConnection(b)
    const sw = () => b.wrapper.get('[role=switch]')
    expect(sw().attributes('aria-checked')).toBe('false')

    await sw().trigger('click')
    await flushPromises()

    const post = b.fetchMock.mock.calls
      .map((c) => c[0] as Request)
      .find((r) => r.url.endsWith('/api/system/alert'))
    expect(post, 'POST /api/system/alert 未发出').toBeDefined()
    expect(post!.method).toBe('POST')
    expect(post!.headers.get('authorization')).toBe('Bearer fake-token')
    expect(post!.url).not.toContain('fake-token')
    expect(await post!.clone().json()).toEqual({ active: true, reason: 'S0 DEMO ALERT' })

    expect(b.store.alert.active).toBe(false)
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    expect(sw().attributes('aria-checked')).toBe('false')

    b.sock.emit(alertEnv(900, true, 'S0 DEMO ALERT'))
    await flushPromises()
    expect(sw().attributes('aria-checked')).toBe('true')
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
    await b.done()
  })

  it('后端返回 500 时显示请求失败文案，开关与横幅不变', async () => {
    const fetchImpl = vi.fn(async (req: Request) =>
      req.method === 'POST'
        ? new Response('{"detail":"boom"}', { status: 500 })
        : json({ status: 'ok', version: '9.9.9', pid: 1, uptime_s: 1, alert: false }),
    ) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    await openConnection(b)
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toContain('请求失败 (500)')
    expect(b.wrapper.get('[role=switch]').attributes('aria-checked')).toBe('false')
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    await b.done()
  })
})
