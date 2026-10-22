// EventClient 故障路径（独立编写）：假 socket、虚拟时钟，不连真实后端。
import { describe, expect, it } from 'vitest'
import { EventClient, nextBackoff } from '@/api/events'
import {
  FAKE_TOKEN,
  WS_URL,
  alertEnv,
  clientHarness,
  envelope,
  flush,
  helloEnv,
  resetSeqCounter,
} from './support'

const STALE = 15_000

describe('EventClient 正常路径与状态机', () => {
  it('connecting→online→reconnecting→online，重连后用新 socket 与新 token 重新发 auth，URL 不含 token', async () => {
    resetSeqCounter()
    const h = clientHarness({ tokens: ['TOKEN-ONE', 'TOKEN-TWO'] })
    const c = new EventClient(h.options)
    c.start()
    await flush()
    expect(h.states).toEqual(['connecting'])

    const s1 = h.sockets[0]!
    expect(s1.url).toBe(WS_URL)
    s1.open()
    expect(s1.authFrames()).toEqual([{ type: 'auth', token: 'TOKEN-ONE' }])
    expect(h.states).toEqual(['connecting'])

    s1.env(helloEnv(1))
    await flush()
    expect(c.state).toBe('online')

    s1.drop(1006)
    expect(c.state).toBe('reconnecting')
    await h.clock.runFor(500)

    expect(h.sockets).toHaveLength(2)
    const s2 = h.sockets[1]!
    expect(s2.url).toBe(WS_URL)
    expect(s2.url).not.toContain('TOKEN')
    expect(s2.url).not.toContain('token')
    s2.open()
    expect(s2.authFrames()).toEqual([{ type: 'auth', token: 'TOKEN-TWO' }])

    s2.env(helloEnv(2))
    await flush()
    expect(h.states).toEqual(['connecting', 'online', 'reconnecting', 'online'])
    c.stop()
  })

  it('同一 start() 重复调用不会创建第二个 socket', async () => {
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    c.start()
    await flush()
    expect(h.sockets).toHaveLength(1)
    c.stop()
  })

  it('重复收到 hello 保持 online，不产生多余状态切换', async () => {
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    await flush()
    h.sockets[0]!.open()
    h.sockets[0]!.env(helloEnv(1))
    h.sockets[0]!.env(helloEnv(2))
    await flush()
    expect(h.states).toEqual(['connecting', 'online'])
    c.stop()
  })
})

describe('EventClient 故障路径：握手前后的帧与关闭', () => {
  it('WebSocket 在 open 之前就被关闭：不发送 auth，保持 connecting，500ms 后重试', async () => {
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    await flush()
    h.sockets[0]!.drop(4401)
    expect(c.state).toBe('connecting')
    expect(h.sockets[0]!.sent).toEqual([])
    await h.clock.runFor(499)
    expect(h.sockets).toHaveLength(1)
    await h.clock.runFor(1)
    expect(h.sockets).toHaveLength(2)
    c.stop()
  })

  it('auth 已发出但 hello 之前连接被关闭（服务端 4401）：不进入 online', async () => {
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    await flush()
    h.sockets[0]!.open()
    h.sockets[0]!.drop(4401)
    expect(c.state).toBe('connecting')
    expect(h.states).not.toContain('online')
    c.stop()
  })

  it('hello 之前收到 heartbeat / alert：不切换到 online', async () => {
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    await flush()
    const s = h.sockets[0]!
    s.open()
    s.env(envelope('system.heartbeat', { uptime_s: 1 }, { seq: 1 }))
    s.env(alertEnv(2, true, 'before hello'))
    await flush()
    expect(c.state).toBe('connecting')
    expect(h.states).toEqual(['connecting'])
    c.stop()
  })

  it('非 JSON、缺字段、data 为 null、非字符串帧全部忽略且不抛出', async () => {
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    await flush()
    const s = h.sockets[0]!
    s.open()
    const bad: unknown[] = [
      'not json{',
      '',
      'null',
      '[]',
      '123',
      JSON.stringify({ seq: '1', topic: 'system', type: 'system.hello', ts: 'x', data: {} }),
      JSON.stringify({ seq: 1, topic: 'system', type: 'system.hello', ts: 'x' }),
      JSON.stringify({ seq: 1, topic: 'system', type: 'system.hello', ts: 'x', data: null }),
      JSON.stringify({ seq: 1, topic: 'system', ts: 'x', data: {} }),
      JSON.stringify({ seq: 1, topic: 'system', type: 'system.hello', data: {} }),
      42,
      { not: 'a string' },
      null,
    ]
    for (const frame of bad) {
      expect(() => s.raw(frame)).not.toThrow()
    }
    await flush()
    expect(h.events).toEqual([])
    expect(c.state).toBe('connecting')
    c.stop()
  })

  it('重连后旧 socket 迟到的 hello 被忽略（不得把新连接置为 online）', async () => {
    resetSeqCounter()
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    await flush()
    const s1 = h.sockets[0]!
    s1.open()
    s1.env(helloEnv(1))
    await flush()
    const staleOnMessage = s1.onmessage
    s1.drop(1006)
    await h.clock.runFor(500)
    expect(h.sockets).toHaveLength(2)
    expect(c.state).toBe('reconnecting')

    // 旧 socket 的处理函数若仍被调用，必须不改变状态
    staleOnMessage?.({ data: JSON.stringify(helloEnv(9)) })
    await flush()
    expect(c.state).toBe('reconnecting')
    expect(h.events.filter((e) => e.type === 'system.hello')).toHaveLength(1)
    c.stop()
  })
})

