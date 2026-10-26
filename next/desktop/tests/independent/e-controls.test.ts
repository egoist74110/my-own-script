// 方向 B 交互控件（独立编写）：审批条 Y/A/N、⌘K 搜索、Tabs 键盘、检查器收起、导航禁用项、路由。
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ApprovalBar from '@/components/ApprovalBar.vue'
import SearchField from '@/components/SearchField.vue'
import { boot, openConnection } from '../unit/boot'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'

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
  ts = new Date().toISOString(),
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

const press = (key: string, init: KeyboardEventInit = {}, target: EventTarget = window) =>
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }),
  )

describe('审批条 ApprovalBar：Y / A / N 快捷键', () => {
  it.each([
    ['y', 'once'],
    ['Y', 'once'],
    ['a', 'always'],
    ['A', 'always'],
    ['n', 'deny'],
    ['N', 'deny'],
  ])('按 %s 发出 %s', (key, decision) => {
    const w = mount(ApprovalBar, { props: { command: 'pnpm test' }, attachTo: document.body })
    press(key)
    expect(w.emitted('decide')).toEqual([[decision]])
    w.unmount()
  })

  it('按钮与快捷键发出相同的决定，且按钮文字含对应快捷键字母', () => {
    const w = mount(ApprovalBar, { props: { command: 'x' }, attachTo: document.body })
    w.get('[data-act=once]').trigger('click')
    w.get('[data-act=always]').trigger('click')
    w.get('[data-act=deny]').trigger('click')
    expect(w.emitted('decide')).toEqual([['once'], ['always'], ['deny']])
    expect(w.get('[data-act=once]').text()).toContain('Y')
    expect(w.get('[data-act=always]').text()).toContain('A')
    expect(w.get('[data-act=deny]').text()).toContain('N')
    w.unmount()
  })

  it('无关按键（回车、空格、k、yy 组合键名）不发出', () => {
    const w = mount(ApprovalBar, { props: { command: 'x' }, attachTo: document.body })
    for (const k of ['Enter', ' ', 'k', 'Escape', 'Yes', 'y ']) press(k)
    expect(w.emitted('decide')).toBeUndefined()
    w.unmount()
  })

  it('处理过的快捷键 preventDefault；忽略的按键不 preventDefault', () => {
    const w = mount(ApprovalBar, { props: { command: 'x' }, attachTo: document.body })
    const handled = new KeyboardEvent('keydown', { key: 'y', cancelable: true })
    window.dispatchEvent(handled)
    expect(handled.defaultPrevented).toBe(true)
    const ignored = new KeyboardEvent('keydown', { key: 'q', cancelable: true })
    window.dispatchEvent(ignored)
    expect(ignored.defaultPrevented).toBe(false)
    w.unmount()
  })

  it.each([
    ['Ctrl', { ctrlKey: true }],
    ['Meta', { metaKey: true }],
    ['Alt', { altKey: true }],
  ])('%s+Y 不触发', (_name, mod) => {
    const w = mount(ApprovalBar, { props: { command: 'x' }, attachTo: document.body })
    press('y', mod)
    press('n', mod)
    expect(w.emitted('decide')).toBeUndefined()
    w.unmount()
  })

  it.each([
    ['input', () => document.createElement('input')],
    ['textarea', () => document.createElement('textarea')],
    ['select', () => document.createElement('select')],
  ])('焦点在 %s 时不触发，且不 preventDefault（文字可正常输入）', (_t, make) => {
    const w = mount(ApprovalBar, { props: { command: 'x' }, attachTo: document.body })
    const el = make()
    document.body.appendChild(el)
    el.focus()
    expect(document.activeElement).toBe(el)
    const ev = new KeyboardEvent('keydown', { key: 'y', bubbles: true, cancelable: true })
    el.dispatchEvent(ev)
    expect(w.emitted('decide')).toBeUndefined()
    expect(ev.defaultPrevented).toBe(false)
    w.unmount()
  })

  it('焦点在 contenteditable 时不触发（jsdom 不实现 isContentEditable，此处按浏览器语义补齐）', () => {
    const w = mount(ApprovalBar, { props: { command: 'x' }, attachTo: document.body })
    const div = document.createElement('div')
    div.contentEditable = 'true'
    Object.defineProperty(div, 'isContentEditable', { value: true })
    document.body.appendChild(div)
    div.focus()
    div.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true, cancelable: true }))
    expect(w.emitted('decide')).toBeUndefined()
    w.unmount()
  })

  it('焦点在按钮上（非文本输入）时快捷键仍生效', () => {
    const w = mount(ApprovalBar, { props: { command: 'x' }, attachTo: document.body })
    const btn = w.get('[data-act=deny]').element as HTMLElement
    btn.focus()
    press('y')
    expect(w.emitted('decide')).toEqual([['once']])
    w.unmount()
  })

  it('卸载后不再监听快捷键', () => {
    const w = mount(ApprovalBar, { props: { command: 'x' }, attachTo: document.body })
    w.unmount()
    press('y')
    press('a')
    press('n')
    expect(w.emitted('decide')).toBeUndefined()
  })
})

