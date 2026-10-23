// R1 独立验证：ConnectionStatus 四种连接态与告警开关（合同 R1 验收第 4 条）。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { bootUnconnected, boot, json, openConnection } from '../unit/boot'
import { FakeSocket, hello, resetSeq } from '../unit/helpers'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('ConnectionStatus 四种连接态', () => {
  it('connecting：尚未连上时显示「后端 连接中」', async () => {
    const b = await bootUnconnected()
    await flushPromises()
    expect(b.store.connection).toBe('connecting')
    expect(b.wrapper.get('[data-testid=connection]').text()).toContain('连接中')
    expect(b.wrapper.get('[data-testid=connection] [data-state]').attributes('data-state')).toBe(
      'connecting',
    )
    await b.done()
  })

  it('online：收到 hello 后显示「在线」', async () => {
    const b = await boot()
    b.sock.emit(hello(4242))
    await flushPromises()
    expect(b.store.connection).toBe('online')
    expect(b.wrapper.get('[data-testid=connection]').text()).toContain('在线')
    await b.done()
  })

  it('reconnecting：连接断开后显示「重连中」', async () => {
    const b = await boot()
    b.sock.emit(hello(4242))
    await flushPromises()
    b.sock.drop()
    await flushPromises()
    expect(b.store.connection).toBe('reconnecting')
    expect(b.wrapper.get('[data-testid=connection]').text()).toContain('重连中')
    await b.done()
  })

  it('offline：后端不可达时显示「离线」', async () => {
    const b = await boot()
    b.store.connection = 'offline'
    await flushPromises()
    expect(b.wrapper.get('[data-testid=connection]').text()).toContain('离线')
    expect(b.wrapper.get('.conn').attributes('data-alert')).toBe('false')
    await b.done()
  })
})

describe('ConnectionStatus 弹出层与告警演示开关', () => {
  it('弹出层含 pid 与心跳延迟；开关是 role=switch', async () => {
    const b = await boot()
    b.sock.emit(hello(4242))
    await flushPromises()
    await openConnection(b)
    const pop = b.wrapper.get('[data-testid=connection-popover]')
    expect(pop.get('[data-testid=connection-pid]').text()).toBe('4242')
    expect(pop.find('[data-testid=connection-latency]').exists()).toBe(true)
    expect(pop.find('[role=switch]').exists()).toBe(true)
    await b.done()
  })

  it('开关只发 POST /api/system/alert，不在本地切换告警态（请求未返回时开关不变）', async () => {
    const posts: Request[] = []
    const fetchImpl = vi.fn(async (req: Request) => {
      if (req.url.endsWith('/health'))
        return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 1, alert: false })
      posts.push(req)
      // 永不返回：若实现本地切换，告警态会在这里就变化
      return new Promise<Response>(() => {})
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    b.sock.emit(hello(4242))
    await flushPromises()
    await openConnection(b)

    const sw = b.wrapper.get('[data-testid=connection-popover] [role=switch]')
    expect(sw.attributes('aria-checked')).toBe('false')
    await sw.trigger('click')
    await flushPromises()

    expect(posts.length).toBe(1)
    expect(new URL(posts[0]!.url).pathname).toBe('/api/system/alert')
    expect(posts[0]!.method).toBe('POST')
    expect(JSON.parse(await posts[0]!.clone().text())).toMatchObject({ active: true })
    // 不本地切换：store 与开关都仍是关闭
    expect(b.store.alert.active).toBe(false)
    expect(
      b.wrapper.get('[data-testid=connection-popover] [role=switch]').attributes('aria-checked'),
    ).toBe('false')
    // 其它路径不应被请求
    expect(posts.every((r) => new URL(r.url).pathname === '/api/system/alert')).toBe(true)
    await b.done()
  })
})
