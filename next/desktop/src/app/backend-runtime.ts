import type { InjectionKey } from 'vue'
import { createApiClient, type ApiClient } from '@/api/client'
import type { BackendConnection } from '@/api/connection'
import { EventClient, type EventClientOptions } from '@/api/events'
import { useBackendStore } from '@/stores/backend'

export interface BackendRuntime {
  /** 当前连接的 API 客户端；尚未取得连接信息时为 null。 */
  api(): ApiClient | null
  start(): void
  stop(): void
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
    start: () => events.start(),
    stop: () => events.stop(),
  }
}