describe('/ai 页审批集成', () => {
  // S5D2 迁移：审批/状态由假后端驱动；断言 POST 请求体与 WS 推送后的展示，不断言本地 mock 记录
  const fixture = () =>
    new FakeAi(
      [
        fxSession({ id: 's1', state: 'awaiting_approval', pending_approval: true, last_seq: 2 }),
        fxSession({ id: 's2', cli: 'codex', state: 'idle', last_seq: 0 }),
      ],
      {
        s1: [fxEvent('s1', 1, 'assistant', { text: '准备运行测试' }), fxApprovalPending('s1', 2)],
        s2: [],
      },
    )
  async function openAi(fake = fixture()) {
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    for (let i = 0; i < 3; i++) await flushPromises()
    return { ...b, fake }
  }
  const focusChat = (w: { get: (s: string) => { element: Element } }) =>
    (w.get('[data-testid=chat-view]').element as HTMLElement).focus()

  it('按 Y：发出 allow_once，审批卡消失；后端推送 busy 后列表显示运行中', async () => {
    const b = await openAi()
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(true)
    focusChat(b.wrapper)
    press('y')
    await flushPromises()
    const posts = b.fake.posts('/approvals/ap-1')
    expect(posts).toHaveLength(1)
    expect(posts[0]!.body).toEqual({ decision: 'allow_once' })
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(false)
    pushAi(b.sock, 'ai.session', {
      session_id: 's1',
      state: 'busy',
      ended_reason: null,
      last_seq: 3,
    })
    await flushPromises()
    expect(b.wrapper.get('[data-testid=session-s1]').text()).toContain('运行中')
    await b.done()
  })

  it('按 N：发出 deny；按 A：发出 allow_session', async () => {
    const deny = await openAi()
    focusChat(deny.wrapper)
    press('N')
    await flushPromises()
    expect(deny.fake.posts('/approvals/ap-1')[0]!.body).toEqual({ decision: 'deny' })
    await deny.done()

    const always = await openAi()
    focusChat(always.wrapper)
    press('a')
    await flushPromises()
    expect(always.fake.posts('/approvals/ap-1')[0]!.body).toEqual({ decision: 'allow_session' })
    await always.done()
  })

  it('同一步内连按两次 Y 只发出一次决定', async () => {
    const b = await openAi()
    focusChat(b.wrapper)
    press('y')
    press('y')
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')).toHaveLength(1)
    press('y')
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')).toHaveLength(1)
    await b.done()
  })

  it('切到其他会话后按 Y 不发出请求（审批已不属于当前会话）', async () => {
    const b = await openAi()
    focusChat(b.wrapper)
    await b.wrapper.get('[data-testid=session-s2]').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(false)
    press('y')
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')).toHaveLength(0)
    await b.done()
  })

  it('输入框（多行消息框）聚焦时按 Y 只是打字，不发出审批', async () => {
    const b = await openAi()
    const ta = b.wrapper.get('[data-testid=composer-textarea]')
    ;(ta.element as HTMLTextAreaElement).focus()
    await ta.trigger('keydown', { key: 'y' })
    await ta.setValue('y')
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')).toHaveLength(0)
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(true)
    await b.done()
  })

  it('离开 /ai 页后按 Y 不报错、不影响其他页面', async () => {
    const b = await boot({ path: '/ai' })
    await b.router.push('/tasks')
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe('/tasks'))
    await flushPromises()
    expect(() => press('y')).not.toThrow()
    await flushPromises()
    expect(b.wrapper.find('[data-testid=tasks-page]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    await b.done()
  })
})

describe('⌘K 搜索框 SearchField', () => {
  const mountSearch = () =>
    mount(SearchField, {
      props: { label: '搜索', modelValue: '', 'onUpdate:modelValue': () => {} },
      attachTo: document.body,
    })

  it('⌘K（meta）与 Ctrl+K 聚焦 input', () => {
    const w = mountSearch()
    const input = w.get('input').element
    press('k', { metaKey: true })
    expect(document.activeElement).toBe(input)
    ;(input as HTMLInputElement).blur()
    press('K', { ctrlKey: true })
    expect(document.activeElement).toBe(input)
    w.unmount()
  })

  it('单独按 k（无修饰键）不聚焦', () => {
    const w = mountSearch()
    press('k')
    expect(document.activeElement).not.toBe(w.get('input').element)
    w.unmount()
  })

  it('⌘K 触发时阻止默认行为', () => {
    const w = mountSearch()
    const ev = new KeyboardEvent('keydown', {
      key: 'k',
      metaKey: true,
      cancelable: true,
      bubbles: true,
    })
    window.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
    w.unmount()
  })

  it('Esc 在输入框内失焦', async () => {
    const w = mountSearch()
    const input = w.get('input')
    press('k', { metaKey: true })
    await input.trigger('keydown', { key: 'Escape' })
    expect(document.activeElement).not.toBe(input.element)
    w.unmount()
  })

  it('卸载后 ⌘K 不再聚焦', () => {
    const w = mountSearch()
    const input = w.get('input').element
    w.unmount()
    press('k', { metaKey: true })
    expect(document.activeElement).not.toBe(input)
  })

  it.each(['/work-items', '/ai'])('%s 页 ⌘K 可聚焦搜索输入框', async (path) => {
    const b = await boot({ path })
    const search = b.wrapper.find('input[type=search]')
    expect(search.exists(), `${path} 没有搜索框（SearchField）`).toBe(true)
    press('k', { metaKey: true })
    await flushPromises()
    expect(document.activeElement).toBe(search.element)
    await b.done()
  })
})

describe('Tabs（Reka）：点击与键盘', () => {
  const tabs = (b: Awaited<ReturnType<typeof boot>>) =>
    b.wrapper.findAll('[role=tablist] [role=tab]')
  const activeLabel = (b: Awaited<ReturnType<typeof boot>>) =>
    b.wrapper.get('[role=tab][data-state=active]').text()
  it('工单页看板列 Tabs 为 tablist/tab，初始「开发中」激活', async () => {
    const b = await boot({ path: '/work-items' })
    await flushPromises()
    expect(tabs(b).map((t) => t.text().replace(/\s+/g, ' '))).toEqual([
      '新建',
      '待开发',
      '开发中',
      '测试',
      '已关闭',
    ])
    expect(activeLabel(b)).toBe('开发中')
    await b.done()
  })

  it('点击切换看板列页签', async () => {
    const b = await boot({ path: '/work-items' })
    await flushPromises()
    await tabs(b)[3]!.trigger('mousedown', { button: 0 })
    await tabs(b)[3]!.trigger('click')
    await flushPromises()
    expect(activeLabel(b)).toBe('测试')
    await b.done()
  })

  it('ArrowRight / ArrowLeft（环绕）/ End / Home 键盘切换看板列', async () => {
    const b = await boot({ path: '/work-items' })
    await flushPromises()
    ;(tabs(b)[2]!.element as HTMLElement).focus()
    await tabs(b)[2]!.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(activeLabel(b)).toBe('测试')
    await tabs(b)[3]!.trigger('keydown', { key: 'End' })
    await flushPromises()
    expect(activeLabel(b)).toBe('已关闭')
    await tabs(b)[4]!.trigger('keydown', { key: 'Home' })
    await flushPromises()
    expect(activeLabel(b)).toBe('新建')
    await tabs(b)[0]!.trigger('keydown', { key: 'ArrowLeft' })
    await flushPromises()
    expect(activeLabel(b)).toBe('已关闭')
    await b.done()
  })

  it('AI 页筛选 Tabs 键盘切换会改变会话列表', async () => {
    // S5D2 迁移：会话列表由假后端 GET /api/ai/sessions 提供（claude s1/s3，codex s2）
    const fake = new FakeAi(
      [
        fxSession({ id: 's1', cli: 'claude', state: 'idle' }),
        fxSession({ id: 's2', cli: 'codex', state: 'idle' }),
        fxSession({ id: 's3', cli: 'claude', state: 'idle' }),
      ],
      { s1: [], s2: [], s3: [] },
    )
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    const ai = b.wrapper.findAll('[role=tablist] [role=tab]')
    expect(ai.map((t) => t.text())).toEqual(['全部', 'Claude', 'Codex', 'agy'])
    expect(b.wrapper.findAll('[data-testid^=session-]')).toHaveLength(3)
    ;(ai[0]!.element as HTMLElement).focus()
    await ai[0]!.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(
      b.wrapper.findAll('[data-testid^=session-]').map((e) => e.attributes('data-testid')),
    ).toEqual(['session-s1', 'session-s3'])
    await b.done()
  })
})

describe('检查器收起 / 展开', () => {
  it('按钮 aria-label 与 aria-pressed 随状态变化；收起后内容仍在 DOM 但容器隐藏', async () => {
    localStorage.clear()
    // S5D2 迁移：检查器内容只在选中终端会话时出现（ai-terminal-inspector），用终端会话夹具验证“收起后仍在 DOM”
    const fake = new FakeAi(
      [fxSession({ id: 'term1', kind: 'terminal', cli: 'claude', state: 'idle' })],
      {
        term1: [],
      },
    )
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await b.wrapper.get('[data-testid=session-term1]').trigger('click')
    await flushPromises()
    const toggle = () => b.wrapper.get('[data-testid=inspector-toggle]')
    const panel = () => b.wrapper.get('[data-testid=inspector]').element as HTMLElement
    expect(toggle().attributes('aria-label')).toBe('收起检查器')
    expect(toggle().attributes('aria-pressed')).toBe('true')
    expect(panel().style.display).not.toBe('none')

    await toggle().trigger('click')
    await flushPromises()
    expect(toggle().attributes('aria-label')).toBe('展开检查器')
    expect(toggle().attributes('aria-pressed')).toBe('false')
    expect(panel().style.display).toBe('none')
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-inspector')).toBe('closed')
    expect(b.wrapper.find('[data-testid=ai-terminal-inspector]').exists()).toBe(true)

    await toggle().trigger('click')
    await flushPromises()
    expect(toggle().attributes('aria-label')).toBe('收起检查器')
    expect(panel().style.display).not.toBe('none')
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-inspector')).toBe('open')
    await b.done()
  })

  it('收起状态跨页面保持；在 /work-items 页仍收起，检查器内容也仍在 DOM', async () => {
    localStorage.clear()
    const b = await boot({ path: '/ai' })
    await b.wrapper.get('[data-testid=inspector-toggle]').trigger('click')
    await flushPromises()
    await b.router.push('/work-items')
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe('/work-items'))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-inspector')).toBe('closed')
    expect(b.wrapper.get('[data-testid=inspector-toggle]').attributes('aria-label')).toBe(
      '展开检查器',
    )
    expect(b.wrapper.find('[data-testid=wi-ai]').exists()).toBe(true)
    await b.wrapper.get('[data-testid=inspector-toggle]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-inspector')).toBe('open')
    await b.done()
  })

  it('无检查器内容的页面（任务占位）不显示检查器栏', async () => {
    localStorage.clear()
    const b = await boot()
    expect((b.wrapper.get('[data-testid=inspector]').element as HTMLElement).style.display).toBe(
      'none',
    )
    await b.done()
  })
})

