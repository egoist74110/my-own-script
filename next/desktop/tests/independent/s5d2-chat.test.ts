// S5D2 独立测试：AI 会话区（事件流、审批、排队与错误码、续聊、Markdown 清洗）。
// 只用按正式 DTO 构造的假后端与假 WebSocket；不使用 mock，不调用真实 CLI。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/features/ai/markdown'
import { boot } from '../unit/boot'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'

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

const press = (key: string, target: EventTarget = window) =>
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))

async function openChat(fake: FakeAi) {
  const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  for (let i = 0; i < 3; i++) await flushPromises()
  return { ...b, fake }
}
const focusChat = (w: { get: (s: string) => { element: Element } }) =>
  (w.get('[data-testid=chat-view]').element as HTMLElement).focus()
const pending = () =>
  new FakeAi(
    [fxSession({ id: 's1', state: 'awaiting_approval', pending_approval: true, last_seq: 2 })],
    {
      s1: [
        fxEvent('s1', 1, 'assistant', { text: '准备运行测试' }),
        fxApprovalPending('s1', 2, 'ap-1', 'pnpm vitest run'),
      ],
    },
  )

describe('S5D2 事件流：去重、乱序、断线补齐、对账', () => {
  it('同一 session_seq 的重复 ai.event 只渲染一次（助手文本不翻倍）', async () => {
    const b = await openChat(pending())
    const dup = fxEvent('s1', 3, 'assistant', { text: '甲' })
    pushAi(b.sock, 'ai.event', dup)
    pushAi(b.sock, 'ai.event', dup)
    await flushPromises()
    expect(b.wrapper.get('[data-testid=chat-flow]').text().split('甲').length - 1).toBe(1)
    await b.done()
  })

  it('乱序到达（seq 4 先于 seq 3）按 session_seq 升序渲染', async () => {
    const b = await openChat(
      new FakeAi([fxSession({ id: 's1', state: 'busy', last_seq: 2 })], {
        s1: [fxEvent('s1', 1, 'turn_started', { message: '问' })],
      }),
    )
    pushAi(b.sock, 'ai.event', fxEvent('s1', 4, 'assistant', { text: '乙' }))
    pushAi(b.sock, 'ai.event', fxEvent('s1', 3, 'assistant', { text: '甲' }))
    await flushPromises()
    const text = b.wrapper.get('[data-testid=chat-flow]').text()
    expect(text.indexOf('甲')).toBeGreaterThan(-1)
    expect(text.indexOf('甲')).toBeLessThan(text.indexOf('乙'))
    await b.done()
  })

  it('WS 已推送的 seq 与随后 after_seq 补齐的 GET 结果重叠时不重复渲染', async () => {
    const fake = new FakeAi([fxSession({ id: 's1', state: 'busy', last_seq: 2 })], {
      s1: [
        fxEvent('s1', 1, 'turn_started', { message: '问' }),
        fxEvent('s1', 2, 'assistant', { text: '丙' }),
      ],
    })
    const b = await openChat(fake)
    // 后端新产生 seq 3；WS 推送了它，随后用户发送消息触发 after_seq 补齐，GET 再次返回 seq 2 与 3
    const ev3 = fake.appendEvent('s1', 'assistant', { text: '丁' })
    pushAi(b.sock, 'ai.event', ev3)
    pushAi(b.sock, 'ai.event', fxEvent('s1', 2, 'assistant', { text: '丙' }))
    await flushPromises()
    await b.wrapper.get('[data-testid=composer-textarea]').setValue('继续')
    await b.wrapper.get('[data-testid=composer-textarea]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    const refetch = b.fake.reqs.filter((r) => r.path.endsWith('/events'))
    expect(refetch.length).toBeGreaterThan(1)
    const text = b.wrapper.get('[data-testid=chat-flow]').text()
    expect(text.split('丙').length - 1).toBe(1)
    expect(text.split('丁').length - 1).toBe(1)
    await b.done()
  })

  it('较新的 GET 快照（last_seq 更大）胜过较旧的 ai.session 推送', async () => {
    const b = await openChat(
      new FakeAi([fxSession({ id: 's1', state: 'busy', last_seq: 5 })], { s1: [] }),
    )
    pushAi(b.sock, 'ai.session', {
      session_id: 's1',
      state: 'idle',
      ended_reason: null,
      last_seq: 4,
    })
    await flushPromises()
    expect(b.wrapper.get('[data-testid=session-s1]').text()).toContain('运行中')
    await b.done()
  })

  it('较新的 ai.session 推送胜过较旧的 GET 快照', async () => {
    const b = await openChat(
      new FakeAi([fxSession({ id: 's1', state: 'busy', last_seq: 5 })], { s1: [] }),
    )
    pushAi(b.sock, 'ai.session', {
      session_id: 's1',
      state: 'idle',
      ended_reason: null,
      last_seq: 6,
    })
    await flushPromises()
    expect(b.wrapper.get('[data-testid=session-s1]').text()).toContain('空闲')
    await b.done()
  })
})

describe('S5D2 审批：先到者生效、过期、倒计时、键盘范围', () => {
  it('另一端已决：POST 返回 409 approval_settled，显示“已由另一端处理”', async () => {
    const fake = pending()
    fake.override = (r) =>
      r.method === 'POST' && r.path.endsWith('/approvals/ap-1')
        ? new Response(JSON.stringify({ code: 'approval_settled', detail: 'x' }), {
            status: 409,
            headers: { 'content-type': 'application/json' },
          })
        : undefined
    const b = await openChat(fake)
    await b.wrapper.get('[data-testid=approval-deny]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=chat-error-banner]').text()).toContain('已由另一端处理')
    await b.done()
  })

  it('审批过期：POST 返回 409 approval_expired，显示超时文案', async () => {
    const fake = pending()
    fake.override = (r) =>
      r.method === 'POST' && r.path.endsWith('/approvals/ap-1')
        ? new Response(JSON.stringify({ code: 'approval_expired', detail: 'x' }), {
            status: 409,
            headers: { 'content-type': 'application/json' },
          })
        : undefined
    const b = await openChat(fake)
    await b.wrapper.get('[data-testid=approval-allow-once]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=chat-error-banner]').text()).toContain('超时')
    await b.done()
  })

  it('倒计时归零后审批按钮禁用（不能再提交已过期的审批）', async () => {
    // ts 设为 541 秒前：挂载即为 0:00
    const old = new Date(Date.now() - 541 * 1000).toISOString()
    const fake = new FakeAi(
      [fxSession({ id: 's1', state: 'awaiting_approval', pending_approval: true, last_seq: 1 })],
      {
        s1: [
          fxEvent(
            's1',
            1,
            'approval',
            { approval_id: 'ap-1', state: 'pending', tool: 'Bash', summary: 'pnpm test' },
            old,
          ),
        ],
      },
    )
    const b = await openChat(fake)
    expect(b.wrapper.get('[data-testid=approval-card]').text()).toContain('0:00')
    expect(b.wrapper.get('[data-testid=approval-allow-once]').attributes('disabled')).toBeDefined()
    expect(
      b.wrapper.get('[data-testid=approval-allow-session]').attributes('disabled'),
    ).toBeDefined()
    expect(b.wrapper.get('[data-testid=approval-deny]').attributes('disabled')).toBeDefined()
    await b.done()
  })

  it('已决审批的 pending 事件被重复投递（同一 session_seq）时，审批卡不得重新出现', async () => {
    const b = await openChat(pending())
    focusChat(b.wrapper)
    press('y')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(false)
    // 重放同一条 seq=2 的 pending 事件（已被去重的旧事件）
    pushAi(b.sock, 'ai.event', fxApprovalPending('s1', 2, 'ap-1', 'pnpm vitest run'))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(false)
    await b.done()
  })

  it('键盘只在会话区焦点时生效：焦点在 body 时按 y 不发出请求', async () => {
    const b = await openChat(pending())
    ;(document.activeElement as HTMLElement | null)?.blur?.()
    press('y')
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')).toHaveLength(0)
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(true)
    await b.done()
  })

  it('会话区焦点且审批待决时按 y 发出 allow_once（正向对照）', async () => {
    const b = await openChat(pending())
    focusChat(b.wrapper)
    press('y')
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')[0]!.body).toEqual({ decision: 'allow_once' })
    await b.done()
  })
})

