// 独立测试的辅助代码（不依赖 tests/unit）。只用假 socket、假定时器、假 token。
import type { BackendConnection } from '@/api/connection'
import type { ConnectionState, EventEnvelope, SocketLike } from '@/api/events'

export const FAKE_TOKEN = 'FAKE-TOKEN-independent-0123'
export const FAKE_PORT = 5555
export const WS_URL = `ws://127.0.0.1:${FAKE_PORT}/ws/events`

export async function flush(): Promise<void> {
  for (let i = 0; i < 30; i++) await Promise.resolve()
}

/** 可控的虚拟时钟：runFor 逐个触发到期任务，并在每次触发前让微任务跑完（保证重试定时器登记时间准确）。 */
export class VirtualClock {
  now = 0
  private seq = 0
  private tasks = new Map<number, { at: number; fn: () => void }>()

  setTimer = (fn: () => void, ms: number): number => {
    const id = ++this.seq
    this.tasks.set(id, { at: this.now + ms, fn })
    return id
  }

  clearTimer = (handle: unknown): void => {
    this.tasks.delete(handle as number)
  }

  get pending(): number {
    return this.tasks.size
  }

  private earliest(): { id: number; at: number; fn: () => void } | undefined {
    let best: { id: number; at: number; fn: () => void } | undefined
    for (const [id, t] of this.tasks) {
      if (!best || t.at < best.at || (t.at === best.at && id < best.id)) {
        best = { id, at: t.at, fn: t.fn }
      }
    }
    return best
  }

  async runFor(ms: number): Promise<void> {
    const end = this.now + ms
    for (;;) {
      await flush()
      const next = this.earliest()
      if (!next || next.at > end) break
      this.now = next.at
      this.tasks.delete(next.id)
      next.fn()
    }
    await flush()
    this.now = end
  }
}

export class FakeSock implements SocketLike {
  onopen: SocketLike['onopen'] = null
  onmessage: SocketLike['onmessage'] = null
  onclose: SocketLike['onclose'] = null
  onerror: SocketLike['onerror'] = null
  sent: string[] = []
  closed = false

  constructor(readonly url: string) {}

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.closed = true
  }

  open(): void {
    this.onopen?.({})
  }

  raw(data: unknown): void {
    this.onmessage?.({ data })
  }

  env(e: EventEnvelope): void {
    this.raw(JSON.stringify(e))
  }

  drop(code = 1006): void {
    this.onclose?.({ code })
  }

  authFrames(): Array<{ type: string; token: string }> {
    return this.sent.map((s) => JSON.parse(s))
  }
}

let seqCounter = 0
export function resetSeqCounter(): void {
  seqCounter = 0
}

export function envelope(
  type: string,
  data: Record<string, unknown>,
  extra: Partial<EventEnvelope> = {},
): EventEnvelope {
  return {
    seq: extra.seq ?? ++seqCounter,
    topic: extra.topic ?? 'system',
    type,
    ts: extra.ts ?? new Date(0).toISOString(),
    data,
  }
}

export const QUIET_ALERT = { active: false, reason: null, changed_at: '2026-10-22T10:00:00Z' }

export const helloEnv = (seq: number, pid = 4242, alert: unknown = QUIET_ALERT) =>
  envelope('system.hello', { pid, version: '0.0.0-indep', alert }, { seq })

export const alertEnv = (seq: number, active: boolean, reason: string | null = null) =>
  envelope('system.alert', { active, reason, changed_at: '2026-10-22T10:01:00Z' }, { seq })

/** 构造 EventClient 的假依赖：可控 token 序列、可控的连接失败次数、记录所有状态与事件。 */
export function clientHarness(
  opts: {
    tokens?: string[]
    failConnections?: number
    failSockets?: number
    staleAfterMs?: number
    deferConnection?: boolean
  } = {},
) {
  const clock = new VirtualClock()
  const sockets: FakeSock[] = []
  const connectionCalls: number[] = []
  const states: ConnectionState[] = []
  const events: EventEnvelope[] = []
  const heartbeats: number[] = []
  const tokens = opts.tokens ?? [FAKE_TOKEN]
  let failConnRemaining = opts.failConnections ?? 0
  let failSockRemaining = opts.failSockets ?? 0
  let connIndex = 0
  let pendingResolve: ((c: BackendConnection) => void) | null = null
  const deferred = opts.deferConnection === true

  const getConnection = async (): Promise<BackendConnection> => {
    connectionCalls.push(clock.now)
    if (deferred) {
      return new Promise<BackendConnection>((res) => {
        pendingResolve = res
      })
    }
    if (failConnRemaining > 0) {
      failConnRemaining--
      throw new Error('fake getConnection failure')
    }
    const token = tokens[Math.min(connIndex, tokens.length - 1)]!
    connIndex++
    return { port: FAKE_PORT, token }
  }

  const createSocket = (url: string): FakeSock => {
    if (failSockRemaining > 0) {
      failSockRemaining--
      throw new Error('fake createSocket failure')
    }
    const s = new FakeSock(url)
    sockets.push(s)
    return s
  }

  return {
    clock,
    sockets,
    connectionCalls,
    states,
    events,
    heartbeats,
    resolveDeferred(conn: BackendConnection) {
      pendingResolve?.(conn)
      pendingResolve = null
    },
    options: {
      getConnection,
      createSocket,
      now: () => clock.now,
      setTimer: clock.setTimer,
      clearTimer: clock.clearTimer,
      onState: (s: ConnectionState) => states.push(s),
      onEvent: (e: EventEnvelope) => events.push(e),
      onHeartbeat: (ms: number) => heartbeats.push(ms),
      staleAfterMs: opts.staleAfterMs,
    },
  }
}