describe('EventClient 故障路径：心跳超时与退避', () => {
  it('心跳持续到达则不重连；超过 staleAfterMs 无任何帧则判定断线并重连', async () => {
    const h = clientHarness({ staleAfterMs: STALE })
    const c = new EventClient(h.options)
    c.start()
    await flush()
    const s = h.sockets[0]!
    s.open()
    s.env(helloEnv(1))
    await flush()
    for (let i = 0; i < 6; i++) {
      await h.clock.runFor(5_000)
      s.env(envelope('system.heartbeat', { uptime_s: i }, { seq: 2 + i }))
    }
    expect(h.sockets).toHaveLength(1)
    expect(c.state).toBe('online')
    expect(s.closed).toBe(false)

    await h.clock.runFor(STALE)
    expect(s.closed).toBe(true)
    expect(c.state).toBe('reconnecting')
    expect(h.sockets).toHaveLength(1)
    await h.clock.runFor(500)
    expect(h.sockets).toHaveLength(2)
    c.stop()
  })

  it('心跳延迟 = 本机当前时间 - 信封 ts，且不为负', async () => {
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    await flush()
    const s = h.sockets[0]!
    s.open()
    s.env(helloEnv(1))
    await flush()
    // ts 为 epoch 0；本机时钟推进到 250ms
    await h.clock.runFor(250)
    s.env(envelope('system.heartbeat', { uptime_s: 1 }, { seq: 2, ts: new Date(0).toISOString() }))
    // ts 在未来（时钟偏差）时不得出现负延迟
    s.env(
      envelope(
        'system.heartbeat',
        { uptime_s: 2 },
        {
          seq: 3,
          ts: new Date(10_000_000).toISOString(),
        },
      ),
    )
    await flush()
    expect(h.heartbeats).toEqual([250, 0])
    c.stop()
  })

  it('持续 getConnection 失败：退避序列 500,1000,2000,4000,8000 然后封顶 10000', async () => {
    const h = clientHarness({ failConnections: 1_000 })
    const c = new EventClient(h.options)
    c.start()
    await h.clock.runFor(120_000)
    const calls = h.connectionCalls
    expect(calls.length).toBeGreaterThanOrEqual(12)
    const deltas = calls.slice(1).map((t, i) => t - calls[i]!)
    expect(deltas.slice(0, 5)).toEqual([500, 1000, 2000, 4000, 8000])
    for (const d of deltas.slice(5)) expect(d).toBe(10_000)
    expect(nextBackoff(0)).toBe(500)
    expect(nextBackoff(100)).toBe(10_000)
    c.stop()
  })

  it('hello 成功后退避计数清零：下一次断线从 500ms 重新开始', async () => {
    const h = clientHarness({ failConnections: 3 })
    const c = new EventClient(h.options)
    c.start()
    // 三次失败后第 4 次成功（delays: 500, 1000, 2000）
    await h.clock.runFor(3_500)
    expect(h.sockets).toHaveLength(1)
    h.sockets[0]!.open()
    h.sockets[0]!.env(helloEnv(1))
    await flush()
    expect(c.state).toBe('online')

    const dropAt = h.clock.now
    h.sockets[0]!.drop(1006)
    await h.clock.runFor(500)
    expect(h.connectionCalls[h.connectionCalls.length - 1]).toBe(dropAt + 500)
    c.stop()
  })

  it('getConnection 先失败后成功：最终进入 online，失败期间不处于 online', async () => {
    const h = clientHarness({ failConnections: 2 })
    const c = new EventClient(h.options)
    c.start()
    await flush()
    expect(c.state).not.toBe('online')
    await h.clock.runFor(1_500)
    expect(h.sockets).toHaveLength(1)
    expect(c.state).not.toBe('online')
    h.sockets[0]!.open()
    h.sockets[0]!.env(helloEnv(1))
    await flush()
    expect(c.state).toBe('online')
    c.stop()
  })

  it('createSocket 抛错不会导致 start 抛出，之后按退避重试', async () => {
    const h = clientHarness({ failSockets: 2 })
    const c = new EventClient(h.options)
    expect(() => c.start()).not.toThrow()
    await h.clock.runFor(5_000)
    expect(h.sockets).toHaveLength(1)
    h.sockets[0]!.open()
    h.sockets[0]!.env(helloEnv(1))
    await flush()
    expect(c.state).toBe('online')
    c.stop()
  })
})