describe('S5D2 排队、发送与续聊的错误码文案', () => {
  it('排队中显示“已排队 N 条消息”', async () => {
    const b = await openChat(
      new FakeAi([fxSession({ id: 's1', state: 'busy', queue_len: 2, last_seq: 0 })], { s1: [] }),
    )
    expect(b.wrapper.get('[data-testid=queue-indicator]').text()).toContain('已排队 2 条消息')
    await b.done()
  })

  it('发送返回 409 ai_queue_full：显示队列已满文案', async () => {
    const fake = new FakeAi([fxSession({ id: 's1', state: 'busy', last_seq: 0 })], { s1: [] })
    fake.override = (r) =>
      r.path.endsWith('/messages')
        ? new Response(JSON.stringify({ code: 'ai_queue_full', detail: 'x' }), {
            status: 409,
            headers: { 'content-type': 'application/json' },
          })
        : undefined
    const b = await openChat(fake)
    await b.wrapper.get('[data-testid=composer-textarea]').setValue('再问一次')
    await b.wrapper.get('[data-testid=composer-textarea]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(b.wrapper.get('[data-testid=chat-error-banner]').text()).toContain('消息队列已满')
    await b.done()
  })

  it('发送返回 409 session_ended：显示会话已结束文案', async () => {
    const fake = new FakeAi([fxSession({ id: 's1', state: 'idle', last_seq: 0 })], { s1: [] })
    fake.override = (r) =>
      r.path.endsWith('/messages')
        ? new Response(JSON.stringify({ code: 'session_ended', detail: 'x' }), {
            status: 409,
            headers: { 'content-type': 'application/json' },
          })
        : undefined
    const b = await openChat(fake)
    await b.wrapper.get('[data-testid=composer-textarea]').setValue('还在吗')
    await b.wrapper.get('[data-testid=composer-textarea]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(b.wrapper.get('[data-testid=chat-error-banner]').text()).toContain('会话已结束')
    await b.done()
  })

  it('续聊返回 409 session_active：显示仍在运行文案', async () => {
    const fake = new FakeAi(
      [fxSession({ id: 's1', state: 'ended', has_external_id: true, last_seq: 0 })],
      { s1: [] },
    )
    fake.override = (r) =>
      r.path.endsWith('/resume')
        ? new Response(JSON.stringify({ code: 'session_active', detail: 'x' }), {
            status: 409,
            headers: { 'content-type': 'application/json' },
          })
        : undefined
    const b = await openChat(fake)
    await b.wrapper.get('[data-testid=resume-session-btn]').trigger('click')
    await flushPromises()
    ;(document.querySelector('[data-testid=confirm-resume-btn]') as HTMLButtonElement).click()
    await flushPromises()
    expect(b.wrapper.get('[data-testid=chat-error-banner]').text()).toContain('仍在运行中')
    await b.done()
  })

  it('续聊返回 409 resume_unavailable：显示无外部标识文案', async () => {
    const fake = new FakeAi(
      [fxSession({ id: 's1', state: 'ended', has_external_id: true, last_seq: 0 })],
      { s1: [] },
    )
    fake.override = (r) =>
      r.path.endsWith('/resume')
        ? new Response(JSON.stringify({ code: 'resume_unavailable', detail: 'x' }), {
            status: 409,
            headers: { 'content-type': 'application/json' },
          })
        : undefined
    const b = await openChat(fake)
    await b.wrapper.get('[data-testid=resume-session-btn]').trigger('click')
    await flushPromises()
    ;(document.querySelector('[data-testid=confirm-resume-btn]') as HTMLButtonElement).click()
    await flushPromises()
    expect(b.wrapper.get('[data-testid=chat-error-banner]').text()).toContain('无外部标识')
    await b.done()
  })
})

describe('S5D2 Markdown 清洗（渲染结果不含脚本、事件属性与 javascript: 链接）', () => {
  it('<script>、onerror= 与 javascript: 链接被移除', () => {
    const html = renderMarkdown(
      '正常 **粗体**\n\n<script>window.__x=1</script>\n\n<img src="x" onerror="window.__y=1">\n\n[点我](javascript:alert(1))',
    )
    const host = document.createElement('div')
    host.innerHTML = html
    expect(host.querySelector('script')).toBeNull()
    expect(host.querySelector('[onerror]')).toBeNull()
    expect(host.innerHTML).not.toMatch(/onerror=/i)
    for (const a of Array.from(host.querySelectorAll('a'))) {
      expect(a.getAttribute('href') ?? '').not.toMatch(/^javascript:/i)
    }
    expect(host.querySelector('strong')?.textContent).toBe('粗体')
  })

  it('合法 https 链接保留，并带 rel=noopener noreferrer', () => {
    const host = document.createElement('div')
    host.innerHTML = renderMarkdown('[文档](https://example.com/a)')
    const a = host.querySelector('a')!
    expect(a.getAttribute('href')).toBe('https://example.com/a')
    expect(a.getAttribute('rel')).toBe('noopener noreferrer')
  })
})

describe('S5D2 新建会话：高权限档需二次确认', () => {
  const OVERVIEW = {
    revision: 1,
    profiles: [
      {
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
      },
    ],
    selected_profile_id: 'prof-claude',
    defaults: {},
    analysis: {},
    model_presets: {},
    store_state: 'ready',
  }

  it('bypassPermissions 未确认时不发送；确认后请求体带 ack_high_risk=true', async () => {
    const fake = new FakeAi([], {})
    fake.override = (r) => (r.path === '/api/ai' ? fxJson(OVERVIEW) : undefined)
    const b = await openChat(fake)
    await b.wrapper.get('[data-testid=new-session-btn]').trigger('click')
    await flushPromises()
    ;(document.querySelector('[data-testid=kind-chat-radio]') as HTMLInputElement).click()
    await flushPromises()
    const prof = document.querySelector('[data-testid=profile-select]') as HTMLSelectElement
    prof.value = 'prof-claude'
    prof.dispatchEvent(new Event('change'))
    await flushPromises()
    const sel = document.querySelector('[data-testid=permission-select]') as HTMLSelectElement
    expect(sel).not.toBeNull()
    sel.value = 'bypassPermissions'
    sel.dispatchEvent(new Event('change'))
    await flushPromises()
    expect(document.querySelector('[data-testid=high-risk-box]')).not.toBeNull()
    ;(document.querySelector('[data-testid=confirm-create-btn]') as HTMLButtonElement).click()
    await flushPromises()
    expect(
      fake.reqs.filter((r) => r.method === 'POST' && r.path === '/api/ai/sessions'),
    ).toHaveLength(0)
    ;(document.querySelector('[data-testid=high-risk-ack-checkbox]') as HTMLInputElement).click()
    await flushPromises()
    ;(document.querySelector('[data-testid=confirm-create-btn]') as HTMLButtonElement).click()
    await flushPromises()
    const posts = fake.reqs.filter((r) => r.method === 'POST' && r.path === '/api/ai/sessions')
    expect(posts).toHaveLength(1)
    expect(posts[0]!.body).toEqual(
      expect.objectContaining({
        ack_high_risk: true,
        permission: 'bypassPermissions',
        profile_id: 'prof-claude',
      }),
    )
    await b.done()
  })
})
