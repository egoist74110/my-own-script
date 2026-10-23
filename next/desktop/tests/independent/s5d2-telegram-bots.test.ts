// S5D2 独立测试：设置页 AI 机器人卡片（启用确认、telegram.status 按 slot、bot_in_use、Token 不泄露）与后端离线/items 缺失。
// 设置接口沿用 settings-fake 的默认处理；AI 机器人与 AI 会话接口按正式 DTO 构造；不连接真实 Telegram。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AIBotsView } from '@/features/ai/api'
import { boot } from '../unit/boot'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'
import { createFake, json } from '../unit/settings-fake'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
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

// 假 Token（格式为 <数字>:<字符串> 以通过前端校验；非真实凭据）
const TOKEN = '424242:FAKE-INDEP-NOT-A-REAL-TOKEN-0000'
const AI_BOTS: AIBotsView = {
  revision: 5,
  warnings: [],
  items: [
    {
      ai_id: 'claude_code',
      slot: 'ai:claude_code',
      bot: {
        credential: { present: true, source: 'manual' },
        bot_id: '1001',
        username: 'claude_helper_bot',
      },
      poller: {
        state: 'disabled',
        consecutive_failures: 0,
        last_error_category: null,
        since: '2026-10-24T00:00:00Z',
      },
      control: { enabled: false, bot_id: '1001', enabled_at: null },
      owner: { bound: true, chat_id: '6001', source: 'bound' },
    },
    {
      ai_id: 'codex',
      slot: 'ai:codex',
      bot: {
        credential: { present: true, source: 'manual' },
        bot_id: '1002',
        username: 'codex_helper_bot',
      },
      poller: {
        state: 'disabled',
        consecutive_failures: 0,
        last_error_category: null,
        since: '2026-10-24T00:00:00Z',
      },
      control: { enabled: false, bot_id: '1002', enabled_at: null },
      owner: { bound: true, chat_id: '6001', source: 'bound' },
    },
    {
      ai_id: 'gemini',
      slot: 'ai:gemini',
      bot: { credential: { present: false, source: 'unknown' }, bot_id: null, username: null },
      poller: {
        state: 'disabled',
        consecutive_failures: 0,
        last_error_category: null,
        since: '2026-10-24T00:00:00Z',
      },
      control: { enabled: false, bot_id: null, enabled_at: null },
      owner: { bound: false, chat_id: null, source: null },
    },
  ],
} as unknown as AIBotsView

/** 主机器人视图（与 S4 设置页的 TelegramView 形状一致）：主槽位默认关闭、未绑定 owner。 */
const MAIN_TG = {
  revision: 10,
  warnings: [],
  bot: {
    bot_id: '123456789',
    username: 'MainHelperBot',
    credential: { present: true, source: 'manual' },
  },
  control: { enabled: false, bot_id: '123456789', enabled_at: null },
  owner: { bound: false, chat_id: null, source: null },
  notify: { include_details: false, ui_runs_to_owner: true },
  poller: {
    state: 'disabled',
    since: '2026-10-24T00:00:00Z',
    last_poll_at: null,
    last_error_category: null,
    consecutive_failures: 0,
  },
  acl: { groups: [], members: [] },
} as unknown as Record<string, unknown>

interface TgCall {
  method: string
  path: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- 测试夹具按 DTO 动态构造
  body: any
}

/** 设置页假后端：AI 机器人接口按正式 DTO 构造，其余设置接口沿用 settings-fake 默认处理。 */
function tgFake(over: { enable?: (c: TgCall) => Response | undefined } = {}) {
  const fake = createFake()
  const calls: TgCall[] = []
  fake.handlers.push(async (c) => {
    calls.push({ method: c.method, path: c.path, body: c.body })
    if (c.path === '/api/telegram' && c.method === 'GET') return json(MAIN_TG)
    if (c.path === '/api/telegram/activity' && c.method === 'GET')
      return json({ items: [], truncated: false })
    if (c.path === '/api/telegram/ai-bots' && c.method === 'GET') return json(AI_BOTS)
    if (c.path.endsWith('/control/enable') && c.method === 'POST') {
      const r = over.enable?.({ method: c.method, path: c.path, body: c.body })
      return (
        r ??
        json({
          ...AI_BOTS.items[1],
          control: { enabled: true, bot_id: '1002', enabled_at: '2026-10-24T01:00:00Z' },
        })
      )
    }
    return undefined
  })
  return { fake, calls }
}

async function openTelegram(fetchImpl: typeof fetch) {
  const b = await boot({ path: '/settings', fetchImpl })
  b.sock.emit(hello())
  await flushPromises()
  const tab = b.wrapper.findAll('[role=tab]').find((t) => t.text().includes('Telegram'))
  await tab?.trigger('mousedown')
  for (let i = 0; i < 5; i++) await flushPromises()
  return b
}

const modal = (testid: string) =>
  document.querySelector(`[data-testid=${testid}]`) as HTMLElement | null

