// S5-D 独立测试（测试员）：TerminalView 的 WS 生命周期、断线续接、卸载与凭据暴露。
// xterm 与 WebSocket 均为替身；不连接真实后端。
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backendRuntimeKey } from '@/app/backend-runtime'
import TerminalView from '@/features/ai/TerminalView.vue'

const h = vi.hoisted(() => ({
  terms: [] as Array<{
    rows: number
    cols: number
    written: Uint8Array[]
    onDataCb: ((d: string) => void) | null
    disposed: boolean
  }>,
  sockets: [] as Array<Record<string, unknown>>,
}))

vi.mock('@xterm/xterm', () => {
  class Terminal {
    rows = 24
    cols = 80
    options: Record<string, unknown>
    written: Uint8Array[] = []
    onDataCb: ((d: string) => void) | null = null
    disposed = false
    constructor(opts: Record<string, unknown>) {
      this.options = { ...opts }
      h.terms.push(this)
    }
    loadAddon() {}
    open() {}
    write(d: Uint8Array) {
      this.written.push(d)
    }
    reset() {
      this.written = []
    }
    onData(cb: (d: string) => void) {
      this.onDataCb = cb
      return { dispose() {} }
    }
    dispose() {
      this.disposed = true
    }
  }
  return { Terminal }
})
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit() {}
  },
}))
vi.mock('@xterm/xterm/css/xterm.css', () => ({}))

const TOKEN = 'FAKE-TOKEN-s5d-terminal-7f3a'

