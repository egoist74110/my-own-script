// R1 独立验证：页面行为（合同 R1 验收第 5 条）：工单四态、设置三态、AI 审批 Y/A/N、任务占位、告警横幅。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from '../unit/boot'
import { FakeSocket, alertEvent, hello, resetSeq } from '../unit/helpers'
import { createFake, json, makeAdo, makeSettings } from '../unit/settings-fake'
import { createWiFake, summary, wiErr, type WiFake } from '../unit/wi-fake'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
})

async function settle(n = 5) {
  for (let i = 0; i < n; i++) await flushPromises()
}

/** 在假 fetch 之上覆盖工单列表路由；返回 undefined 时落到原假后端。 */
function wiWith(fake: WiFake, list: (n: number) => Response | Promise<Response> | undefined) {
  let n = 0
  return vi.fn(async (req: Request) => {
    const path = new URL(req.url).pathname
    if (path === '/api/work-items') {
      const r = await list(++n)
      if (r) return r
    }
    return fake.fetch(req)
  }) as unknown as typeof fetch
}

const okList = () => json({ items: [summary(1), summary(2)], truncated: false, omitted: 0 })

describe('工单页四态（R1）', () => {
  it('正常：列出条目，列表面板不忙', async () => {
    const fake = createWiFake()
    const b = await boot({ path: '/work-items', fetchImpl: wiWith(fake, okList) })
    b.sock.emit(hello())
    await settle()
    expect(b.wrapper.find('[data-testid=wi-row-1]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid=wi-row-2]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid=no-projects]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=wi-error]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=project-select]').exists()).toBe(true)
    await b.done()
  })

  it('未配置项目：显示 no-projects 空状态并给出前往设置的入口', async () => {
    const fake = createWiFake()
    fake.ado = makeAdo({ projects: [], active_project_id: null })
    const b = await boot({ path: '/work-items', fetchImpl: wiWith(fake, okList) })
    b.sock.emit(hello())
    await settle()
    const empty = b.wrapper.get('[data-testid=no-projects]')
    expect(empty.text()).toContain('没有 ADO 项目')
    expect(empty.find('a[href="/settings"]').exists()).toBe(true)
    await b.done()
  })

  it('读取中：列表面板 aria-busy=true，且还没有条目', async () => {
    const fake = createWiFake()
    const b = await boot({
      path: '/work-items',
      fetchImpl: wiWith(fake, () => new Promise<Response>(() => {})),
    })
    b.sock.emit(hello())
    await settle()
    const panel = b.wrapper.get('#wi-list-panel')
    expect(panel.attributes('aria-busy')).toBe('true')
    expect(b.wrapper.find('[data-testid=wi-row-1]').exists()).toBe(false)
    await b.done()
  })

  it('出错：显示 wi-error 带「重试」，重试后恢复正常', async () => {
    const fake = createWiFake()
    let fail = true
    const b = await boot({
      path: '/work-items',
      fetchImpl: wiWith(fake, () => (fail ? wiErr(500, 'internal_error') : okList())),
    })
    b.sock.emit(hello())
    await settle()
    const err = b.wrapper.get('[data-testid=wi-error]')
    expect(err.attributes('role')).toBe('alert')
    const retry = err.findAll('button').find((x) => x.text() === '重试')
    expect(retry, '重试按钮').toBeTruthy()

    fail = false
    await retry!.trigger('click')
    await settle()
    expect(b.wrapper.find('[data-testid=wi-error]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=wi-row-1]').exists()).toBe(true)
    await b.done()
  })
})

describe('设置页三态（R1）', () => {
  it('正常：无存储只读横幅、无加载错误', async () => {
    const fake = createFake()
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await settle()
    expect(b.wrapper.find('[data-testid=settings-summary]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid=store-error]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=load-error]').exists()).toBe(false)
    await b.done()
  })

  it('HTTP 明文地址：选中该 library 后显示 http-warning（PAT 明文提示保留）', async () => {
    const fake = createFake()
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await settle()
    // 默认落在「导入」页签；库列表在「ADO 连接」页签（Reka 页签在 mousedown 激活）
    const ado = b.wrapper.findAll('[role=tab]').find((t) => t.text().startsWith('ADO 连接'))
    expect(ado, 'ADO 连接 页签').toBeTruthy()
    await ado!.trigger('mousedown', { button: 0 })
    await settle()
    await b.wrapper.get('[data-testid="library-row-lib:b"]').trigger('click')
    await settle()
    const w = b.wrapper.get('[data-testid=http-warning]')
    expect(w.text()).toContain('HTTP 明文')
    await b.done()
  })

  it('存储只读：显示 store-error（role=alert）并带原因', async () => {
    const fake = createFake()
    fake.state.settings = makeSettings({ store_state: 'readonly_error', store_error: '磁盘只读' })
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await settle()
    const e = b.wrapper.get('[data-testid=store-error]')
    expect(e.attributes('role')).toBe('alert')
    expect(e.text()).toContain('磁盘只读')
    await b.done()
  })
})

