// 服务管理状态与操作 composable：WS 订阅 + 水位管理 + 快照单飞刷新 + 各操作独立 loading 与幂等 request_id
import { computed, inject, onMounted, onUnmounted, ref, type InjectionKey } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import type { EventEnvelope } from '@/api/events'
import { useBackendStore } from '@/stores/backend'
import {
  ApiError,
  SERVICES_ERROR_MESSAGES,
  unwrap,
  type CloudflaredSettings,
  type CodeServerSettings,
  type ServiceBinaries,
  type ServicesConfig,
  type ServicesSnapshot,
} from './api'

export function useServices() {
  const runtime = inject(backendRuntimeKey, null)
  const store = useBackendStore()
  const online = computed(() => store.connection === 'online')

  function api(): ApiClient {
    const a = runtime?.api()
    if (!a) throw new ApiError(0, 'not_connected', '后端未连接')
    return a
  }

  // --- 快照与实时 WS 状态 ---
  const snapshot = ref<ServicesSnapshot | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const watermark = ref(0)

  let removeEventListener: (() => void) | null = null
  let snapshotInFlight = false
  let snapshotPending = false

  async function fetchSnapshot() {
    if (!online.value) return
    if (snapshotInFlight) {
      snapshotPending = true
      return
    }
    snapshotInFlight = true
    try {
      const res = await unwrap(api().GET('/api/services'))
      snapshot.value = res
      error.value = null
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '读取服务状态失败')
      error.value = err.message
    } finally {
      snapshotInFlight = false
      if (snapshotPending && online.value) {
        snapshotPending = false
        void fetchSnapshot()
      }
    }
  }

  function handleEvent(envelope: EventEnvelope) {
    if (envelope.topic !== 'services') return

    if (envelope.type === 'services.subscribed') {
      const data = envelope.data as { last_seq?: number }
      if (typeof data.last_seq === 'number') {
        watermark.value = Math.max(watermark.value, data.last_seq)
      }
      return
    }

    if (envelope.type === 'services.status') {
      const data = envelope.data as { services_seq?: number; snapshot?: ServicesSnapshot }
      const seq = data.services_seq ?? envelope.seq
      if (seq <= watermark.value) return

      watermark.value = seq
      if (data.snapshot) {
        snapshot.value = data.snapshot
        error.value = null
      }
    }
  }

  function subscribe() {
    if (!runtime) return
    runtime.subscribeServices?.(watermark.value)
    void fetchSnapshot()
  }

  function unsubscribe() {
    runtime?.unsubscribeServices?.()
  }

  let protocolNoticeTimer: ReturnType<typeof setTimeout> | null = null

  onMounted(() => {
    if (runtime) {
      removeEventListener = runtime.onEvent(handleEvent)
    }
    subscribe()
  })

  onUnmounted(() => {
    removeEventListener?.()
    removeEventListener = null
    unsubscribe()
    if (protocolNoticeTimer) {
      clearTimeout(protocolNoticeTimer)
      protocolNoticeTimer = null
    }
  })

  // 格式化错误文案
  function formatError(e: unknown): string {
    if (e instanceof ApiError) {
      return SERVICES_ERROR_MESSAGES[e.code] ?? e.message
    }
    if (e instanceof Error) return e.message
    return String(e)
  }

  // --- code-server 操作 ---
  const codeServerStarting = ref(false)
  const codeServerStopping = ref(false)
  const codeServerError = ref<string | null>(null)
  const codeServerLogs = ref<string | null>(null)
  const codeServerLogsLoading = ref(false)
  const codeServerLogsError = ref<string | null>(null)

  async function startCodeServer(): Promise<boolean> {
    codeServerStarting.value = true
    codeServerError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/services/{name}/start', {
          params: { path: { name: 'code-server' } },
          body: {
            ack_public: false,
            request_id: crypto.randomUUID(),
          },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      codeServerError.value = formatError(e)
      return false
    } finally {
      codeServerStarting.value = false
    }
  }

  async function stopCodeServer(): Promise<boolean> {
    codeServerStopping.value = true
    codeServerError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/services/{name}/stop', {
          params: { path: { name: 'code-server' } },
          body: {
            ack_public: false,
            request_id: crypto.randomUUID(),
          },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      codeServerError.value = formatError(e)
      return false
    } finally {
      codeServerStopping.value = false
    }
  }

  async function fetchCodeServerLogs(tail = 65536): Promise<string | null> {
    codeServerLogsLoading.value = true
    codeServerLogsError.value = null
    try {
      const res = await unwrap(
        api().GET('/api/services/{name}/logs', {
          params: {
            path: { name: 'code-server' },
            query: { tail },
          },
        }),
      )
      codeServerLogs.value = res.text
      return res.text
    } catch (e) {
      codeServerLogsError.value = formatError(e)
      return null
    } finally {
      codeServerLogsLoading.value = false
    }
  }

  // --- cloudflared 全局隧道与自定义隧道 ---
  const globalTunnelStarting = ref(false)
  const globalTunnelStopping = ref(false)
  const globalTunnelError = ref<string | null>(null)
  const protocolUpdating = ref(false)
  const protocolNotice = ref<string | null>(null)
  const protocolError = ref<string | null>(null)

  const tunnelCreating = ref(false)
  const tunnelCreateError = ref<string | null>(null)
  const deletingTunnelId = ref<string | null>(null)
  const deleteTunnelError = ref<string | null>(null)

  const legacyImporting = ref(false)
  const legacyImportError = ref<string | null>(null)

  async function startGlobalTunnel(): Promise<boolean> {
    globalTunnelStarting.value = true
    globalTunnelError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/services/{name}/start', {
          params: { path: { name: 'cloudflared' } },
          body: {
            ack_public: false,
            request_id: crypto.randomUUID(),
          },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      globalTunnelError.value = formatError(e)
      return false
    } finally {
      globalTunnelStarting.value = false
    }
  }

  async function stopGlobalTunnel(): Promise<boolean> {
    globalTunnelStopping.value = true
    globalTunnelError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/services/{name}/stop', {
          params: { path: { name: 'cloudflared' } },
          body: {
            ack_public: false,
            request_id: crypto.randomUUID(),
          },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      globalTunnelError.value = formatError(e)
      return false
    } finally {
      globalTunnelStopping.value = false
    }
  }

  async function updateProtocol(protocol: 'http2' | 'quic'): Promise<boolean> {
    protocolUpdating.value = true
    protocolError.value = null
    protocolNotice.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      const res = await unwrap(
        api().POST('/api/services/cloudflared/protocol', {
          body: {
            protocol,
            revision: rev,
          },
        }),
      )
      if (res.restart_required) {
        protocolNotice.value = '协议已变更，需重启隧道后生效'
      }
      await fetchSnapshot()
      return true
    } catch (e) {
      protocolError.value = formatError(e)
      if (e instanceof ApiError && e.code === 'revision_conflict') {
        await fetchSnapshot()
      }
      return false
    } finally {
      protocolUpdating.value = false
    }
  }

  async function createCustomTunnel(targetUrl: string, ackPublic: boolean): Promise<boolean> {
    tunnelCreating.value = true
    tunnelCreateError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/services/cloudflared/tunnels', {
          body: {
            target_url: targetUrl,
            ack_public: ackPublic,
            request_id: crypto.randomUUID(),
          },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      tunnelCreateError.value = formatError(e)
      return false
    } finally {
      tunnelCreating.value = false
    }
  }

  async function deleteCustomTunnel(identifier: string): Promise<boolean> {
    deletingTunnelId.value = identifier
    deleteTunnelError.value = null
    try {
      const res = await unwrap(
        api().DELETE('/api/services/cloudflared/tunnels/{identifier}', {
          params: { path: { identifier } },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      deleteTunnelError.value = formatError(e)
      return false
    } finally {
      deletingTunnelId.value = null
    }
  }

  async function importLegacyPref(path: string): Promise<boolean> {
    legacyImporting.value = true
    legacyImportError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      const res = await unwrap(
        api().POST('/api/services/import-legacy', {
          body: {
            path,
            revision: rev,
          },
        }),
      )
      if (res.restart_required) {
        protocolNotice.value = '已导入协议偏好，需重启隧道后生效'
      }
      await fetchSnapshot()
      return true
    } catch (e) {
      legacyImportError.value = formatError(e)
      if (e instanceof ApiError && e.code === 'revision_conflict') {
        await fetchSnapshot()
      }
      return false
    } finally {
      legacyImporting.value = false
    }
  }

  // --- 设置项 PATCH ---
  const settingsUpdating = ref(false)
  const settingsError = ref<string | null>(null)
  const settingsMessage = ref<string | null>(null)

  async function updateServicesSettings(patch: {
    binaries?: ServiceBinaries
    cloudflared?: CloudflaredSettings
    code_server?: CodeServerSettings
  }): Promise<boolean> {
    settingsUpdating.value = true
    settingsError.value = null
    settingsMessage.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      const current = snapshot.value?.settings ?? {}
      const merged: ServicesConfig = {
        binaries: patch.binaries ?? current.binaries,
        cloudflared: patch.cloudflared ?? current.cloudflared,
        code_server: patch.code_server ?? current.code_server,
      }
      const res = await unwrap(
        api().PATCH('/api/services/settings', {
          body: {
            revision: rev,
            services: merged,
          },
        }),
      )
      if (res.restart_required) {
        protocolNotice.value = '设置已更新，部分配置需重启服务后生效'
      }
      settingsMessage.value = '设置已保存'
      await fetchSnapshot()
      return true
    } catch (e) {
      settingsError.value = formatError(e)
      if (e instanceof ApiError && e.code === 'revision_conflict') {
        await fetchSnapshot()
      }
      return false
    } finally {
      settingsUpdating.value = false
    }
  }

  return {
    snapshot,
    loading,
    error,
    watermark,
    fetchSnapshot,

    // code-server
    codeServerStarting,
    codeServerStopping,
    codeServerError,
    codeServerLogs,
    codeServerLogsLoading,
    codeServerLogsError,
    startCodeServer,
    stopCodeServer,
    fetchCodeServerLogs,

    // cloudflared
    globalTunnelStarting,
    globalTunnelStopping,
    globalTunnelError,
    protocolUpdating,
    protocolNotice,
    protocolError,
    startGlobalTunnel,
    stopGlobalTunnel,
    updateProtocol,

    // custom tunnels
    tunnelCreating,
    tunnelCreateError,
    deletingTunnelId,
    deleteTunnelError,
    createCustomTunnel,
    deleteCustomTunnel,

    // legacy import
    legacyImporting,
    legacyImportError,
    importLegacyPref,

    // settings
    settingsUpdating,
    settingsError,
    settingsMessage,
    updateServicesSettings,
  }
}

export type ServicesContext = ReturnType<typeof useServices>
export const servicesContextKey: InjectionKey<ServicesContext> = Symbol('services-context')

export function useServicesContext(): ServicesContext {
  const ctx = inject(servicesContextKey)
  if (!ctx) {
    throw new Error('useServicesContext must be used within ServicesTab')
  }
  return ctx
}
