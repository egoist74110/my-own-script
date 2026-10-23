// S1-C 独立边界/故障用例（independent=true）：SegmentedControl 键盘与多实例、告警开关故障态与可达性、AI 会话隔离。
// 只用假 fetch / 假 socket；fixtures 复用 tests/unit/boot.ts 与 tests/unit/helpers.ts。
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import { tabTriggerId } from '@/components/tabs'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'
import { boot, bootUnconnected, json, openConnection } from '../unit/boot'

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
})

const items = [
  { value: 'a', label: '甲' },
  { value: 'b', label: '乙' },
  { value: 'c', label: '丙' },
]

function mountTabs(opts: { label?: string; withSlot?: boolean; initial?: string } = {}) {
  const model = ref(opts.initial ?? 'a')
  const slot =
    opts.withSlot === false ? '' : `<template #default="{ item }">内容-{{ item.value }}</template>`
  const w = mount(
    {
      components: { SegmentedControl },
      setup: () => ({ model, items, label: opts.label ?? '视图' }),
      template: `<SegmentedControl v-model="model" :label="label" :items="items">${slot}</SegmentedControl>`,
    },
    { attachTo: document.body },
  )
  return { w, model }
}

/** 断言：每个 tab 的 aria-controls 指向唯一存在的 tabpanel，且 panel.aria-labelledby 指回该 tab。 */
function expectPairing(w: ReturnType<typeof mountTabs>['w']) {
  const tabs = w.findAll('[role=tab]')
  const panels = w.findAll('[role=tabpanel]')
  expect(tabs.length).toBe(panels.length)
  tabs.forEach((t) => {
    const id = t.attributes('aria-controls')
    expect(id, 'tab 必须有 aria-controls').toBeTruthy()
    const panel = document.getElementById(id!)
    expect(panel?.getAttribute('role')).toBe('tabpanel')
    expect(panel?.getAttribute('aria-labelledby')).toBe(t.attributes('id'))
  })
}