class FakeWS {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSING = 2
  static CLOSED = 3
  readyState = 0
  sent: string[] = []
  binaryType = ''
  onopen: ((e: unknown) => void) | null = null
  onmessage: ((e: { data: unknown }) => void) | null = null
  onclose: ((e: unknown) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  closed = false
  constructor(readonly url: string) {
    h.sockets.push(this as unknown as Record<string, unknown>)
  }
  send(d: string) {
    this.sent.push(d)
  }
  close() {
    this.closed = true
    this.readyState = 3
  }
  open() {
    this.readyState = 1
    this.onopen?.({})
  }
  recv(data: Uint8Array) {
    this.onmessage?.({ data })
  }
  drop() {
    this.readyState = 3
    this.onclose?.({ code: 1006 })
  }
}

function frame(offset: number, payload: string): Uint8Array {
  const body = new TextEncoder().encode(payload)
  const out = new Uint8Array(8 + body.length)
  new DataView(out.buffer).setBigUint64(0, BigInt(offset), false)
  out.set(body, 8)
  return out
}

const runtime = {
  api: () => null,
  getConnection: () => ({ port: 5555, token: TOKEN }),
  start() {},
  stop() {},
  send: () => false,
  subscribeRun: () => false,
  unsubscribeRun: () => false,
  onEvent: () => () => {},
}

function socket(i = h.sockets.length - 1): FakeWS {
  return h.sockets[i] as unknown as FakeWS
}
function term(i = 0) {
  return h.terms[i]!
}
const decode = (chunks: Uint8Array[]) => chunks.map((c) => new TextDecoder().decode(c)).join('')

async function mountView(sessionState = 'busy', sessionId = 'ais_0123456789abcdef') {
  const wrapper = mount(TerminalView, {
    props: { sessionId, sessionState },
    global: { provide: { [backendRuntimeKey as symbol]: runtime } },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  h.terms.length = 0
  h.sockets.length = 0
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWS)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('S5-D 独立：终端 WS 首帧认证与发送顺序', () => {
  it('token 只出现在首帧 auth 中：不在 URL、DOM、storage 或 console', async () => {
    const logs: unknown[] = []
    for (const m of ['log', 'info', 'warn', 'error', 'debug'] as const) {
      vi.spyOn(console, m).mockImplementation((...a: unknown[]) => {
        logs.push(a)
      })
    }
    const w = await mountView()
    socket().open()
    await flushPromises()

    expect(socket().url).not.toContain(TOKEN)
    expect(socket().url).toMatch(/\/api\/ai\/terminals\/ais_0123456789abcdef\/ws$/)

    const frames = socket().sent.map((s) => JSON.parse(s) as Record<string, unknown>)
    expect(frames[0]).toEqual({ type: 'auth', token: TOKEN })
    for (const f of frames.slice(1)) {
      expect(JSON.stringify(f)).not.toContain(TOKEN)
    }

    expect(w.html()).not.toContain(TOKEN)
    expect(document.body.innerHTML).not.toContain(TOKEN)
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i)!
      expect(window.localStorage.getItem(k)).not.toContain(TOKEN)
    }
    for (let i = 0; i < window.sessionStorage.length; i++) {
      const k = window.sessionStorage.key(i)!
      expect(window.sessionStorage.getItem(k)).not.toContain(TOKEN)
    }
    expect(JSON.stringify(logs)).not.toContain(TOKEN)
  })

  it('auth 前不发送 attach/input；打开后首帧为 auth，其次为 attach', async () => {
    await mountView()
    // 尚未 open：用户键入不得发出任何帧
    term().onDataCb?.('ls\r')
    expect(socket().sent).toEqual([])

    socket().open()
    await flushPromises()
    const types = socket().sent.map((s) => (JSON.parse(s) as { type: string }).type)
    expect(types[0]).toBe('auth')
    expect(types[1]).toBe('attach')
  })

  it('断线后重连：attach 的 after_offset 等于已写入末尾，且重放不重复写入终端', async () => {
    await mountView()
    socket(0).open()
    socket(0).recv(frame(0, 'hello'))
    socket(0).recv(frame(5, 'world'))
    await flushPromises()
    expect(decode(term().written)).toBe('helloworld')

    socket(0).drop()
    vi.advanceTimersByTime(500)
    await flushPromises()
    expect(h.sockets).toHaveLength(2)

    socket(1).open()
    const attach = JSON.parse(socket(1).sent[1]!) as { type: string; after_offset: number }
    expect(attach).toEqual({ type: 'attach', after_offset: 10 })

    // 服务端从保留起点（0）整段重放，再推进一段新数据
    socket(1).recv(frame(0, 'helloworld'))
    socket(1).recv(frame(10, '!'))
    await flushPromises()
    expect(decode(term().written)).toBe('helloworld!')
  })

  it('重复推送与部分重叠帧不产生重复字节', async () => {
    await mountView()
    socket(0).open()
    socket(0).recv(frame(0, 'abc'))
    socket(0).recv(frame(1, 'bcd')) // 部分重叠，只应追加 "d"
    socket(0).recv(frame(0, 'abc')) // 完全重复
    await flushPromises()
    expect(decode(term().written)).toBe('abcd')
  })

  it('切换会话 id：水位清零，新会话 attach 从 0 开始', async () => {
    const w = await mountView('busy', 'ais_aaaaaaaaaaaaaaaa')
    socket(0).open()
    socket(0).recv(frame(0, 'hello'))
    await w.setProps({ sessionId: 'ais_bbbbbbbbbbbbbbbb' })
    await flushPromises()
    expect(h.sockets.length).toBeGreaterThanOrEqual(2)
    const newSock = socket(h.sockets.length - 1)
    expect(newSock.url).toContain('ais_bbbbbbbbbbbbbbbb')
    newSock.open()
    const attach = JSON.parse(newSock.sent[1]!) as { after_offset: number }
    expect(attach.after_offset).toBe(0)
  })
})

describe('S5-D 独立：输入与 resize 发送', () => {
  it('输入超过 16 KiB 时拆帧，每帧解码 ≤16384，拼接等于原文', async () => {
    await mountView()
    socket().open()
    await flushPromises()
    const src = 'q'.repeat(16385)
    term().onDataCb?.(src)
    const inputs = socket()
      .sent.map((s) => JSON.parse(s) as { type: string; data?: string })
      .filter((f) => f.type === 'input')
    expect(inputs.length).toBe(2)
    const sizes = inputs.map((f) => Buffer.from(f.data!, 'base64').length)
    expect(Math.max(...sizes)).toBeLessThanOrEqual(16384)
    const joined = Buffer.concat(inputs.map((f) => Buffer.from(f.data!, 'base64'))).toString('utf8')
    expect(joined).toBe(src)
  })

  it('多字节字符跨分片边界：发送端拼接解码后无乱码', async () => {
    await mountView()
    socket().open()
    await flushPromises()
    const src = '中文'.repeat(9000)
    term().onDataCb?.(src)
    const inputs = socket()
      .sent.map((s) => JSON.parse(s) as { type: string; data?: string })
      .filter((f) => f.type === 'input')
    const joined = new TextDecoder('utf-8', { fatal: true }).decode(
      Buffer.concat(inputs.map((f) => Buffer.from(f.data!, 'base64'))),
    )
    expect(joined).toBe(src)
  })

  it('open 后发送的 resize 使用夹取后的尺寸（终端尺寸越界时不超出协议区间）', async () => {
    await mountView()
    term().rows = 1000
    term().cols = 5
    socket().open()
    await flushPromises()
    const resize = socket()
      .sent.map((s) => JSON.parse(s) as Record<string, unknown>)
      .find((f) => f.type === 'resize')
    expect(resize).toEqual({ type: 'resize', rows: 300, cols: 20 })
  })
})

describe('S5-D 独立：断线退避与终态', () => {
  it('连续连接失败的退避序列 500/1000/2000/4000/5000/5000 毫秒（上限 5 秒）', async () => {
    await mountView()
    // 初始 socket 从未 open 就断开
    const expected = [500, 1000, 2000, 4000, 5000, 5000]
    for (let i = 0; i < expected.length; i++) {
      const before = h.sockets.length
      socket().drop()
      vi.advanceTimersByTime(expected[i]! - 1)
      expect(h.sockets.length).toBe(before)
      vi.advanceTimersByTime(1)
      expect(h.sockets.length).toBe(before + 1)
    }
  })

  it('会话已 ended/failed 时断线不重连', async () => {
    await mountView('ended')
    socket(0).open()
    socket(0).drop()
    vi.advanceTimersByTime(60_000)
    expect(h.sockets.length).toBe(1)
  })

  it('会话状态变为 ended 后，已安排的重连被取消', async () => {
    const w = await mountView('busy')
    socket(0).open()
    socket(0).drop()
    await w.setProps({ sessionState: 'ended' })
    vi.advanceTimersByTime(60_000)
    expect(h.sockets.length).toBe(1)
  })
})

describe('S5-D 独立：组件卸载', () => {
  it('卸载后不再重连、不再写入终端、释放 WS 监听并销毁 xterm', async () => {
    const w = await mountView()
    socket(0).open()
    socket(0).recv(frame(0, 'before'))
    const s0 = socket(0)
    const t0 = term()
    w.unmount()

    expect(s0.closed).toBe(true)
    expect(s0.onmessage).toBeNull()
    expect(s0.onclose).toBeNull()
    expect(t0.disposed).toBe(true)

    // 即使旧 socket 仍投递数据，也不得写入已销毁的终端
    const before = t0.written.length
    s0.onmessage?.({ data: frame(6, 'after') })
    s0.drop()
    vi.advanceTimersByTime(60_000)
    expect(t0.written.length).toBe(before)
    expect(h.sockets.length).toBe(1)
  })

  it('卸载发生在重连等待期间：定时器被清除，不再创建新连接', async () => {
    const w = await mountView()
    socket(0).drop()
    w.unmount()
    vi.advanceTimersByTime(60_000)
    expect(h.sockets.length).toBe(1)
  })
})
