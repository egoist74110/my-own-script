// 后端事件订阅：WebSocket 连接状态机 + 指数退避重连 + 重连后重新取连接信息并重新 auth。
import { getBackendConnection, wsUrl, type BackendConnection } from './connection'
import type { components } from './schema'

export type AlertState = components['schemas']['AlertState']
export type RunEventData = components['schemas']['RunEventData']
export interface RunSubscribedData {
  run_id: string
  last_seq: number
}

export type ConnectionState = 'connecting' | 'online' | 'reconnecting' | 'offline'

export interface TelegramStatusEventData {
  state: components['schemas']['PollerView']['state']
  since: string
  slot?: string
  last_error_category?: string | null
}

export interface AISessionData {
  session_id: string
  state: 'starting' | 'idle' | 'busy' | 'awaiting_approval' | 'closing' | 'ended' | 'failed'
  ended_reason?: string | null
  last_seq: number
}

export interface AIJobData {
  job_id: string
  state: 'running' | 'succeeded' | 'failed' | 'cancelled'
  exit_code?: number | null
  output?: string
}

export interface AISubscribedData {
  session_id: string
  last_seq: number
}

export interface AIEventData {
  session_id: string
  session_seq: number
  ts: string
  kind:
    | 'init'
    | 'assistant'
    | 'thinking'
    | 'tool_use'
    | 'tool_result'
    | 'turn_started'
    | 'turn_completed'
    | 'turn_failed'
    | 'approval'
    | 'notice'
    | 'error'
    | 'exit'
  payload: Record<string, unknown>
}

export interface EventEnvelope {
  seq: number
  topic: string
  type: string
  ts: string
  data: Record<string, unknown>
}

export interface HelloData {
  pid: number
  version: string
  alert: AlertState
}

export interface SocketLike {
  onopen: ((ev: unknown) => void) | null
  onmessage: ((ev: { data: unknown }) => void) | null
  onclose: ((ev: { code: number }) => void) | null
  onerror: ((ev: unknown) => void) | null
  send(data: string): void
  close(code?: number): void
}

export interface EventClientOptions {
  getConnection?: () => Promise<BackendConnection>
  createSocket?: (url: string) => SocketLike
  now?: () => number
  setTimer?: (fn: () => void, ms: number) => unknown
  clearTimer?: (handle: unknown) => void
  onState?: (state: ConnectionState) => void
  onConnection?: (conn: BackendConnection) => void
  onEvent?: (event: EventEnvelope) => void
  onHeartbeat?: (latencyMs: number) => void
  onRunEvent?: (data: components['schemas']['RunEventData'], envelope: EventEnvelope) => void
  onRunSubscribed?: (data: RunSubscribedData, envelope: EventEnvelope) => void
  onTelegramStatus?: (data: TelegramStatusEventData, envelope: EventEnvelope) => void
  onAiSession?: (data: AISessionData, envelope: EventEnvelope) => void
  onAiJob?: (data: AIJobData, envelope: EventEnvelope) => void
  onAiSubscribed?: (data: AISubscribedData, envelope: EventEnvelope) => void
  onAiEvent?: (data: AIEventData, envelope: EventEnvelope) => void
  /** 超过此时间没收到任何事件视为连接已死（后端心跳间隔 5s）。 */
  staleAfterMs?: number
  backoff?: { initialMs: number; maxMs: number }
}

const DEFAULT_BACKOFF = { initialMs: 500, maxMs: 10_000 }

export function nextBackoff(attempt: number, cfg = DEFAULT_BACKOFF): number {
  return Math.min(cfg.initialMs * 2 ** attempt, cfg.maxMs)
}

function isEnvelope(v: unknown): v is EventEnvelope {
  if (typeof v !== 'object' || v === null) return false
  const e = v as Record<string, unknown>
  return (
    typeof e.seq === 'number' &&
    typeof e.topic === 'string' &&
    typeof e.type === 'string' &&
    typeof e.ts === 'string' &&
    typeof e.data === 'object' &&
    e.data !== null
  )
}

