import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EventClient, nextBackoff, type ConnectionState } from '@/api/events'
import { FakeSocket, hello, resetSeq, env } from './helpers'

const tick = () => vi.advanceTimersByTimeAsync(0)

function setup(tokens: string[] = ['tok-1']) {
  let n = 0
  const states: ConnectionState[] = []
  const getConnection = vi.fn(async () => {
    const token = tokens[Math.min(n++, tokens.length - 1)]!
    return { port: 5555, token }
  })
  const client = new EventClient({
    getConnection,
    createSocket: (url) => new FakeSocket(url),
    onState: (s) => states.push(s),
  })
  return { client, states, getConnection }
}

describe('EventClient', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeSocket.reset()
    resetSeq()
  })
  afterEach(() => vi.useRealTimers())

  it('backoff 0.5s -> 10s 封顶', () => {
    expect([0, 1, 2, 3, 4, 5, 6].map((a) => nextBackoff(a))).toEqual([
      500, 1000, 2000, 4000, 8000, 10000, 10000,
    ])
  })

  it('connecting -> online -> reconnecting -> online，重连后重新发送 auth', async () => {
    const { client, states, getConnection } = setup(['tok-1', 'tok-2'])
    client.start()
    await tick()
    expect(states).toEqual(['connecting'])
    const s1 = FakeSocket.last()
    expect(s1.url).toBe('ws://127.0.0.1:5555/ws/events')
    s1.open()
    expect(JSON.parse(s1.sent[0]!)).toEqual({ type: 'auth', token: 'tok-1' })
    s1.emit(hello())
    expect(client.state).toBe('online')

    s1.drop()
    expect(client.state).toBe('reconnecting')
    await vi.advanceTimersByTimeAsync(500)
    expect(getConnection).toHaveBeenCalledTimes(2)
    const s2 = FakeSocket.last()
    expect(s2).not.toBe(s1)
    s2.open()
    // 重新取到的新 token 重新 auth
    expect(JSON.parse(s2.sent[0]!)).toEqual({ type: 'auth', token: 'tok-2' })
    s2.emit(hello())
    expect(client.state).toBe('online')
    expect(states).toEqual(['connecting', 'online', 'reconnecting', 'online'])
    client.stop()
  })

  it('token 不出现在 WebSocket URL 中', async () => {
    const { client } = setup(['secret-token-xyz'])
    client.start()
    await tick()
    expect(FakeSocket.last().url).not.toContain('secret-token-xyz')
    client.stop()
  })

  it('重连失败时退避递增，成功后重置', async () => {
    const { client } = setup()
    client.start()
    await tick()
    FakeSocket.last().open()
    FakeSocket.last().emit(hello())
    FakeSocket.last().drop()
    // 第 1 次重连在 500ms
    await vi.advanceTimersByTimeAsync(499)
    expect(FakeSocket.instances).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(FakeSocket.instances).toHaveLength(2)
    FakeSocket.last().drop() // 未 online 就掉线：下一次 1000ms
    await vi.advanceTimersByTimeAsync(999)
    expect(FakeSocket.instances).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(FakeSocket.instances).toHaveLength(3)
    FakeSocket.last().open()
    FakeSocket.last().emit(hello())
    FakeSocket.last().drop() // 成功后重置为 500ms
    await vi.advanceTimersByTimeAsync(500)
    expect(FakeSocket.instances).toHaveLength(4)
    client.stop()
  })

  it('连接信息不可用 -> offline 并持续重试', async () => {
    const getConnection = vi
      .fn()
      .mockRejectedValueOnce(new Error('no conn'))
      .mockResolvedValue({ port: 1234, token: 't' })
    const client = new EventClient({ getConnection, createSocket: (u) => new FakeSocket(u) })
    client.start()
    await tick()
    expect(client.state).toBe('offline')
    await vi.advanceTimersByTimeAsync(500)
    expect(FakeSocket.instances).toHaveLength(1)
    client.stop()
  })

  it('stop 后不再重连并关闭 socket', async () => {
    const { client } = setup()
    client.start()
    await tick()
    const s = FakeSocket.last()
    client.stop()
    expect(s.closed).toBe(true)
    expect(client.state).toBe('offline')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(FakeSocket.instances).toHaveLength(1)
  })

  it('心跳超时视为断线并重连', async () => {
    const states: ConnectionState[] = []
    const client = new EventClient({
      getConnection: async () => ({ port: 1, token: 't' }),
      createSocket: (u) => new FakeSocket(u),
      onState: (s) => states.push(s),
      staleAfterMs: 15_000,
    })
    client.start()
    await tick()
    FakeSocket.last().open()
    FakeSocket.last().emit(hello())
    await vi.advanceTimersByTimeAsync(15_000)
    expect(client.state).toBe('reconnecting')
    client.stop()
  })

  it('心跳事件回调延迟；非法帧被忽略', async () => {
    const lat: number[] = []
    const client = new EventClient({
      getConnection: async () => ({ port: 1, token: 't' }),
      createSocket: (u) => new FakeSocket(u),
      onHeartbeat: (ms) => lat.push(ms),
      now: () => Date.parse('2026-10-22T10:00:00.050Z'),
    })
    client.start()
    await tick()
    const s = FakeSocket.last()
    s.open()
    s.onmessage?.({ data: 'not json' })
    s.onmessage?.({ data: '{"foo":1}' })
    s.emit(env('system.heartbeat', { uptime_s: 1 }, { ts: '2026-10-22T10:00:00.000Z' }))
    expect(lat).toEqual([50])
    client.stop()
  })
})