describe('SegmentedControl 键盘与关联（独立）', () => {
  it('方向键切换后，选中态与可见面板随之更新，tabpanel 关联保持一致', async () => {
    const { w, model } = mountTabs()
    await flushPromises()
    const first = w.findAll('[role=tab]')[0]!
    ;(first.element as HTMLElement).focus()
    await first.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(model.value).toBe('b')
    expectPairing(w)
    const visible = w.findAll('[role=tabpanel]').filter((p) => !p.element.hasAttribute('hidden'))
    expect(visible).toHaveLength(1)
    expect(visible[0]!.text()).toBe('内容-b')
    // 被选中页签的 panel 应可聚焦（有插槽时 tabindex=0）
    const selectedPanel = document.getElementById(
      w.findAll('[role=tab]')[1]!.attributes('aria-controls')!,
    )
    expect(selectedPanel!.getAttribute('tabindex')).toBe('0')
    w.unmount()
  })

  it('panelId 用法：方向键更新 modelValue；当前页签 aria-controls 指向可见 tabpanel 且含当前内容', async () => {
    const model = ref('a')
    const w = mount(
      {
        components: { SegmentedControl },
        setup: () => ({ model, items, tabTriggerId }),
        template: `<div><SegmentedControl v-model="model" label="视图" :items="items" panel-id="pp" />
          <div id="pp" role="tabpanel" :aria-labelledby="tabTriggerId('pp', model)">内容-{{ model }}</div></div>`,
      },
      { attachTo: document.body },
    )
    await flushPromises()
    ;(w.findAll('[role=tab]')[0]!.element as HTMLElement).focus()
    await w.findAll('[role=tab]')[0]!.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(model.value).toBe('b')
    expect(w.findAll('[role=tabpanel]')).toHaveLength(1)
    const current = w.get('[role=tab][aria-selected=true]')
    const panel = document.getElementById(current.attributes('aria-controls')!)!
    expect(panel.hasAttribute('hidden')).toBe(false)
    expect(panel.textContent).toBe('内容-b')
    expect(panel.getAttribute('aria-labelledby')).toBe(current.attributes('id'))
    w.unmount()
  })

  it('同一应用内多个 SegmentedControl（工单页即如此）：所有 id 唯一，各自关联不串线', async () => {
    const m1 = ref('a')
    const m2 = ref('c')
    const w = mount(
      {
        components: { SegmentedControl },
        setup: () => ({ m1, m2, items }),
        template: `<div><SegmentedControl v-model="m1" label="甲组" :items="items"><template #default="{ item }">内容-{{ item.value }}</template></SegmentedControl><SegmentedControl v-model="m2" label="乙组" :items="items"><template #default="{ item }">内容-{{ item.value }}</template></SegmentedControl></div>`,
      },
      { attachTo: document.body },
    )
    await flushPromises()
    const ids = Array.from(document.querySelectorAll('[id]')).map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    const groups = w.findAllComponents(SegmentedControl)
    expect(groups).toHaveLength(2)
    for (const g of groups) expectPairing(g as unknown as ReturnType<typeof mountTabs>['w'])
    // 改动第二组不影响第一组的选中与可见面板
    await w.findAll('[role=tab]')[3]!.trigger('mousedown')
    await flushPromises()
    expect(m1.value).toBe('a')
    expect(m2.value).toBe('a')
    const firstGroupVisible = w
      .findAll('[role=tabpanel]')
      .slice(0, 3)
      .filter((p) => !p.element.hasAttribute('hidden'))
    expect(firstGroupVisible.map((p) => p.text())).toEqual(['内容-a'])
    w.unmount()
  })

  it('工单页（含两组 SegmentedControl）：文档内所有 id 唯一，aria-controls/aria-labelledby 都能解析', async () => {
    const b = await boot({ path: '/work-items' })
    await flushPromises()
    const ids = Array.from(document.querySelectorAll('[id]')).map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const el of b.wrapper.findAll('[aria-labelledby]')) {
      expect(document.getElementById(el.attributes('aria-labelledby')!)).not.toBeNull()
    }
    await b.done()
  })
})

/** 可手动决定何时结束的 fetch，用于观察 pending 态。 */
function deferredAlertFetch() {
  const calls: { url: string; method: string; body: unknown }[] = []
  let release: ((r: Response) => void) | null = null
  const fetchImpl = (async (req: Request) => {
    if (req.url.endsWith('/health')) {
      return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
    }
    calls.push({
      url: req.url,
      method: req.method,
      body: await req
        .clone()
        .json()
        .catch(() => null),
    })
    return new Promise<Response>((res) => {
      release = res
    })
  }) as unknown as typeof fetch
  return { fetchImpl, calls, resolve: (r: Response) => release?.(r) }
}

