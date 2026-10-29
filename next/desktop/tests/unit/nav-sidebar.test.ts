// 侧栏基础设施导航、设置页 tab 与 URL 同步、侧栏手动展开/收起。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SIDEBAR_KEY } from '@/stores/ui'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { createFake, json } from './settings-fake'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function openAt(path: string) {
  const fake = createFake()
  // MCP 分区会读 /api/ai；设置页夹具没有这个接口，补一个空配置，避免页面渲染时读到 undefined
  fake.handlers.push((c) =>
    c.method === 'GET' && c.path === '/api/ai' ? json({ profiles: [] }) : undefined,
  )
  const b = await boot({ path, fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  return b
}
type B = Awaited<ReturnType<typeof openAt>>
const navLink = (b: B, name: string) => b.wrapper.findAll('nav a').find((a) => a.text() === name)!
const activeNames = (b: B) => b.wrapper.findAll('nav a[aria-current=page]').map((a) => a.text())
const selectedTab = (b: B) => b.wrapper.get('[role=tab][aria-selected=true]').text()

describe('基础设施导航进入对应设置分区', () => {
  it.each([
    ['MCP', '/settings/mcp', 'MCP'],
    ['服务', '/settings/services', '服务'],
    ['VPN', '/settings/vpn', '服务'],
  ])('点“%s” -> %s，落在设置的“%s”分区并只高亮自己', async (name, path, tab) => {
    const b = await openAt('/work-items')
    await navLink(b, name).trigger('click')
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe(path))
    await flushPromises()
    expect(selectedTab(b)).toContain(tab)
    expect(activeNames(b)).toEqual([name])
    await b.done()
  })

  it('/settings 只高亮“设置”；切到 AI 会话只高亮它', async () => {
    const b = await openAt('/settings')
    expect(activeNames(b)).toEqual(['设置'])
    await b.router.push('/ai')
    await flushPromises()
    expect(activeNames(b)).toEqual(['AI 会话'])
    await b.done()
  })

  it('VPN 直达：渲染 VPN 卡片并滚动到它', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    const b = await openAt('/settings/vpn')
    expect(b.wrapper.find('[data-testid=vpn-card]').exists()).toBe(true)
    expect(b.wrapper.get('#settings-vpn').attributes('data-testid')).toBe('vpn-card')
    expect(scroll).toHaveBeenCalled()
    await b.done()
  })

  it('未知设置分区回到 /tasks', async () => {
    const b = await openAt('/settings/nope')
    await flushPromises()
    expect(b.router.currentRoute.value.path).toBe('/tasks')
    await b.done()
  })
})

describe('设置页分区与 URL 同步', () => {
  it('点分区更新 URL；直接打开 URL 选中对应分区；浏览器后退跟随', async () => {
    const b = await openAt('/settings/mcp')
    expect(selectedTab(b)).toContain('MCP')
    const tab = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith('通用'))!
    await tab.trigger('mousedown')
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe('/settings/general'))
    await flushPromises()
    expect(selectedTab(b)).toContain('通用')
    expect(activeNames(b)).toEqual(['设置'])
    b.router.back()
    await flushPromises()
    expect(b.router.currentRoute.value.path).toBe('/settings/mcp')
    expect(selectedTab(b)).toContain('MCP')
    await b.done()
  })

  it('从 /settings/vpn 手动换分区：URL 跟着变，高亮从 VPN 切到对应入口', async () => {
    const b = await openAt('/settings/vpn')
    expect(activeNames(b)).toEqual(['VPN'])
    const pick = async (label: string, path: string) => {
      const tab = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith(label))!
      await tab.trigger('mousedown')
      await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe(path))
      await flushPromises()
    }
    await pick('MCP', '/settings/mcp')
    expect(activeNames(b)).toEqual(['MCP'])
    await pick('服务', '/settings/services')
    expect(activeNames(b)).toEqual(['服务'])
    await b.done()
  })
})