export class EventClient {
  private readonly opts: Required<
    Pick<EventClientOptions, 'getConnection' | 'createSocket' | 'now' | 'setTimer' | 'clearTimer'>
  > &
    EventClientOptions
  private readonly backoff: { initialMs: number; maxMs: number }
  private socket: SocketLike | null = null
  private retryTimer: unknown = null
  private staleTimer: unknown = null
  private attempt = 0
  private stopped = true
  private everOnline = false
  private generation = 0
  private _state: ConnectionState = 'offline'
  private listeners = new Set<(event: EventEnvelope) => void>()

  constructor(options: EventClientOptions = {}) {
    this.opts = {
      getConnection: () => getBackendConnection(),
      createSocket: (url) => new WebSocket(url) as unknown as SocketLike,
      now: () => Date.now(),
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
      ...options,
    }
    this.backoff = options.backoff ?? DEFAULT_BACKOFF
  }

  get state(): ConnectionState {
    return this._state
  }

  /** 发送已认证的 WS 客户端消息（如 run 订阅）；仅在 online 状态下发出。返回是否已发送。 */
  send(data: string | Record<string, unknown>): boolean {
    if (this._state !== 'online' || !this.socket) return false
    try {
      this.socket.send(typeof data === 'string' ? data : JSON.stringify(data))
      return true
    } catch {
      return false
    }
  }

  /** 订阅 run 日志 */
  subscribeRun(runId: string, afterSeq = 0): boolean {
    return this.send({
      type: 'subscribe',
      topic: 'run',
      run_id: runId,
      after_seq: afterSeq,
    })
  }

  /** 退订 run 日志 */
  unsubscribeRun(runId: string): boolean {
    return this.send({
      type: 'unsubscribe',
      topic: 'run',
      run_id: runId,
    })
  }

  /** 订阅 ai 主题 */
  subscribeAi(sessionId?: string, afterSeq = 0): boolean {
    return this.send({
      type: 'subscribe',
      topic: 'ai',
      ...(sessionId ? { session_id: sessionId } : {}),
      after_seq: afterSeq,
    })
  }

  /** 退订 ai 主题 */
  unsubscribeAi(sessionId?: string): boolean {
    return this.send({
      type: 'unsubscribe',
      topic: 'ai',
      ...(sessionId ? { session_id: sessionId } : {}),
    })
  }

  /** 注册事件监听器，返回解除监听的回调 */
  addEventListener(listener: (event: EventEnvelope) => void): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  start(): void {
    if (!this.stopped) return
    this.stopped = false
    this.attempt = 0
    this.everOnline = false
    this.setState('connecting')
    void this.connect()
  }

  stop(): void {
    this.stopped = true
    this.generation++
    this.clearTimers()
    this.detachSocket()
    this.setState('offline')
  }

  private setState(next: ConnectionState): void {
    if (this._state === next) return
    this._state = next
    this.opts.onState?.(next)
  }

  private clearTimers(): void {
    if (this.retryTimer !== null) this.opts.clearTimer(this.retryTimer)
    if (this.staleTimer !== null) this.opts.clearTimer(this.staleTimer)
    this.retryTimer = null
    this.staleTimer = null
  }

  private detachSocket(): void {
    const s = this.socket
    this.socket = null
    if (!s) return
    s.onopen = s.onmessage = s.onclose = s.onerror = null
    try {
      s.close()
    } catch {
      // 已关闭的 socket 再关闭无需处理
    }
  }

