import type { InjectionKey } from 'vue'
import { createApiClient, type ApiClient } from '@/api/client'
import type { BackendConnection } from '@/api/connection'
import { EventClient, type EventClientOptions, type EventEnvelope } from '@/api/events'
import { useBackendStore } from '@/stores/backend'

export interface BackendRuntime {
  /** 当前连接的 API 客户端；尚未取得连接信息时为 null。 */
  api(): ApiClient | null
  /** 当前后端连接信息（含端口与 token）；尚未取得连接信息时为 null。token 不落盘。 */
  getConnection?(): BackendConnection | null
  start(): void
  stop(): void
  /** 发送已认证的 WS 客户端消息（如 subscribe/unsubscribe）；未连接或未就绪时返回 false */
  send(message: Record<string, unknown> | string): boolean
  /** 订阅 run 日志 */
  subscribeRun(runId: string, afterSeq?: number): boolean
  /** 退订 run 日志 */
  unsubscribeRun(runId: string): boolean
  /** 订阅 ai 主题 */
  subscribeAi?(sessionId?: string, afterSeq?: number): boolean
  /** 退订 ai 主题 */
  unsubscribeAi?(sessionId?: string): boolean
  /** 订阅 mcp 主题 */
  subscribeMcp?(afterSeq?: number): boolean
  /** 退订 mcp 主题 */
  unsubscribeMcp?(): boolean
  /** 订阅 services 主题 */
  subscribeServices?(afterSeq?: number): boolean
  /** 退订 services 主题 */
  unsubscribeServices?(): boolean
  /** 注册事件监听器，返回解除监听的回调 */
  onEvent(listener: (event: EventEnvelope) => void): () => void
}

export const backendRuntimeKey: InjectionKey<BackendRuntime> = Symbol('backend-runtime')

export interface RuntimeDeps {
  events?: Omit<EventClientOptions, 'onState' | 'onConnection' | 'onEvent' | 'onHeartbeat'>
  fetch?: typeof fetch
}

/** 把 EventClient 接到 Pinia store；连接信息在内存，随每次（重）连刷新。 */
export function createBackendRuntime(deps: RuntimeDeps = {}): BackendRuntime {
  const store = useBackendStore()
  let conn: BackendConnection | null = null
  let client: ApiClient | null = null
  const events = new EventClient({
    ...deps.events,
    onState: (s) => store.setConnection(s),
    onConnection: (c) => {
      conn = c
      client = createApiClient(c, deps.fetch)
    },
    onEvent: (e) => store.applyEvent(e),
    onHeartbeat: (ms) => store.setLatency(ms),
  })
  return {
    api: () => (conn ? client : null),
    getConnection: () => conn,
    start: () => events.start(),
    stop: () => events.stop(),
    send: (msg) => events.send(msg),
    subscribeRun: (runId, afterSeq) => events.subscribeRun(runId, afterSeq),
    unsubscribeRun: (runId) => events.unsubscribeRun(runId),
    subscribeAi: (sessionId, afterSeq) => events.subscribeAi(sessionId, afterSeq),
    unsubscribeAi: (sessionId) => events.unsubscribeAi(sessionId),
    subscribeMcp: (afterSeq) => events.subscribeMcp(afterSeq),
    unsubscribeMcp: () => events.unsubscribeMcp(),
    subscribeServices: (afterSeq) => events.subscribeServices(afterSeq),
    unsubscribeServices: () => events.unsubscribeServices(),
    onEvent: (listener) => events.addEventListener(listener),
  }
}