describe('AI 会话页审批 Y/A/N（R1）', () => {
  async function openAi() {
    const b = await boot({ path: '/ai' })
    b.sock.emit(hello())
    await settle()
    return b
  }
  const press = (key: string, target: EventTarget = window) =>
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))

  it('默认选中会话有待审批命令，审批条可见', async () => {
    const b = await openAi()
    const bar = b.wrapper.get('[data-testid=approval-bar]')
    expect(bar.text()).toContain('pnpm vitest run')
    await b.done()
  })

  it('按 y 记为允许一次', async () => {
    const b = await openAi()
    press('y')
    await settle()
    const log = b.wrapper.get('[data-testid=decision-log]')
    expect(log.attributes('data-decision')).toBe('once')
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    await b.done()
  })

  it('按 a 记为本会话总是允许', async () => {
    const b = await openAi()
    press('a')
    await settle()
    expect(b.wrapper.get('[data-testid=decision-log]').attributes('data-decision')).toBe('always')
    await b.done()
  })

  it('按 n 记为拒绝', async () => {
    const b = await openAi()
    press('n')
    await settle()
    expect(b.wrapper.get('[data-testid=decision-log]').attributes('data-decision')).toBe('deny')
    await b.done()
  })

  it('输入框聚焦时 y/a/n 不触发审批', async () => {
    const b = await openAi()
    const ta = b.wrapper.get('form.composer textarea').element as HTMLTextAreaElement
    ta.focus()
    press('y', ta)
    press('a', ta)
    press('n', ta)
    await settle()
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(true)
    await b.done()
  })
})

describe('任务页占位与根路由（R1）', () => {
  it('/ 重定向到 /tasks；任务页根节点存在且不含 mock 任务文本', async () => {
    const b = await boot({ path: '/' })
    b.sock.emit(hello())
    await settle()
    expect(b.router.currentRoute.value.path).toBe('/tasks')
    expect(b.wrapper.find('[data-testid=tasks-page]').exists()).toBe(true)
    const text = b.wrapper.get('main').text()
    for (const bad of [
      'web-portal',
      'admin-console',
      'docs-site',
      'Runs/wk',
      'FAILED',
      'CLEAR',
      'ROLLBACK',
    ]) {
      expect(text, bad).not.toContain(bad)
    }
    await b.done()
  })
})

describe('告警横幅（R1）', () => {
  it('system.alert 进入 store 后出现 warn 横幅；连接行变为告警态；页面按钮仍可点击', async () => {
    const b = await boot({ path: '/tasks' })
    b.sock.emit(hello())
    b.sock.emit(alertEvent(true, 'staging-a 被环境拒绝'))
    await settle()
    expect(b.store.alert.active).toBe(true)
    const banner = b.wrapper.get('[data-testid=alert-banner]')
    expect(banner.attributes('data-tone')).toBe('warn')
    expect(banner.text()).toContain('staging-a 被环境拒绝')
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('true')
    // 横幅不遮挡：导航仍能切页
    await b.wrapper.get('nav a[href="/ai"]').trigger('click')
    await settle()
    expect(b.router.currentRoute.value.path).toBe('/ai')
    await b.done()
  })

  it('告警无原因时显示默认文案', async () => {
    const b = await boot({ path: '/tasks' })
    b.sock.emit(hello())
    b.sock.emit(alertEvent(true, null))
    await settle()
    expect(b.wrapper.get('[data-testid=alert-banner]').text()).toContain(
      '后端报告告警（未提供原因）',
    )
    await b.done()
  })

  it('告警解除后横幅消失，连接行恢复', async () => {
    const b = await boot({ path: '/tasks' })
    b.sock.emit(hello())
    b.sock.emit(alertEvent(true, 'x'))
    await settle()
    b.sock.emit(alertEvent(false))
    await settle()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('false')
    await b.done()
  })
})
