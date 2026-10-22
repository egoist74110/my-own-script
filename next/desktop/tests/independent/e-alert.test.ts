// 方向 E 告警态（独立编写）：横幅 / 任务行 / 检查器 / 导航角标 / 告警开关。
// 只用假 socket 与假 fetch，不连真实后端。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot, json } from '../unit/boot'
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

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
})
afterEach(() => {
  document.body.innerHTML = ''
  vi.useRealTimers()
})

describe('告警态：同时出现在横幅、任务行、检查器、导航角标', () => {
  it('告警开启后四处同步出现，且只有 errorOnAlert 的 t1 行被标记', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, 'S0 DEMO ALERT'))
    await flushPromises()

    const banner = b.wrapper.get('[data-testid=alert-banner]')
    expect(banner.attributes('role')).toBe('alert')
    expect(b.wrapper.get('[data-testid=alert-reason]').text()).toBe('S0 DEMO ALERT')
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-alert')).toBe('true')

    const t1 = b.wrapper.get('[data-testid=task-row-t1]')
    expect(t1.attributes('data-alert')).toBe('true')
    expect(t1.text()).toContain('失败')
    expect(t1.text()).toContain('FAILED')
    expect(t1.find('[data-state=fail]').exists()).toBe(true)

    for (const id of ['t2', 't3', 't4', 't5', 't6', 't7']) {
      expect(b.wrapper.get(`[data-testid=task-row-${id}]`).attributes('data-alert')).toBeUndefined()
    }

    const insp = b.wrapper.get('[data-testid=task-inspector]')
    expect(insp.attributes('data-alert')).toBe('true')
    expect(insp.text()).toContain('HALT')

    expect(b.wrapper.get('[data-testid=nav-alert-badge]').text()).toBe('!')
    await b.done()
  })

  it('告警解除后横幅、角标、行、检查器全部还原', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, 'x'))
    await flushPromises()
    b.sock.emit(alertEnv(101, false, null))
    await flushPromises()

    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-alert')).toBe('false')
    expect(b.wrapper.find('[data-testid=nav-alert-badge]').exists()).toBe(false)

    const t1 = b.wrapper.get('[data-testid=task-row-t1]')
    expect(t1.attributes('data-alert')).toBeUndefined()
    expect(t1.text()).toContain('运行中')
    expect(t1.text()).not.toContain('FAILED')
    expect(t1.find('[data-state=fail]').exists()).toBe(false)

    const insp = b.wrapper.get('[data-testid=task-inspector]')
    expect(insp.attributes('data-alert')).toBeUndefined()
    expect(insp.text()).not.toContain('HALT')
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

  it('告警态下工作区仍可交互：新建任务、点行选中、导航切换、⌘K 聚焦', async () => {
    const b = await boot()
    b.sock.emit(alertEnv(100, true, 'x'))
    await flushPromises()

    const before = b.wrapper.findAll('tbody tr').length
    await b.wrapper.get('[data-testid=add-task]').trigger('click')
    await flushPromises()
    expect(b.wrapper.findAll('tbody tr').length).toBe(before + 1)

    await b.wrapper.get('[data-testid=task-row-t4]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=task-row-t4]').attributes('data-selected')).toBe('true')

    await b.wrapper.get('nav a[href="/work-items"]').trigger('click')
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe('/work-items'))
    await flushPromises()

    await b.router.push('/tasks')
    await flushPromises()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }))
    await flushPromises()
    expect(document.activeElement).toBe(b.wrapper.get('input[type=search]').element)
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
    for (const path of ['/work-items', '/ai']) {
      const b = await boot({ path, ...(path === '/work-items' ? { fetchImpl: wi.fetch } : {}) })
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
    expect(b.wrapper.get('[data-testid=task-row-t1]').attributes('data-alert')).toBe('true')
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
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toContain('请求失败 (500)')
    expect(b.wrapper.get('[role=switch]').attributes('aria-checked')).toBe('false')
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    await b.done()
  })
})