describe('告警开关故障态与可达性（独立）', () => {
  it('请求在途时开关为 disabled，重复点击不再发第二个请求', async () => {
    const f = deferredAlertFetch()
    const b = await boot({ fetchImpl: f.fetchImpl })
    await openConnection(b)
    await flushPromises()
    const sw = b.wrapper.get('[role=switch]')
    await sw.trigger('click')
    await flushPromises()
    expect(f.calls).toHaveLength(1)
    expect(b.wrapper.get('[role=switch]').attributes('disabled')).toBeDefined()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(f.calls).toHaveLength(1)
    f.resolve(new Response(null, { status: 200 }))
    await flushPromises()
    expect(b.wrapper.get('[role=switch]').attributes('disabled')).toBeUndefined()
    await b.done()
  })

  it('请求体：开启发送 active=true + 演示原因；关闭发送 active=false 且 reason=null', async () => {
    const f = deferredAlertFetch()
    const b = await boot({ fetchImpl: f.fetchImpl })
    await openConnection(b)
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(f.calls[0]!.url).toMatch(/\/api\/system\/alert$/)
    expect(f.calls[0]!.method).toBe('POST')
    expect(f.calls[0]!.body).toEqual({ active: true, reason: 'S0 DEMO ALERT' })
    f.resolve(new Response(null, { status: 200 }))
    await flushPromises()
    await b.done()
  })

  it('服务端返回 503：显示 请求失败 (503)，开关恢复可点', async () => {
    let n = 0
    const fetchImpl = (async (req: Request) => {
      if (req.url.endsWith('/health'))
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      n++
      return new Response('{"detail":"down"}', {
        status: 503,
        headers: { 'content-type': 'application/json' },
      })
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    await openConnection(b)
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(n).toBe(1)
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('请求失败 (503)')
    expect(b.wrapper.get('[role=switch]').attributes('disabled')).toBeUndefined()
    await b.done()
  })

  it('网络异常（fetch reject）：显示 请求失败（网络）', async () => {
    const fetchImpl = (async (req: Request) => {
      if (req.url.endsWith('/health'))
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      throw new TypeError('network down')
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    await openConnection(b)
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('请求失败（网络）')
    await b.done()
  })

  it('错误后再次成功：错误文案被清除', async () => {
    let n = 0
    const fetchImpl = (async (req: Request) => {
      if (req.url.endsWith('/health'))
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      n++
      if (n === 1) throw new TypeError('flaky')
      return new Response(null, { status: 200 })
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    await openConnection(b)
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-error]').exists()).toBe(true)
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-error]').exists()).toBe(false)
    expect(n).toBe(2)
    await b.done()
  })

  it('未连接时点击 → 连接建立后再点击：发出请求并清除“后端未连接”', async () => {
    const b = await bootUnconnected()
    await openConnection(b)
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('后端未连接')
    expect(b.fetchMock).not.toHaveBeenCalled()
    b.runtime.start()
    await flushPromises()
    FakeSocket.last().open()
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.fetchMock).toHaveBeenCalled()
    expect(b.wrapper.find('[data-testid=alert-error]').exists()).toBe(false)
    await b.done()
  })

  it('label 与开关关联：点击“告警演示”文字同样触发开关请求', async () => {
    const f = deferredAlertFetch()
    const b = await boot({ fetchImpl: f.fetchImpl })
    await openConnection(b)
    await flushPromises()
    const label = b.wrapper.get('label[for=alert-demo]')
    const switchId = b.wrapper.get('[role=switch]').attributes('id')
    expect(label.attributes('for')).toBe('alert-demo')
    expect(switchId).toBe('alert-demo')
    await label.trigger('click')
    await flushPromises()
    expect(f.calls).toHaveLength(1)
    f.resolve(new Response(null, { status: 200 }))
    await flushPromises()
    await b.done()
  })
})

const press = (key: string) =>
  window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))

describe('AI 会话隔离（独立）', () => {
  // S5D2 迁移：会话、事件、审批、消息全部由按正式 DTO 构造的假后端提供，断言请求体与真实 DOM
  const fixture = () =>
    new FakeAi(
      [
        fxSession({
          id: 's1',
          cli: 'claude',
          state: 'awaiting_approval',
          pending_approval: true,
          last_seq: 2,
        }),
        fxSession({ id: 's2', cli: 'codex', state: 'idle' }),
        fxSession({ id: 's3', cli: 'claude', state: 'idle' }),
        fxSession({ id: 's5', cli: 'codex', state: 'idle' }),
      ],
      {
        s1: [fxEvent('s1', 1, 'assistant', { text: '准备运行测试' }), fxApprovalPending('s1', 2)],
        s2: [],
        s3: [],
        s5: [],
      },
    )
  async function openAi(fake = fixture()) {
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    for (let i = 0; i < 3; i++) await flushPromises()
    return { ...b, fake }
  }
  type Wrap = Awaited<ReturnType<typeof openAi>>['wrapper']
  const sessBtn = (w: Wrap, id: string) => w.get(`[data-testid=session-${id}]`)
  const focusChat = (w: Wrap) => (w.get('[data-testid=chat-view]').element as HTMLElement).focus()
  const sendText = async (w: Wrap, text: string) => {
    await w.get('[data-testid=composer-textarea]').setValue(text)
    await w.get('[data-testid=composer-textarea]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
  }

  it('纯空白消息不发送，也不产生消息条目', async () => {
    const b = await openAi()
    const before = b.wrapper.findAll('[data-testid=user-message]').length
    await sendText(b.wrapper, '   \n\t ')
    expect(b.fake.posts('/messages')).toHaveLength(0)
    expect(b.wrapper.findAll('[data-testid=user-message]').length).toBe(before)
    await b.done()
  })

  it('发送带首尾空白的消息：请求体中的 text 已 trim', async () => {
    const b = await openAi()
    await sendText(b.wrapper, '  追问内容  ')
    const posts = b.fake.posts('/messages')
    expect(posts).toHaveLength(1)
    expect(posts[0]!.path).toBe('/api/ai/sessions/s1/messages')
    expect(posts[0]!.body.text).toBe('追问内容')
    expect(typeof posts[0]!.body.request_id).toBe('string')
    await b.done()
  })

  it('s1 审批后在 s2/s3 发送，再切回 s1：审批与消息都只属于各自会话', async () => {
    const b = await openAi()
    focusChat(b.wrapper)
    press('a')
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')).toHaveLength(1)
    expect(b.fake.posts('/approvals/ap-1')[0]!.path).toBe('/api/ai/sessions/s1/approvals/ap-1')
    await sessBtn(b.wrapper, 's2').trigger('click')
    await sendText(b.wrapper, '发给 s2')
    await sessBtn(b.wrapper, 's3').trigger('click')
    await sendText(b.wrapper, '发给 s3')
    expect(b.fake.posts('/messages').map((r) => r.path)).toEqual([
      '/api/ai/sessions/s2/messages',
      '/api/ai/sessions/s3/messages',
    ])
    expect(b.fake.posts('/approvals/ap-1')).toHaveLength(1)
    await sessBtn(b.wrapper, 's1').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=chat-flow]').text()).not.toContain('发给 s2')
    expect(b.wrapper.get('[data-testid=chat-flow]').text()).not.toContain('发给 s3')
    await b.done()
  })

  it('N 键拒绝：发出 deny，审批卡消失；后端推送 idle 后列表显示空闲', async () => {
    const b = await openAi()
    focusChat(b.wrapper)
    press('n')
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')[0]!.body).toEqual({ decision: 'deny' })
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(false)
    pushAi(b.sock, 'ai.session', {
      session_id: 's1',
      state: 'idle',
      ended_reason: null,
      last_seq: 3,
    })
    await flushPromises()
    expect(b.wrapper.get('[data-testid=session-s1]').text()).toContain('空闲')
    await b.done()
  })

  it('输入框聚焦时按 Y 不审批（不应误触审批）', async () => {
    const b = await openAi()
    const ta = b.wrapper.get('[data-testid=composer-textarea]').element as HTMLTextAreaElement
    ta.focus()
    ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', bubbles: true }))
    await flushPromises()
    expect(b.fake.posts('/approvals/ap-1')).toHaveLength(0)
    expect(b.wrapper.find('[data-testid=approval-card]').exists()).toBe(true)
    await b.done()
  })

  it('每个会话的工具卡片随会话切换而变化（不残留 s1 的工具）', async () => {
    const fake = new FakeAi(
      [
        fxSession({ id: 's1', state: 'idle' }),
        fxSession({ id: 's2', cli: 'codex', state: 'idle' }),
      ],
      {
        s1: [
          fxEvent('s1', 1, 'turn_started', { text: '改一下' }),
          fxEvent('s1', 2, 'tool_use', { tool: 'Edit', tool_use_id: 't1', summary: 'src/a.ts' }),
          fxEvent('s1', 3, 'turn_completed', {}),
        ],
        s2: [
          fxEvent('s2', 1, 'turn_started', { text: '另一个问题' }),
          fxEvent('s2', 2, 'tool_use', { tool: 'Read', tool_use_id: 't2', summary: 'b.md' }),
          fxEvent('s2', 3, 'turn_completed', {}),
        ],
      },
    )
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(b.wrapper.find('[data-testid=tool-card-t1]').exists()).toBe(true)
    await sessBtn(b.wrapper, 's2').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=tool-card-t2]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid=tool-card-t1]').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=chat-flow]').text()).not.toContain('src/a.ts')
    await b.done()
  })

  it('筛选：按 Codex 过滤后列表只含 Codex 会话', async () => {
    const b = await openAi()
    const codexTab = b.wrapper.findAll('[role=tab]').find((t) => t.text().startsWith('Codex'))!
    await codexTab.trigger('mousedown')
    await flushPromises()
    const ids = b.wrapper.findAll('[data-testid^=session-]').map((e) => e.attributes('data-testid'))
    expect(ids.sort()).toEqual(['session-s2', 'session-s5'])
    await b.done()
  })

  it('特征化：选中的会话被筛选掉后，列表不再高亮它，但对话区仍绑定该会话（待产品确认）', async () => {
    const b = await openAi()
    expect(b.wrapper.get('[data-testid=session-s1]').attributes('data-selected')).toBe('true')
    const codexTab = b.wrapper.findAll('[role=tab]').find((t) => t.text().startsWith('Codex'))!
    await codexTab.trigger('mousedown')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=session-s1]').exists()).toBe(false)
    expect(b.wrapper.findAll('[data-selected=true]')).toHaveLength(0)
    // 对话区仍绑定 s1：其待决审批卡仍在
    expect(b.wrapper.get('[data-testid=approval-card]').text()).toContain('pnpm vitest run')
    await b.done()
  })

  it('搜索无匹配：列表为空，不抛错，对话区仍保留', async () => {
    const b = await openAi()
    await b.wrapper.get('.filters input').setValue('不存在的关键字xyz')
    await flushPromises()
    expect(b.wrapper.findAll('[data-testid^=session-]')).toHaveLength(0)
    expect(b.wrapper.find('[data-testid=chat-view]').exists()).toBe(true)
    await b.done()
  })

  // 主控裁决 S5D2-T02（2026-10-24）：R1 mock 的上下文百分比与改动统计撤销（合同：上下文只在 CLI
  // 提供数据时显示、不估算）；保留原意“检查器内容随会话切换、不残留上一个会话”，按合同右栏字段断言。
  it('每个会话的检查器内容随会话切换而变化（不残留 s1 的数据，不显示估算的上下文百分比）', async () => {
    const fake = new FakeAi(
      [
        fxSession({ id: 's1', state: 'idle', repo: { id: 'repo-1', name: 'my-own-script' } }),
        fxSession({
          id: 's2',
          cli: 'codex',
          state: 'idle',
          repo: { id: 'repo-2', name: 'web-portal' },
        }),
      ],
      {},
    )
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    for (let i = 0; i < 3; i++) await flushPromises()
    let insp = b.wrapper.get('[data-testid=ai-chat-inspector]').text()
    expect(insp).toContain('my-own-script')
    expect(insp).not.toMatch(/\d+%/)
    await sessBtn(b.wrapper, 's2').trigger('click')
    await flushPromises()
    insp = b.wrapper.get('[data-testid=ai-chat-inspector]').text()
    expect(insp).toContain('web-portal')
    expect(insp).not.toContain('my-own-script')
    expect(insp).not.toMatch(/\d+%/)
    await b.done()
  })
})