describe('导航与路由', () => {
  it('禁用导航项：aria-disabled、title 说明尚未提供、不在 Tab 顺序中、无链接', async () => {
    const b = await boot()
    const off = b.wrapper.findAll('[aria-disabled=true]')
    expect(off.map((o) => o.text())).toEqual(['MCP', '服务', 'VPN'])
    for (const o of off) {
      expect(o.attributes('title')).toBe('尚未提供')
      expect(o.element.tagName).not.toBe('A')
      expect(o.attributes('href')).toBeUndefined()
      expect(o.attributes('tabindex')).toBeUndefined()
      expect((o.element as HTMLElement).tabIndex).toBe(-1)
    }
    await b.done()
  })

  it('/ 重定向到 /tasks；未知路径重定向到 /tasks', async () => {
    const root = await boot({ path: '/' })
    expect(root.router.currentRoute.value.path).toBe('/tasks')
    await root.done()

    const unknown = await boot({ path: '/no/such/page' })
    await flushPromises()
    expect(unknown.router.currentRoute.value.path).toBe('/tasks')
    await unknown.done()
  })

  it('当前路由的导航项带 aria-current=page，且标签切换', async () => {
    const b = await boot({ path: '/work-items' })
    await vi.waitFor(() => expect(b.wrapper.find('nav a[aria-current=page]').exists()).toBe(true))
    expect(b.wrapper.get('nav a[aria-current=page]').attributes('href')).toBe('/work-items')
    await b.done()
  })
})

describe('按钮与图标可访问名称（抽查）', () => {
  it.each(['/work-items', '/ai'])('%s 页图标按钮都有 aria-label；告警开关有名称', async (path) => {
    const b = await boot({ path })
    for (const btn of b.wrapper.findAll('.tb')) {
      expect(btn.attributes('aria-label'), btn.html()).toBeTruthy()
    }
    await openConnection(b)
    expect(b.wrapper.get('[role=switch]').attributes('aria-label')).toBe('告警演示开关')
    await b.done()
  })
})