  private async connect(): Promise<void> {
    const gen = ++this.generation
    let conn: BackendConnection
    try {
      conn = await this.opts.getConnection()
    } catch {
      if (this.stopped || gen !== this.generation) return
      this.setState(this.everOnline ? 'reconnecting' : 'offline')
      this.scheduleRetry()
      return
    }
    if (this.stopped || gen !== this.generation) return
    this.opts.onConnection?.(conn)
    let socket: SocketLike
    try {
      socket = this.opts.createSocket(wsUrl(conn))
    } catch {
      this.setState(this.everOnline ? 'reconnecting' : 'offline')
      this.scheduleRetry()
      return
    }
    this.socket = socket
    socket.onopen = () => {
      // 每次（重）连都用本次取到的 token 重新 auth；token 不进 URL。
      socket.send(JSON.stringify({ type: 'auth', token: conn.token }))
      this.armStaleTimer(gen)
    }
    socket.onmessage = (ev) => this.handleMessage(gen, ev.data)
    socket.onclose = () => this.handleClose(gen)
    socket.onerror = () => {
      // 随后会触发 close，由 close 统一处理
    }
  }

  private handleMessage(gen: number, raw: unknown): void {
    if (gen !== this.generation || typeof raw !== 'string') return
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      return
    }
    if (!isEnvelope(parsed)) return
    this.armStaleTimer(gen)
    if (parsed.type === 'system.hello' && parsed.topic === 'system') {
      this.attempt = 0
      this.everOnline = true
      this.setState('online')
    }
    if (parsed.type === 'system.heartbeat') {
      const sent = Date.parse(parsed.ts)
      if (!Number.isNaN(sent)) {
        this.opts.onHeartbeat?.(Math.max(0, this.opts.now() - sent))
      }
    }
    if (parsed.type === 'telegram.status') {
      this.opts.onTelegramStatus?.(parsed.data as unknown as TelegramStatusEventData, parsed)
    }
    if (parsed.topic === 'run') {
      if (parsed.type === 'run.event') {
        this.opts.onRunEvent?.(parsed.data as components['schemas']['RunEventData'], parsed)
      } else if (parsed.type === 'run.subscribed') {
        this.opts.onRunSubscribed?.(parsed.data as unknown as RunSubscribedData, parsed)
      }
    }
    if (parsed.topic === 'ai') {
      if (parsed.type === 'ai.session') {
        this.opts.onAiSession?.(parsed.data as unknown as AISessionData, parsed)
      } else if (parsed.type === 'ai.job') {
        this.opts.onAiJob?.(parsed.data as unknown as AIJobData, parsed)
      } else if (parsed.type === 'ai.subscribed') {
        this.opts.onAiSubscribed?.(parsed.data as unknown as AISubscribedData, parsed)
      } else if (parsed.type === 'ai.event') {
        this.opts.onAiEvent?.(parsed.data as unknown as AIEventData, parsed)
      }
    }
    this.opts.onEvent?.(parsed)
    for (const listener of this.listeners) {
      try {
        listener(parsed)
      } catch {
        // 监听器异常不破坏客户端
      }
    }
  }

  private handleClose(gen: number): void {
    if (gen !== this.generation || this.stopped) return
    this.detachSocket()
    if (this.staleTimer !== null) this.opts.clearTimer(this.staleTimer)
    this.staleTimer = null
    this.setState(this.everOnline ? 'reconnecting' : 'connecting')
    this.scheduleRetry()
  }

  private armStaleTimer(gen: number): void {
    if (this.staleTimer !== null) this.opts.clearTimer(this.staleTimer)
    const ms = this.opts.staleAfterMs ?? 15_000
    this.staleTimer = this.opts.setTimer(() => {
      if (gen === this.generation && !this.stopped) this.handleClose(gen)
    }, ms)
  }

  private scheduleRetry(): void {
    if (this.stopped) return
    if (this.retryTimer !== null) this.opts.clearTimer(this.retryTimer)
    const delay = nextBackoff(this.attempt, this.backoff)
    this.attempt++
    this.retryTimer = this.opts.setTimer(() => {
      this.retryTimer = null
      void this.connect()
    }, delay)
  }
}
