// 方向 B 连接安全回归、禁词扫描、令牌对比度（独立编写）。全部使用假 token / 假 socket / 假 fetch。
import { flushPromises } from '@vue/test-utils'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot, openConnection } from '../unit/boot'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'

const TOKEN = 'fake-token' // boot() 注入的假 token
const ROOT = process.cwd()

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
  vi.useRealTimers()
})

function reqUrls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((c) => (c[0] as Request).url)
}

describe('连接安全：token 只在内存与 HTTP/WS 头中', () => {
  it('token 不出现在 DOM、localStorage、sessionStorage、Pinia 状态中（启动并收到事件后）', async () => {
    const b = await boot()
    b.sock.emit(hello(77))
    b.sock.emit(env('system.alert', { active: true, reason: 'x', changed_at: 't' }))
    await flushPromises()
    expect(document.documentElement.outerHTML).not.toContain(TOKEN)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(JSON.stringify(b.store.$state)).not.toContain(TOKEN)
    await b.done()
  })

  it('HTTP 请求 URL 不含 token，且每个请求都带 Authorization: Bearer', async () => {
    const b = await boot()
    b.sock.emit(hello(77))
    await flushPromises()
    await vi.waitFor(() =>
      expect(reqUrls(b.fetchMock).some((u) => u.endsWith('/health'))).toBe(true),
    )
    await openConnection(b)
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    const reqs = b.fetchMock.mock.calls.map((c) => c[0] as Request)
    expect(reqs.length).toBeGreaterThan(0)
    for (const r of reqs) {
      expect(r.url).not.toContain(TOKEN)
      expect(r.headers.get('authorization')).toBe(`Bearer ${TOKEN}`)
    }
    await b.done()
  })

  it('WebSocket URL 不含 token；首帧为 {"type":"auth","token":...}', async () => {
    const b = await boot()
    expect(b.sock.url).toBe('ws://127.0.0.1:5555/ws/events')
    expect(b.sock.url).not.toContain(TOKEN)
    expect(b.sock.sent).toEqual([JSON.stringify({ type: 'auth', token: TOKEN })])
    expect(JSON.parse(b.sock.sent[0]!)).toEqual({ type: 'auth', token: TOKEN })
    await b.done()
  })

  it('断线后 0.5s 重连，新 socket 打开后重新发送 auth 帧，URL 仍不含 token', async () => {
    const b = await boot()
    b.sock.emit(hello(1))
    await flushPromises()
    vi.useFakeTimers()
    b.sock.drop(1006)
    await vi.advanceTimersByTimeAsync(499)
    expect(FakeSocket.instances).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(FakeSocket.instances).toHaveLength(2)
    const s2 = FakeSocket.last()
    expect(s2.url).not.toContain(TOKEN)
    s2.onopen?.({})
    expect(s2.sent).toEqual([JSON.stringify({ type: 'auth', token: TOKEN })])
    await b.done()
  })

  it('指数退避 500→1000→2000→4000→8000→10000（封顶）：未收到 hello 时连续断线', async () => {
    const b = await boot()
    b.sock.emit(hello(1))
    await flushPromises()
    vi.useFakeTimers()
    const expected = [500, 1000, 2000, 4000, 8000, 10000, 10000]
    let sock = FakeSocket.last()
    sock.drop(1006)
    for (const ms of expected) {
      const before = FakeSocket.instances.length
      await vi.advanceTimersByTimeAsync(ms - 1)
      expect(FakeSocket.instances.length, `退避 ${ms}ms 前不应重连`).toBe(before)
      await vi.advanceTimersByTimeAsync(1)
      expect(FakeSocket.instances.length, `退避 ${ms}ms 后应重连`).toBe(before + 1)
      sock = FakeSocket.last()
      sock.drop(1006)
    }
    await b.done()
  })

  it('重连成功 hello 后退避计数复位：下一次断线又从 500ms 开始', async () => {
    const b = await boot()
    b.sock.emit(hello(1))
    await flushPromises()
    vi.useFakeTimers()
    FakeSocket.last().drop(1006)
    await vi.advanceTimersByTimeAsync(500)
    const s2 = FakeSocket.last()
    s2.onopen?.({})
    s2.onmessage?.({
      data: JSON.stringify(
        env(
          'system.hello',
          { pid: 2, version: 'v', alert: { active: false, reason: null, changed_at: '' } },
          { seq: 2 },
        ),
      ),
    })
    await vi.advanceTimersByTimeAsync(0)
    s2.drop(1006)
    const before = FakeSocket.instances.length
    await vi.advanceTimersByTimeAsync(499)
    expect(FakeSocket.instances.length).toBe(before)
    await vi.advanceTimersByTimeAsync(1)
    expect(FakeSocket.instances.length).toBe(before + 1)
    await b.done()
  })

  it('告警开关请求失败后不产生重复 socket（网络错误不影响连接状态机）', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('network down')
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    b.sock.emit(hello(1))
    await flushPromises()
    await openConnection(b)
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('请求失败（网络）')
    expect(FakeSocket.instances).toHaveLength(1)
    await b.done()
  })
})

// ---------- 禁词扫描（源码；dist 由 pnpm guard:dist，跳过二进制文件；woff2 等字体不扫） ----------
const FORBIDDEN = /rhine|arknights|莱茵|fonts\.googleapis/i

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

function textFiles(dir: string): string[] {
  return walk(dir).filter((f) => !/\.(woff2?|ttf|otf|png|jpe?g|gif|ico|webp)$/i.test(f))
}

describe('禁词与残留令牌', () => {
  it('src 下文本文件不含禁词（不区分大小写）', () => {
    const hits: string[] = []
    for (const f of textFiles(join(ROOT, 'src'))) {
      const buf = readFileSync(f)
      if (buf.includes(0)) continue
      buf
        .toString('utf8')
        .split('\n')
        .forEach((line, i) => {
          if (FORBIDDEN.test(line)) hits.push(`${f}:${i + 1}`)
        })
    }
    expect(hits).toEqual([])
  })

  it('已删除的 --denied 令牌不再被定义或引用（src；dist 侧由 pnpm guard:dist 检查）', () => {
    const hits: string[] = []
    for (const dir of [join(ROOT, 'src')]) {
      for (const f of textFiles(dir)) {
        const buf = readFileSync(f)
        if (buf.includes(0)) continue
        if (/--denied/.test(buf.toString('utf8'))) hits.push(f)
      }
    }
    expect(hits).toEqual([])
  })
})

// 令牌对比度（原方向 E 的珍珠/玻璃/黑橙断言）已随 R1 换皮由 tests/unit/tokens.test.ts 的 B 令牌对比度测试取代。