function stubMedia(wide: boolean) {
  const listeners = new Set<(e: { matches: boolean }) => void>()
  let matches = wide
  vi.stubGlobal(
    'matchMedia',
    vi.fn((q: string) => ({
      get matches() {
        // 只有侧栏查询受控；其余（检查器）按宽窗
        return q.includes('min-width: 1100px') ? matches : false
      },
      media: q,
      addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => listeners.add(cb),
      removeEventListener: (_: string, cb: (e: { matches: boolean }) => void) =>
        listeners.delete(cb),
    })),
  )
  return {
    set(v: boolean) {
      matches = v
      listeners.forEach((cb) => cb({ matches: v }))
    },
  }
}
const shellMode = (b: B) => b.wrapper.get('[data-testid=app-shell]').attributes('data-sidebar')
const toggle = (b: B) => b.wrapper.get('[data-testid=sidebar-toggle]')

describe('侧栏手动展开/收起', () => {
  it('宽窗默认展开；按钮收起后持久化，再次启动仍收起；再点展开', async () => {
    stubMedia(true)
    const b = await openAt('/work-items')
    expect(shellMode(b)).toBe('expanded')
    expect(toggle(b).attributes('aria-label')).toBe('收起导航')
    expect(toggle(b).attributes('title')).toBe('收起导航')
    expect(toggle(b).attributes('aria-expanded')).toBe('true')
    await toggle(b).trigger('click')
    expect(shellMode(b)).toBe('compact')
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe('collapsed')
    expect(toggle(b).attributes('aria-label')).toBe('展开导航')
    await b.done()
    document.body.innerHTML = ''

    const b2 = await openAt('/work-items')
    expect(shellMode(b2)).toBe('compact')
    await toggle(b2).trigger('click')
    expect(shellMode(b2)).toBe('expanded')
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe('expanded')
    await b2.done()
  })

  it('窄窗默认图标；按钮开浮层（主区不被挤压），Esc 收起且不改持久化选择', async () => {
    stubMedia(false)
    const b = await openAt('/work-items')
    expect(shellMode(b)).toBe('compact')
    await toggle(b).trigger('click')
    expect(shellMode(b)).toBe('overlay')
    expect(b.wrapper.get('[data-testid=sidebar]').attributes('data-mode')).toBe('overlay')
    expect(toggle(b).attributes('aria-label')).toBe('收起导航')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(shellMode(b)).toBe('compact')
    expect(localStorage.getItem(SIDEBAR_KEY)).toBeNull()
    await b.done()
  })

  it('窄窗浮层：点外部收起，点侧栏内部不收起；导航后收起', async () => {
    stubMedia(false)
    const b = await openAt('/work-items')
    await toggle(b).trigger('click')
    b.wrapper
      .get('aside[aria-label=侧栏]')
      .element.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(shellMode(b)).toBe('overlay')
    b.wrapper.get('main').element.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(shellMode(b)).toBe('compact')

    await toggle(b).trigger('click')
    await navLink(b, 'AI 会话').trigger('click')
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe('/ai'))
    await flushPromises()
    expect(shellMode(b)).toBe('compact')
    await b.done()
  })

  it('优先级：宽窗里的手动选择优先于自动断点；窄窗不覆盖它；变窄/变宽时浮层复位', async () => {
    const mq = stubMedia(true)
    const b = await openAt('/work-items')
    await toggle(b).trigger('click') // 手动收起
    expect(shellMode(b)).toBe('compact')
    mq.set(false)
    await flushPromises()
    expect(shellMode(b)).toBe('compact')
    await toggle(b).trigger('click') // 窄窗开浮层
    expect(shellMode(b)).toBe('overlay')
    mq.set(true) // 变宽：浮层复位，回到手动选择（收起）
    await flushPromises()
    expect(shellMode(b)).toBe('compact')
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe('collapsed')
    await toggle(b).trigger('click')
    expect(shellMode(b)).toBe('expanded')
    await b.done()
  })

  it('localStorage 不可用时不报错，仍可切换（仅内存）', async () => {
    stubMedia(true)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    const b = await openAt('/work-items')
    expect(shellMode(b)).toBe('expanded')
    await toggle(b).trigger('click')
    expect(shellMode(b)).toBe('compact')
    await b.done()
  })

  it('没有 matchMedia 时按宽窗展开（降级不报错）', async () => {
    const b = await openAt('/work-items')
    expect(shellMode(b)).toBe('expanded')
    await b.done()
  })
})