describe('EventClient 故障路径：stop() 与生命周期', () => {
  it('stop() 后不再调用 getConnection、不再创建 socket、没有残留定时器', async () => {
    const h = clientHarness({ failConnections: 1_000 })
    const c = new EventClient(h.options)
    c.start()
    await h.clock.runFor(2_000)
    const callsBefore = h.connectionCalls.length
    c.stop()
    expect(c.state).toBe('offline')
    await h.clock.runFor(120_000)
    expect(h.connectionCalls.length).toBe(callsBefore)
    expect(h.clock.pending).toBe(0)
    expect(h.sockets).toHaveLength(0)
  })

  it('stop() 后旧 socket 的 close 回调不会触发重连', async () => {
    const h = clientHarness()
    const c = new EventClient(h.options)
    c.start()
    await flush()
    const s = h.sockets[0]!
    s.open()
    s.env(helloEnv(1))
    await flush()
    const oldOnClose = s.onclose
    c.stop()
    expect(s.closed).toBe(true)
    oldOnClose?.({ code: 1006 })
    await h.clock.runFor(60_000)
    expect(h.sockets).toHaveLength(1)
    expect(c.state).toBe('offline')
    expect(h.clock.pending).toBe(0)
  })

  it('getConnection 挂起期间 stop()：之后解析出的连接不会创建 socket', async () => {
    const h = clientHarness({ deferConnection: true })
    const c = new EventClient(h.options)
    c.start()
    await flush()
    c.stop()
    h.resolveDeferred({ port: 5555, token: FAKE_TOKEN })
    await flush()
    await h.clock.runFor(5_000)
    expect(h.sockets).toHaveLength(0)
    expect(c.state).toBe('offline')
  })

  it('stop() 之后可以再次 start()，并且使用新的连接', async () => {
    const h = clientHarness({ tokens: ['T-A', 'T-B'] })
    const c = new EventClient(h.options)
    c.start()
    await flush()
    h.sockets[0]!.open()
    h.sockets[0]!.env(helloEnv(1))
    await flush()
    c.stop()
    c.start()
    await flush()
    expect(h.sockets).toHaveLength(2)
    h.sockets[1]!.open()
    expect(h.sockets[1]!.authFrames()).toEqual([{ type: 'auth', token: 'T-B' }])
    c.stop()
  })
})
