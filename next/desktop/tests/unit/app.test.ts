import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSocket, alertEvent, hello, resetSeq, env } from './helpers'
import { boot, json, openConnection } from './boot'

describe('B 方向壳：骨架与连接', () => {
  beforeEach(() => {
    FakeSocket.reset()
    resetSeq()
  })
  afterEach(() => {
    document.body.innerHTML = ''
    vi.useRealTimers()
  })

  it('骨架：通高侧栏 + 主区；没有底部状态栏；侧栏顶部有拖拽区且没有假红绿灯', async () => {
    const b = await boot({ path: '/work-items' })
    const shell = b.wrapper.get('[data-testid=app-shell]')
    expect(shell.find('aside[aria-label=侧栏]').exists()).toBe(true)
    expect(shell.find('main').exists()).toBe(true)
    expect(shell.find('[data-testid=inspector]').exists()).toBe(true)
    expect(shell.find('footer').exists()).toBe(false)
    expect(shell.find('[data-tauri-drag-region]').exists()).toBe(true)
    expect(shell.html()).not.toMatch(/#ff5f57|#febc2e|#28c840/i)
    await b.done()
  })

  it('/ 重定向到 /tasks', async () => {
    const b = await boot()
    expect(b.router.currentRoute.value.path).toBe('/tasks')
    await b.done()
  })

  it('侧栏分组：工作（任务/工单/AI 会话）与基础设施（MCP/服务/VPN 禁用，无切片号）；设置在底部', async () => {
    const b = await boot()
    const groups = b.wrapper.findAll('nav[aria-label=分区] h2').map((h) => h.text())
    expect(groups).toEqual(['工作', '基础设施'])
    const links = b.wrapper.findAll('nav a').map((a) => a.attributes('href'))
    expect(links).toEqual(['/tasks', '/work-items', '/ai', '/settings'])
    const disabled = b.wrapper.findAll('[aria-disabled=true]')
    expect(disabled.map((d) => d.text())).toEqual(['MCP', '服务', 'VPN'])
    for (const d of disabled) {
      expect(d.attributes('title')).toBe('尚未提供')
      expect(d.attributes('tabindex')).toBeUndefined()
      expect(d.text()).not.toMatch(/S\d/)
    }
    expect(b.wrapper.get('nav a[aria-current=page]').text()).toContain('任务')
    // 不做「已保存查询」「Pinned」，也不显示计数角标
    expect(b.wrapper.get('aside[aria-label=侧栏]').text()).not.toMatch(/Pinned|已保存/)
    await b.done()
  })

  it('连接状态行：只显示后端真实状态；弹出层给 pid 与心跳延迟；不显示 VPN/TG/MCP', async () => {
    const b = await boot()
    const conn = () => b.wrapper.get('[data-testid=connection]').text()
    expect(conn()).toContain('连接中')
    b.sock.emit(hello(777))
    await flushPromises()
    expect(conn()).toContain('在线')
    await openConnection(b)
    expect(b.wrapper.get('[data-testid=connection-pid]').text()).toBe('777')
    b.sock.emit(
      env('system.heartbeat', { uptime_s: 5 }, { ts: new Date(Date.now() - 30).toISOString() }),
    )
    await flushPromises()
    expect(b.store.latencyMs).toBeGreaterThanOrEqual(0)
    expect(b.wrapper.get('[data-testid=connection-latency]').text()).toMatch(/ms/)
    const side = b.wrapper.get('aside[aria-label=侧栏]').text()
    expect(side).not.toMatch(/VPN 已|TG|MCP \d/)
    b.sock.drop()
    await flushPromises()
    expect(conn()).toContain('重连中')
    await b.done()
  })

  it('弹出层：Esc 关闭并回到触发按钮；点外部关闭', async () => {
    const b = await boot()
    await openConnection(b)
    const trigger = b.wrapper.get('[data-testid=connection-trigger]')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    await b.wrapper.get('[data-testid=connection-popover]').trigger('keydown', { key: 'Escape' })
    expect(b.wrapper.find('[data-testid=connection-popover]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    await openConnection(b)
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=connection-popover]').exists()).toBe(false)
    await b.done()
  })

  it('弹出层：焦点不在弹出层内时，文档级 Esc 也能关闭，焦点回到触发按钮', async () => {
    const b = await boot()
    await openConnection(b)
    const trigger = b.wrapper.get('[data-testid=connection-trigger]')
    ;(document.activeElement as HTMLElement | null)?.blur()
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=connection-popover]').exists()).toBe(false)
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger.element)
    await b.done()
  })

  it('/health 查询在 online 后显示版本', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
    await openConnection(b)
    await vi.waitFor(() =>
      expect(b.wrapper.get('[data-testid=health-version]').text()).toBe('9.9.9'),
    )
    await b.done()
  })

  it('告警开关只发请求，不本地切换；仅 system.alert 事件改变告警态', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
    await openConnection(b)
    const sw = b.wrapper.get('[role=switch]')
    expect(sw.attributes('aria-checked')).toBe('false')
    await sw.trigger('click')
    await flushPromises()
    const post = b.fetchMock.mock.calls
      .map((c) => c[0] as Request)
      .find((r) => r.method === 'POST')!
    expect(post.url).toBe('http://127.0.0.1:5555/api/system/alert')
    expect(post.headers.get('authorization')).toBe('Bearer fake-token')
    expect(post.url).not.toContain('fake-token')
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    expect(b.wrapper.get('[role=switch]').attributes('aria-checked')).toBe('false')

    b.sock.emit(alertEvent(true, 'S0 DEMO ALERT'))
    await flushPromises()
    expect(b.wrapper.get('[role=switch]').attributes('aria-checked')).toBe('true')
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
    await b.done()
  })

  it('开关请求失败时显示错误且不改变告警态', async () => {
    const failing = vi.fn(async (req: Request) =>
      req.method === 'POST'
        ? new Response('nope', { status: 401 })
        : json({ status: 'ok', version: 'v', pid: 1, uptime_s: 1, alert: false }),
    ) as unknown as typeof fetch
    const b = await boot({ fetchImpl: failing })
    b.sock.emit(hello())
    await flushPromises()
    await openConnection(b)
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toContain('401')
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    await b.done()
  })

  it('告警：横幅显示 reason（无 reason 给默认文案）、连接状态行变橙、无导航角标、工作区无遮罩', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('false')
    b.sock.emit(alertEvent(true, 'disk full'))
    await flushPromises()
    const banner = b.wrapper.get('[data-testid=alert-banner]')
    expect(banner.attributes('role')).toBe('alert')
    expect(banner.text()).toContain('disk full')
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('true')
    expect(b.wrapper.find('[data-testid=nav-alert-badge]').exists()).toBe(false)
    // 无全屏遮罩：壳内没有 fixed/absolute 覆盖层拦截点击
    expect(b.wrapper.find('[data-testid=app-shell] .overlay').exists()).toBe(false)

    b.sock.emit(alertEvent(true, null))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toContain('未提供原因')

    b.sock.emit(alertEvent(false))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('false')
    await b.done()
  })

  it('告警 reason 里的 HTML 作为文本显示', async () => {
    const b = await boot()
    b.sock.emit(hello())
    b.sock.emit(alertEvent(true, '<img src=x onerror=alert(1)>'))
    await flushPromises()
    const el = b.wrapper.get('[data-testid=alert-banner]').element
    expect(el.querySelector('img')).toBeNull()
    expect(el.textContent).toContain('<img src=x onerror=alert(1)>')
    await b.done()
  })

  it('hello 携带的告警态用于对齐；seq 倒退的旧事件被忽略', async () => {
    const b = await boot()
    b.sock.emit(hello(1, { active: true, reason: 'r', changed_at: 't' }))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
    b.sock.emit({ ...alertEvent(false), seq: 0 })
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
    await b.done()
  })

  it('检查器可收起/展开：顶栏按钮 aria-pressed、键盘可达，状态只把布尔值存 localStorage', async () => {
    localStorage.clear()
    const b = await boot({ path: '/ai' })
    const shell = b.wrapper.get('[data-testid=app-shell]')
    const btn = b.wrapper.get('[data-testid=inspector-toggle]')
    expect(btn.element.tagName).toBe('BUTTON')
    expect(btn.attributes('aria-label')).toBe('收起检查器')
    expect(btn.attributes('aria-pressed')).toBe('true')
    expect(shell.attributes('data-inspector')).toBe('open')
    const panel = () => b.wrapper.get('[data-testid=inspector]').element as HTMLElement
    expect(panel().style.display).not.toBe('none')
    await btn.trigger('click')
    expect(shell.attributes('data-inspector')).toBe('closed')
    expect(b.wrapper.get('[data-testid=inspector-toggle]').attributes('aria-label')).toBe(
      '展开检查器',
    )
    expect(b.wrapper.get('[data-testid=inspector-toggle]').attributes('aria-pressed')).toBe('false')
    expect(panel().style.display).toBe('none')
    expect(localStorage.getItem('toolbox.ui.inspector')).toBe('false')
    expect(Object.keys(localStorage)).toEqual(['toolbox.ui.inspector'])
    await b.wrapper.get('[data-testid=inspector-toggle]').trigger('click')
    expect(shell.attributes('data-inspector')).toBe('open')
    expect(localStorage.getItem('toolbox.ui.inspector')).toBe('true')
    await b.done()
  })

  it('没有 HUD 残留：无时钟、无 ∞ 占位、无 WarningBox、根节点无 --denied', async () => {
    const b = await boot()
    b.sock.emit(hello())
    b.sock.emit(alertEvent(true, 'x'))
    await flushPromises()
    const html = b.wrapper.html()
    expect(html).not.toContain('--denied')
    expect(html).not.toContain('infinity-placeholder')
    expect(html).not.toContain('warning-box')
    expect(html).not.toContain('clock-')
    await b.done()
  })
})