describe('S5D2 AI 机器人卡片：启用确认、状态按槽位、bot_in_use、Token 不泄露', () => {
  it('启用必须勾选旧版清空确认，确认后请求体带 ack_old_bot_cleared=true 与 revision', async () => {
    const { fake, calls } = tgFake()
    const b = await openTelegram(fake.fetch)
    await b.wrapper.get('[data-testid=ai-bot-switch-codex]').trigger('click')
    await flushPromises()
    const confirm = modal('confirm-enable-ai-bot-btn') as HTMLButtonElement | null
    expect(confirm).not.toBeNull()
    expect(confirm!.disabled).toBe(true)
    ;(modal('ack-old-cleared-checkbox') as HTMLInputElement).click()
    await flushPromises()
    expect((modal('confirm-enable-ai-bot-btn') as HTMLButtonElement).disabled).toBe(false)
    ;(modal('confirm-enable-ai-bot-btn') as HTMLButtonElement).click()
    await flushPromises()
    const post = calls.find(
      (c) => c.method === 'POST' && c.path === '/api/telegram/ai-bots/codex/control/enable',
    )
    expect(post).toBeDefined()
    expect(post!.body).toEqual(expect.objectContaining({ revision: 5, ack_old_bot_cleared: true }))
    await b.done()
  })

  it('409 bot_in_use：显示“此 Bot Token 已被其他槽位占用”', async () => {
    const { fake } = tgFake({
      enable: () =>
        new Response(JSON.stringify({ code: 'bot_in_use', detail: 'x' }), {
          status: 409,
          headers: { 'content-type': 'application/json' },
        }),
    })
    const b = await openTelegram(fake.fetch)
    await b.wrapper.get('[data-testid=ai-bot-switch-codex]').trigger('click')
    await flushPromises()
    ;(modal('ack-old-cleared-checkbox') as HTMLInputElement).click()
    await flushPromises()
    ;(modal('confirm-enable-ai-bot-btn') as HTMLButtonElement).click()
    await flushPromises()
    expect(modal('enable-error-banner')?.textContent ?? '').toContain(
      '此 Bot Token 已被其他槽位占用',
    )
    await b.done()
  })

  it('telegram.status 只更新 slot 匹配的 AI 卡片；主槽位事件不改变 AI 卡片', async () => {
    const { fake } = tgFake()
    const b = await openTelegram(fake.fetch)
    const codexBefore = b.wrapper.get('[data-testid=ai-bot-card-codex]').text()
    const claudeBefore = b.wrapper.get('[data-testid=ai-bot-card-claude_code]').text()
    pushAi(b.sock, 'telegram.status', {
      state: 'polling',
      since: '2026-10-24T02:00:00Z',
      slot: 'main',
      last_error_category: null,
    })
    await flushPromises()
    expect(b.wrapper.get('[data-testid=ai-bot-card-codex]').text()).toBe(codexBefore)
    expect(b.wrapper.get('[data-testid=ai-bot-card-claude_code]').text()).toBe(claudeBefore)
    pushAi(b.sock, 'telegram.status', {
      state: 'conflict',
      since: '2026-10-24T02:00:01Z',
      slot: 'ai:codex',
      last_error_category: 'conflict_409',
    })
    await flushPromises()
    expect(b.wrapper.get('[data-testid=ai-bot-card-codex]').text()).not.toBe(codexBefore)
    expect(b.wrapper.get('[data-testid=ai-bot-card-claude_code]').text()).toBe(claudeBefore)
    await b.done()
  })

  it('Token 保存后不出现在 DOM、localStorage、sessionStorage、URL 与 console 中', async () => {
    const logged: unknown[] = []
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation((...a: unknown[]) => void logged.push(a)),
    )
    const { fake, calls } = tgFake()
    fake.handlers.push(async (c) =>
      c.path === '/api/telegram/ai-bots/codex/token' && c.method === 'PUT'
        ? json({ ok: true, revision: 6 })
        : undefined,
    )
    const b = await openTelegram(fake.fetch)
    await b.wrapper.get('[data-testid=ai-bot-token-input-codex]').setValue(TOKEN)
    await b.wrapper.get('[data-testid=save-ai-bot-token-btn-codex]').trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.method === 'PUT' && c.body?.token === TOKEN)).toBe(true)
    const stores = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })
    expect(document.body.innerHTML).not.toContain(TOKEN)
    expect(stores).not.toContain(TOKEN)
    expect(window.location.href).not.toContain(TOKEN)
    expect(JSON.stringify(logged)).not.toContain(TOKEN)
    spies.forEach((s) => s.mockRestore())
    await b.done()
  })
})

describe('S5D2 后端离线与 items 缺失：不出现 R1 示例文本', () => {
  const SAMPLES = [
    '#48213',
    '权限缓存未刷新',
    '+2 −1',
    'CSV 中文文件名乱码',
    'admin-console',
    'api-gateway',
    'mobile-bff',
    'config/gateway.yaml',
    'opus · high',
    '116k / 200k',
    'gpt · medium',
  ]

  it('/ai 页后端离线（未收到 hello）时不显示任何示例会话文本', async () => {
    const fake = createFake()
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    await flushPromises()
    const text = b.wrapper.text()
    for (const s of SAMPLES) expect(text).not.toContain(s)
    await b.done()
  })

  it('GET /api/ai/sessions 缺少 items 字段时，列表为空且不显示示例文本', async () => {
    const fx = new FakeAi([], {})
    const fetchImpl = (async (req: Request) => {
      if (new URL(req.url).pathname === '/api/ai/sessions') return fxJson({})
      return fx.fetch(req)
    }) as unknown as typeof fetch
    const b = await boot({ path: '/ai', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(b.wrapper.findAll('[data-testid^=session-]')).toHaveLength(0)
    const text = b.wrapper.text()
    for (const s of SAMPLES) expect(text).not.toContain(s)
    await b.done()
  })
})
