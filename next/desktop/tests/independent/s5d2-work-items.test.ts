// S5D2 独立测试：工单 AI 分析请求体、跳转到 /ai 并选中会话、高权限确认、复制提示词与 warnings。
// 只用假后端（工单接口沿用 wi-fake，AI 接口按正式 DTO 构造）；不调用真实 CLI。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from '../unit/boot'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'
import { createWiFake, detail, summary, type WiFake } from '../unit/wi-fake'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
})

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

const PROFILE_CLAUDE = {
  id: 'prof-claude',
  name: 'Claude Code',
  cli: 'claude',
  command: 'claude',
  upgrade_command: '',
  builtin: true,
  resolved: {
    ok: true,
    path: '/usr/local/bin/claude',
    version: '1.0.0',
    path_hint: '/usr/local/bin/claude',
  },
}
const PROFILE_AGY = { ...PROFILE_CLAUDE, id: 'prof-agy', name: 'agy', cli: 'agy', command: 'agy' }

interface WiEnv {
  wi: WiFake
  ai: FakeAi
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- 测试夹具按 DTO 动态构造
  posts: Array<{ path: string; body: any }>
  promptQueries: string[]
  fetch: typeof fetch
}

/** 工单页假后端：工单接口沿用 wi-fake；AI 概览、会话、分析与提示词按正式 DTO 构造。 */
function wiEnv(opts: { profiles?: unknown[]; sessions?: Fx[] } = {}): WiEnv {
  const wi = createWiFake()
  wi.lists['proj:a|开发中'] = { items: [summary(7)], truncated: false, omitted: 0 }
  wi.details[7] = detail(7)
  ;(wi.ado as unknown as { local_repos: unknown[] }).local_repos = [
    { id: 'repo-1', name: 'my-own-script' },
  ]
  const ai = new FakeAi(opts.sessions ?? [], {})
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- 测试夹具按 DTO 动态构造
  const posts: Array<{ path: string; body: any }> = []
  const promptQueries: string[] = []
  const fetchImpl = (async (req: Request): Promise<Response> => {
    const u = new URL(req.url)
    const p = u.pathname
    if (p === '/api/ai' && req.method === 'GET')
      return fxJson({
        revision: 1,
        profiles: opts.profiles ?? [PROFILE_CLAUDE],
        selected_profile_id: 'prof-claude',
        defaults: {},
        analysis: {},
        model_presets: {},
        store_state: 'ready',
      })
    if (p.endsWith('/ai-analysis') && req.method === 'POST') {
      const body = await req.clone().json()
      posts.push({ path: p, body })
      return fxJson(
        fxSession({ id: 'sNEW', kind: 'chat', cli: 'claude', state: 'starting', last_seq: 0 }),
        200,
      )
    }
    if (p.endsWith('/ai-prompt') && req.method === 'GET') {
      promptQueries.push(u.search)
      return fxJson({ prompt: '请分析工单 #7', warnings: ['附件未包含在提示词中'] })
    }
    if (p === '/api/ai/sessions' || p.endsWith('/events') || p.endsWith('/messages'))
      return ai.fetch(req)
    return wi.fetch(req)
  }) as unknown as typeof fetch
  return { wi, ai, posts, promptQueries, fetch: fetchImpl }
}

async function openWi(env: WiEnv) {
  const b = await boot({ path: '/work-items', fetchImpl: env.fetch })
  b.sock.emit(hello())
  await flushPromises()
  for (let i = 0; i < 3; i++) await flushPromises()
  await b.wrapper.get('[data-testid=wi-row-7]').trigger('click')
  for (let i = 0; i < 3; i++) await flushPromises()
  return b
}

const sheet = (testid: string) =>
  document.querySelector(`[data-testid=${testid}]`) as HTMLElement | null

describe('S5D2 工单 AI 分析与复制提示词', () => {
  it('AI 分析请求体含 request_id、project_id、repo_id、profile_id，且 ack_high_risk=false', async () => {
    const env = wiEnv()
    const b = await openWi(env)
    await b.wrapper.get('[data-testid=ai-analysis-btn]').trigger('click')
    await flushPromises()
    sheet('confirm-analysis-btn')!.click()
    await flushPromises()
    expect(env.posts).toHaveLength(1)
    expect(env.posts[0]!.path).toBe('/api/work-items/7/ai-analysis')
    expect(env.posts[0]!.body).toEqual({
      request_id: expect.any(String),
      project_id: 'proj:a',
      repo_id: 'repo-1',
      profile_id: 'prof-claude',
      ack_high_risk: false,
    })
    await b.done()
  })

  it('分析发起后跳转到 /ai，并选中新创建的会话', async () => {
    const env = wiEnv({
      // 旧会话排在前面：新分析会话必须被选中，而不是默认第一条
      sessions: [
        fxSession({ id: 's0', state: 'idle', last_seq: 0 }),
        fxSession({ id: 'sNEW', state: 'starting', last_seq: 0 }),
      ],
    })
    const b = await openWi(env)
    await b.wrapper.get('[data-testid=ai-analysis-btn]').trigger('click')
    await flushPromises()
    sheet('confirm-analysis-btn')!.click()
    await flushPromises()
    for (let i = 0; i < 20; i++) await flushPromises()
    // /ai 路由为懒加载组件，导航需等待真实的动态 import 完成
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe('/ai'))
    await vi.waitFor(() => expect(b.wrapper.find('[data-testid=session-sNEW]').exists()).toBe(true))
    expect(b.wrapper.get('[data-testid=session-sNEW]').attributes('data-selected')).toBe('true')
    await b.done()
  })

  it('agy（高权限档）未确认风险时不发送，确认后请求体带 ack_high_risk=true', async () => {
    const env = wiEnv({ profiles: [PROFILE_AGY] })
    const b = await openWi(env)
    await b.wrapper.get('[data-testid=ai-analysis-btn]').trigger('click')
    await flushPromises()
    expect(sheet('analysis-high-risk-box')).not.toBeNull()
    sheet('confirm-analysis-btn')!.click()
    await flushPromises()
    expect(env.posts).toHaveLength(0)
    expect(sheet('analysis-error-banner')?.textContent ?? '').toContain('高权限')
    ;(sheet('analysis-high-risk-ack') as HTMLInputElement).click()
    await flushPromises()
    sheet('confirm-analysis-btn')!.click()
    await flushPromises()
    expect(env.posts).toHaveLength(1)
    expect(env.posts[0]!.body.ack_high_risk).toBe(true)
    expect(env.posts[0]!.body.profile_id).toBe('prof-agy')
    await b.done()
  })

  it('复制提示词：写入剪贴板并显示后端返回的 warnings；请求带 project_id', async () => {
    const written: string[] = []
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: async (t: string) => void written.push(t) },
    })
    const env = wiEnv()
    const b = await openWi(env)
    await b.wrapper.get('[data-testid=copy-prompt-btn]').trigger('click')
    await flushPromises()
    expect(written).toEqual(['请分析工单 #7'])
    expect(b.wrapper.get('[data-testid=prompt-warnings]').text()).toContain('附件未包含在提示词中')
    expect(env.promptQueries[0]).toContain('project_id=proj%3Aa')
    await b.done()
  })

  it('工单页检查器不应保留 S5 占位（禁用的“即将推出”AI 面板）', async () => {
    const env = wiEnv()
    const b = await openWi(env)
    expect(b.wrapper.find('[data-testid=wi-ai]').exists()).toBe(false)
    await b.done()
  })
})
