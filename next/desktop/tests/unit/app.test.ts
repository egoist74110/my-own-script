import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSocket, alertEvent, hello, resetSeq, env } from './helpers'
import { boot, json } from './boot'

describe('E 方向壳：骨架与连接', () => {
  beforeEach(() => {
    FakeSocket.reset()
    resetSeq()
  })
  afterEach(() => {
    document.body.innerHTML = ''
    vi.useRealTimers()
  })

  it('网格四区：侧栏、主区、检查器、状态栏；侧栏顶部有拖拽区且没有假红绿灯', async () => {
    const b = await boot()
    const shell = b.wrapper.get('[data-testid=app-shell]')
    expect(shell.find('aside[aria-label=侧栏]').exists()).toBe(true)
    expect(shell.find('main').exists()).toBe(true)
    expect(shell.find('[data-testid=inspector]').exists()).toBe(true)
    expect(shell.find('footer').exists()).toBe(true)
    expect(shell.find('[data-tauri-drag-region]').exists()).toBe(true)
    expect(shell.html()).not.toMatch(/#ff5f57|#febc2e|#28c840/i)
    await b.done()
  })

  it('/ 重定向到 /tasks', async () => {
    const b = await boot()
    expect(b.router.currentRoute.value.path).toBe('/tasks')
    await b.done()
  })

  it('导航：01..08 编号；任务/工单/AI 会话可用，其余禁用并标切片号', async () => {
    const b = await boot()
    const codes = b.wrapper.findAll('nav .item .code').map((c) => c.text())
    expect(codes).toEqual(['01', '02', '03', '04', '05', '06', '07', '08'])
    const links = b.wrapper.findAll('nav a').map((a) => a.attributes('href'))
    expect(links).toEqual(['/tasks', '/work-items', '/ai'])
    const disabled = b.wrapper.findAll('[aria-disabled=true]')
    expect(disabled.map((d) => d.attributes('data-slice'))).toEqual(['S3', 'S6', 'S7', 'S8', 'S1'])
    expect(b.wrapper.get('nav a[aria-current=page]').text()).toContain('任务')
    await b.done()
  })

  it('侧栏底部有 Pinned 区', async () => {
    const b = await boot()
    expect(b.wrapper.get('.pinned').text()).toContain('Pinned')
    expect(b.wrapper.findAll('.pinned a').length).toBeGreaterThan(0)
    await b.done()
  })

  it('状态栏：后端真实状态 + pid + 心跳；VPN/TG/MCP/待处理为 mock', async () => {
    const b = await boot()
    const conn = () => b.wrapper.get('[data-testid=connection]').text()
    expect(conn()).toContain('连接中')
    b.sock.emit(hello(777))
    await flushPromises()
    expect(conn()).toContain('在线')
    expect(b.wrapper.get('[data-testid=connection-detail]').text()).toContain('PID 777')
    b.sock.emit(
      env('system.heartbeat', { uptime_s: 5 }, { ts: new Date(Date.now() - 30).toISOString() }),
    )
    await flushPromises()
    expect(b.store.latencyMs).toBeGreaterThanOrEqual(0)
    expect(b.wrapper.get('[data-testid=connection-detail]').text()).toMatch(/MS/)
    for (const k of ['vpn', 'tg', 'mcp', 'pending']) {
      expect(b.wrapper.find(`[data-testid=status-${k}]`).exists()).toBe(true)
    }
    b.sock.drop()
    await flushPromises()
    expect(conn()).toContain('重连中')
    await b.done()
  })

  it('/health 查询在 online 后显示版本', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
    await vi.waitFor(() =>
      expect(b.wrapper.get('[data-testid=health-version]').text()).toBe('9.9.9'),
    )
    await b.done()
  })

  it('告警开关只发请求，不本地切换；仅 system.alert 事件改变告警态', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
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
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toContain('401')
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    await b.done()
  })

  it('告警：横幅显示 reason（无 reason 给默认文案）、导航任务角标变 !、工作区无遮罩', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
    expect(b.wrapper.find('[data-testid=nav-alert-badge]').exists()).toBe(false)
    b.sock.emit(alertEvent(true, 'disk full'))
    await flushPromises()
    const banner = b.wrapper.get('[data-testid=alert-banner]')
    expect(banner.attributes('role')).toBe('alert')
    expect(banner.text()).toContain('disk full')
    expect(b.wrapper.get('[data-testid=nav-alert-badge]').text()).toBe('!')
    // 无全屏遮罩：壳内没有 fixed/absolute 覆盖层拦截点击
    expect(b.wrapper.find('[data-testid=app-shell] .overlay').exists()).toBe(false)

    b.sock.emit(alertEvent(true, null))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toContain('未提供原因')

    b.sock.emit(alertEvent(false))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=nav-alert-badge]').exists()).toBe(false)
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

  it('检查器可收起/展开：按钮键盘可达，收起后主区占满', async () => {
    const b = await boot()
    const shell = b.wrapper.get('[data-testid=app-shell]')
    const btn = b.wrapper.get('[data-testid=inspector-toggle]')
    expect(btn.element.tagName).toBe('BUTTON')
    expect(btn.attributes('aria-label')).toBe('收起检查器')
    expect(btn.attributes('aria-expanded')).toBe('true')
    expect(shell.attributes('data-inspector')).toBe('open')
    expect(
      (b.wrapper.get('[data-testid=inspector]').element as HTMLElement).style.display,
    ).not.toBe('none')
    await btn.trigger('click')
    expect(shell.attributes('data-inspector')).toBe('closed')
    expect(b.wrapper.get('[data-testid=inspector-toggle]').attributes('aria-label')).toBe(
      '展开检查器',
    )
    expect((b.wrapper.get('[data-testid=inspector]').element as HTMLElement).style.display).toBe(
      'none',
    )
    await b.wrapper.get('[data-testid=inspector-toggle]').trigger('click')
    expect(shell.attributes('data-inspector')).toBe('open')
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
