// 方向 B 交互控件（独立编写）：审批条 Y/A/N、⌘K 搜索、Tabs 键盘、检查器收起、导航禁用项、路由。
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ApprovalBar from '@/components/ApprovalBar.vue'
import SearchField from '@/components/SearchField.vue'
import { boot, openConnection } from '../unit/boot'
import { FakeSocket, resetSeq } from '../unit/helpers'

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
  it('按 Y：审批条消失，出现决定记录，会话变「运行中」', async () => {
    const b = await boot({ path: '/ai' })
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(true)
    press('y')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    const log = b.wrapper.get('[data-testid=decision-log]')
    expect(log.attributes('data-decision')).toBe('once')
    expect(log.text()).toContain('已允许一次')
    expect(log.text()).toContain('pnpm vitest run')
    expect(b.wrapper.get('[data-testid=session-s1]').text()).toContain('运行中')
    await b.done()
  })

  it('按 N：会话变「已拒绝」；按 A：记录「本会话总是允许」', async () => {
    const deny = await boot({ path: '/ai' })
    press('N')
    await flushPromises()
    expect(deny.wrapper.get('[data-testid=decision-log]').attributes('data-decision')).toBe('deny')
    expect(deny.wrapper.get('[data-testid=session-s1]').text()).toContain('已拒绝')
    await deny.done()

    const always = await boot({ path: '/ai' })
    press('a')
    await flushPromises()
    expect(always.wrapper.get('[data-testid=decision-log]').text()).toContain('本会话总是允许')
    await always.done()
  })

  it('同一步内连按两次 Y 只记录一次决定', async () => {
    const b = await boot({ path: '/ai' })
    press('y')
    press('y')
    await flushPromises()
    expect(b.wrapper.findAll('[data-testid=decision-log]')).toHaveLength(1)
    press('y')
    await flushPromises()
    expect(b.wrapper.findAll('[data-testid=decision-log]')).toHaveLength(1)
    await b.done()
  })

  it('切到其他会话后按 Y 不触发（审批条已不在页面）', async () => {
    const b = await boot({ path: '/ai' })
    await b.wrapper.get('[data-testid=session-s2]').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    press('y')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(false)
    await b.done()
  })

  it('输入框（多行消息框）聚焦时按 Y 只是打字，不做决定', async () => {
    const b = await boot({ path: '/ai' })
    const ta = b.wrapper.get('textarea')
    ;(ta.element as HTMLTextAreaElement).focus()
    await ta.trigger('keydown', { key: 'y' })
    await ta.setValue('y')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(true)
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
    const b = await boot({ path: '/ai' })
    await flushPromises()
    const ai = b.wrapper.findAll('[role=tablist] [role=tab]')
    expect(ai.map((t) => t.text())).toEqual(['全部', 'Claude', 'Codex', 'agy'])
    ;(ai[0]!.element as HTMLElement).focus()
    await ai[0]!.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(b.wrapper.findAll('[data-testid^=session-]')).toHaveLength(3)
    await b.done()
  })
})

describe('检查器收起 / 展开', () => {
  it('按钮 aria-label 与 aria-pressed 随状态变化；收起后内容仍在 DOM 但容器隐藏', async () => {
    localStorage.clear()
    const b = await boot({ path: '/ai' })
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
    expect(b.wrapper.find('[data-testid=ai-inspector]').exists()).toBe(true)

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
