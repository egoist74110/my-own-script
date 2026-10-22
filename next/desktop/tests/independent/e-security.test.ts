// 方向 E 连接安全回归、禁词扫描、令牌对比度（独立编写）。全部使用假 token / 假 socket / 假 fetch。
import { flushPromises } from '@vue/test-utils'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from '../unit/boot'
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
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('请求失败（网络）')
    expect(FakeSocket.instances).toHaveLength(1)
    await b.done()
  })
})

// ---------- 禁词扫描（源码 + dist，跳过二进制文件；woff2 等字体不扫） ----------
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

  it('dist 下文本文件不含禁词（需已构建）', () => {
    const dist = join(ROOT, 'dist')
    expect(statSync(dist).isDirectory(), 'dist 不存在').toBe(true)
    const hits: string[] = []
    for (const f of textFiles(dist)) {
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

  it('已删除的 --denied 令牌不再被定义或引用（src 与 dist）', () => {
    const hits: string[] = []
    for (const dir of [join(ROOT, 'src'), join(ROOT, 'dist')]) {
      for (const f of textFiles(dir)) {
        const buf = readFileSync(f)
        if (buf.includes(0)) continue
        if (/--denied/.test(buf.toString('utf8'))) hits.push(f)
      }
    }
    expect(hits).toEqual([])
  })
})

// ---------- WCAG 对比度（从 tokens.css 解析） ----------
function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)) as [number, number, number]
}
function lum([r, g, b]: [number, number, number]): number {
  const f = (v: number) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
function ratio(a: [number, number, number], b: [number, number, number]): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}
function mix(fg: [number, number, number], alpha: number, bg: [number, number, number]) {
  return fg.map((v, i) => Math.round(v * alpha + bg[i]! * (1 - alpha))) as [number, number, number]
}

const tokensCss = readFileSync(join(ROOT, 'src/design/tokens.css'), 'utf8')
function token(name: string): [number, number, number] {
  const m = tokensCss.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,6})\\s*;`))
  if (!m) throw new Error(`token --${name} not found in tokens.css`)
  return hexToRgb(m[1]!)
}

describe('对比度（WCAG AA 正文 ≥ 4.5:1）', () => {
  const pearls = ['pearl-a', 'pearl-b', 'pearl-c'] as const
  // 玻璃近似：白色 52% 叠在珍珠底上（见 ui.css 的 .glass 渐变末端）
  const glass = (p: [number, number, number]) => mix([255, 255, 255], 0.52, p)

  it('--ink 与 --mute 在珍珠底及玻璃近似上 ≥ 4.5:1', () => {
    for (const p of pearls) {
      const base = token(p)
      for (const bg of [base, glass(base)]) {
        expect(ratio(token('ink'), bg), `ink on ${p}`).toBeGreaterThanOrEqual(4.5)
        expect(ratio(token('mute'), bg), `mute on ${p}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('--warn-ink 与 --ok-ink 在珍珠底及玻璃近似上 ≥ 4.5:1', () => {
    for (const p of pearls) {
      const base = token(p)
      for (const bg of [base, glass(base)]) {
        expect(ratio(token('warn-ink'), bg), `warn-ink on ${p}`).toBeGreaterThanOrEqual(4.5)
        expect(ratio(token('ok-ink'), bg), `ok-ink on ${p}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('墨色文字在强调色 --acc 与告警橙 --warn 填充上 ≥ 4.5:1', () => {
    expect(ratio(token('ink'), token('acc'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(token('ink'), token('warn'))).toBeGreaterThanOrEqual(4.5)
  })

  it('标记为「只做填充」的 --warn 不得作为珍珠底上的文字色（应低于 4.5:1，证明令牌注释成立）', () => {
    expect(ratio(token('warn'), token('pearl-a'))).toBeLessThan(4.5)
  })

  it('告警横幅与审批条的深底文字：#f2f0eb / #ff6a00 标签 / #ff9a4d / #ffb27a 在 --ink 上 ≥ 4.5:1', () => {
    const ink = token('ink')
    for (const c of ['#f2f0eb', '#ff6a00', '#ff9a4d', '#ffb27a', '#ffffff']) {
      expect(ratio(hexToRgb(c), ink), c).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('--acc 只做填充：不被当作文字色用于珍珠底（对比度不足，符合令牌注释）', () => {
    expect(ratio(token('acc'), token('pearl-a'))).toBeLessThan(4.5)
  })
})
