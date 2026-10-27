// VPN 状态与操作 composable：WS 订阅 + 水位管理 + 快照单飞刷新 + 凭据只写与 MFA Sheet 管理
import { computed, inject, onMounted, onUnmounted, ref, type InjectionKey } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import type {
  EventEnvelope,
  VpnCredentialConfiguredData,
  VpnMfaRequiredData,
  VpnRunEventData,
  VpnStatusData,
  VpnSubscribedData,
} from '@/api/events'
import { useBackendStore } from '@/stores/backend'
import {
  ApiError,
  unwrap,
  vpnErrorMessage,
  type VpnConfig,
  type VpnRunView,
  type VpnSnapshot,
} from './api'

export interface TotpCandidate {
  issuer: string
  label: string
  index: number
}

export interface TotpImportResult {
  ambiguous: boolean
  items?: TotpCandidate[]
}

export function useVpn() {
  const runtime = inject(backendRuntimeKey, null)
  const store = useBackendStore()
  const online = computed(() => store.connection === 'online')

  function api(): ApiClient {
    const a = runtime?.api()
    if (!a) throw new ApiError(0, 'not_connected', '后端未连接')
    return a
  }

  // --- 状态与水位 ---
  const snapshot = ref<VpnSnapshot | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const notice = ref<string | null>(null)
  const watermark = ref(0)
  const actionLoading = ref<string | null>(null)

  // 运行时间线步骤
  const timelineEvents = ref<VpnRunEventData[]>([])

  // MFA 弹窗状态
  const mfaModalOpen = ref(false)
  const mfaRunId = ref<string | null>(null)
  const mfaSecondsLeft = ref(120)
  const mfaError = ref<string | null>(null)
  let mfaTimer: ReturnType<typeof setInterval> | null = null

  let removeEventListener: (() => void) | null = null
  let snapshotInFlight = false
  let snapshotPending = false

  function clearNotice() {
    notice.value = null
  }

  function clearError() {
    error.value = null
  }

  function openMfa(runId: string, expiresInS = 120) {
    if (mfaTimer) {
      clearInterval(mfaTimer)
      mfaTimer = null
    }
    mfaRunId.value = runId
    mfaSecondsLeft.value = expiresInS > 0 ? expiresInS : 120
    mfaError.value = null
    mfaModalOpen.value = true

    mfaTimer = setInterval(() => {
      if (mfaSecondsLeft.value > 1) {
        mfaSecondsLeft.value--
      } else {
        closeMfa('MFA 验证码输入超时已关闭')
      }
    }, 1000)
  }

  function closeMfa(reason?: string) {
    if (mfaTimer) {
      clearInterval(mfaTimer)
      mfaTimer = null
    }
    mfaModalOpen.value = false
    mfaRunId.value = null
    mfaSecondsLeft.value = 120
    if (reason) {
      mfaError.value = reason
    }
  }

  async function fetchSnapshot() {
    if (!online.value) return
    if (snapshotInFlight) {
      snapshotPending = true
      return
    }
    snapshotInFlight = true
    try {
      const res = await unwrap(api().GET('/api/vpn'))
      snapshot.value = res
      error.value = null

      // 同步当前运行事件列表
      if (res.current_run?.events && Array.isArray(res.current_run.events)) {
        const rawEvents = res.current_run.events as unknown as VpnRunEventData[]
        if (
          timelineEvents.value.length === 0 ||
          res.current_run.run_id !== timelineEvents.value[0]?.run_id
        ) {
          timelineEvents.value = [...rawEvents].sort((a, b) => a.run_seq - b.run_seq)
        }
      }
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '读取 VPN 状态失败')
      error.value = vpnErrorMessage(err.code, err.message)
    } finally {
      snapshotInFlight = false
      if (snapshotPending && online.value) {
        snapshotPending = false
        void fetchSnapshot()
      }
    }
  }

  function handleEvent(envelope: EventEnvelope) {
    if (envelope.topic !== 'vpn') return

    if (envelope.type === 'vpn.subscribed') {
      const data = envelope.data as unknown as VpnSubscribedData
      if (typeof data.last_seq === 'number') {
        watermark.value = Math.max(watermark.value, data.last_seq)
      }
      return
    }

    if (envelope.type === 'vpn.status') {
      const data = envelope.data as unknown as VpnStatusData
      const seq = data.vpn_seq ?? envelope.seq
      if (seq <= watermark.value) return
      watermark.value = seq

      if (snapshot.value) {
        snapshot.value.connected = data.connected
        snapshot.value.ip = data.ip ?? null
        if (data.client) {
          snapshot.value.client = data.client
        }
        if (data.current_run) {
          if (snapshot.value.current_run) {
            snapshot.value.current_run.run_id = data.current_run.run_id
            snapshot.value.current_run.state = data.current_run.state as VpnRunView['state']
            snapshot.value.current_run.rung = data.current_run.rung
          } else {
            void fetchSnapshot()
          }
        } else if (snapshot.value.current_run) {
          snapshot.value.current_run = null
        }
        error.value = null
      } else {
        void fetchSnapshot()
      }
      return
    }

    if (envelope.type === 'vpn.run') {
      const data = envelope.data as unknown as VpnRunEventData
      const seq = data.vpn_seq ?? envelope.seq
      if (seq <= watermark.value) return
      watermark.value = seq

      // 更新步骤时间线
      const evs = [...timelineEvents.value]
      const idx = evs.findIndex((e) => e.run_id === data.run_id && e.run_seq === data.run_seq)
      if (idx >= 0) {
        evs[idx] = data
      } else {
        evs.push(data)
      }
      evs.sort((a, b) => a.run_seq - b.run_seq)
      timelineEvents.value = evs

      // 更新快照中的 current_run
      if (snapshot.value?.current_run && snapshot.value.current_run.run_id === data.run_id) {
        snapshot.value.current_run.state = data.state as VpnRunView['state']
        snapshot.value.current_run.rung = data.rung
        if (data.error_code) {
          snapshot.value.current_run.error_code = data.error_code
        }
        if (data.ip) {
          snapshot.value.current_run.ip = data.ip
        }
      }
      return
    }

    if (envelope.type === 'vpn.mfa_required') {
      const data = envelope.data as unknown as VpnMfaRequiredData
      const seq = data.vpn_seq ?? envelope.seq
      if (seq <= watermark.value) return
      watermark.value = seq

      openMfa(data.run_id, data.expires_in_s)
      return
    }

    if (envelope.type === 'vpn.credentials') {
      const data = envelope.data as unknown as VpnCredentialConfiguredData
      if (snapshot.value?.credentials) {
        if (data.kind === 'vpn_password') {
          snapshot.value.credentials.password = data.configured
        } else if (data.kind === 'vpn_totp_secret') {
          snapshot.value.credentials.totp_secret = data.configured
        }
      }
    }
  }

  function subscribe() {
    if (!runtime) return
    runtime.subscribeVpn?.(watermark.value)
    void fetchSnapshot()
  }

  function unsubscribe() {
    runtime?.unsubscribeVpn?.()
  }

  // --- 操作方法 ---
  async function connect(maxRung?: 0 | 1 | 2 | 3): Promise<boolean> {
    actionLoading.value = 'connect'
    error.value = null
    timelineEvents.value = []
    try {
      const run = await unwrap(
        api().POST('/api/vpn/connect', {
          body: {
            max_rung: maxRung,
            allow_login: true,
          },
        }),
      )
      if (snapshot.value) {
        snapshot.value.current_run = run
      }
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '发起连接失败')
      error.value = vpnErrorMessage(err.code, err.message)
      return false
    } finally {
      actionLoading.value = null
    }
  }

  async function relogin(): Promise<boolean> {
    actionLoading.value = 'relogin'
    error.value = null
    timelineEvents.value = []
    try {
      const run = await unwrap(
        api().POST('/api/vpn/relogin', {
          body: {
            allow_login: true,
          },
        }),
      )
      if (snapshot.value) {
        snapshot.value.current_run = run
      }
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '强制重登失败')
      error.value = vpnErrorMessage(err.code, err.message)
      return false
    } finally {
      actionLoading.value = null
    }
  }

  async function cancelRun(runId?: string): Promise<boolean> {
    const id = runId ?? snapshot.value?.current_run?.run_id
    if (!id) return false
    actionLoading.value = 'cancel'
    error.value = null
    try {
      const run = await unwrap(
        api().POST('/api/vpn/runs/{run_id}/cancel', {
          params: { path: { run_id: id } },
        }),
      )
      if (snapshot.value?.current_run && snapshot.value.current_run.run_id === id) {
        snapshot.value.current_run = run
      }
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '取消运行失败')
      error.value = vpnErrorMessage(err.code, err.message)
      return false
    } finally {
      actionLoading.value = null
    }
  }

  async function saveSettings(vpnConfig: VpnConfig): Promise<boolean> {
    actionLoading.value = 'save_settings'
    error.value = null
    const rev = snapshot.value?.revision ?? 0
    try {
      const res = await unwrap(
        api().PATCH('/api/vpn/settings', {
          body: {
            revision: rev,
            vpn: vpnConfig,
          },
        }),
      )
      if (snapshot.value) {
        snapshot.value.revision = res.revision
        snapshot.value.settings = vpnConfig
      }
      notice.value = 'VPN 设置已保存'
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '保存设置失败')
      error.value = vpnErrorMessage(err.code, err.message)
      if (err.code === 'revision_conflict') {
        void fetchSnapshot()
      }
      return false
    } finally {
      actionLoading.value = null
    }
  }

  async function saveCredential(
    kind: 'vpn_password' | 'vpn_totp_secret',
    value: string,
  ): Promise<boolean> {
    if (!value.trim()) return false
    actionLoading.value = kind
    error.value = null
    try {
      await unwrap(
        api().PUT('/api/vpn/credentials/{kind}', {
          params: { path: { kind } },
          body: { value },
        }),
      )
      if (snapshot.value?.credentials) {
        const key = kind === 'vpn_password' ? 'password' : 'totp_secret'
        snapshot.value.credentials[key] = true
      }
      notice.value = kind === 'vpn_password' ? 'VPN 密码已保存' : 'TOTP 种子已保存'
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '保存凭据失败')
      error.value = vpnErrorMessage(err.code, err.message)
      return false
    } finally {
      actionLoading.value = null
    }
  }

  async function deleteCredential(kind: 'vpn_password' | 'vpn_totp_secret'): Promise<boolean> {
    actionLoading.value = `delete_${kind}`
    error.value = null
    try {
      await unwrap(
        api().DELETE('/api/vpn/credentials/{kind}', {
          params: { path: { kind } },
        }),
      )
      if (snapshot.value?.credentials) {
        const key = kind === 'vpn_password' ? 'password' : 'totp_secret'
        snapshot.value.credentials[key] = false
      }
      notice.value = kind === 'vpn_password' ? '已移除保存的密码' : '已移除保存的 TOTP 种子'
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '删除凭据失败')
      error.value = vpnErrorMessage(err.code, err.message)
      return false
    } finally {
      actionLoading.value = null
    }
  }

  async function importTotp(text: string, index?: number): Promise<TotpImportResult> {
    actionLoading.value = 'import_totp'
    error.value = null
    try {
      await unwrap(
        api().POST('/api/vpn/totp/import', {
          body: {
            text,
            index,
          },
        }),
      )
      if (snapshot.value?.credentials) {
        snapshot.value.credentials.totp_secret = true
      }
      notice.value = 'TOTP 种子导入成功，请自行删除导出文件'
      return { ambiguous: false }
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.code === 'totp_ambiguous') {
          const items = (e.detail?.items as TotpCandidate[]) || []
          return { ambiguous: true, items }
        }
        error.value = vpnErrorMessage(e.code, e.message)
      } else {
        error.value = '导入 TOTP 种子失败'
      }
      throw e
    } finally {
      actionLoading.value = null
    }
  }

  async function importLegacy(
    kinds: ('vpn_password' | 'vpn_totp_secret')[],
    fields = true,
  ): Promise<boolean> {
    if (kinds.length === 0) return false
    actionLoading.value = 'import_legacy'
    error.value = null
    try {
      await unwrap(
        api().POST('/api/vpn/credentials/import-legacy', {
          body: {
            kinds,
            fields,
          },
        }),
      )
      notice.value = '已从旧应用成功导入 VPN 配置与凭据'
      await fetchSnapshot()
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '从旧应用导入失败')
      error.value = vpnErrorMessage(err.code, err.message)
      return false
    } finally {
      actionLoading.value = null
    }
  }

  async function submitMfa(code: string): Promise<boolean> {
    const id = mfaRunId.value ?? snapshot.value?.current_run?.run_id
    if (!id) return false
    actionLoading.value = 'mfa'
    mfaError.value = null
    try {
      await unwrap(
        api().POST('/api/vpn/runs/{run_id}/mfa', {
          params: { path: { run_id: id } },
          body: { code },
        }),
      )
      closeMfa()
      notice.value = 'MFA 动态令牌已提交'
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '提交 MFA 失败')
      mfaError.value = vpnErrorMessage(err.code, err.message)
      return false
    } finally {
      actionLoading.value = null
    }
  }

  async function clearBrowserProfile(): Promise<boolean> {
    actionLoading.value = 'clear_browser'
    error.value = null
    try {
      await unwrap(api().DELETE('/api/vpn/browser-profile'))
      notice.value = '已清空浏览器登录凭据缓存（Chrome Profile）'
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '清空浏览器配置失败')
      error.value = vpnErrorMessage(err.code, err.message)
      return false
    } finally {
      actionLoading.value = null
    }
  }

  onMounted(() => {
    if (runtime) {
      removeEventListener = runtime.onEvent(handleEvent)
      subscribe()
    }
  })

  onUnmounted(() => {
    if (mfaTimer) {
      clearInterval(mfaTimer)
      mfaTimer = null
    }
    removeEventListener?.()
    unsubscribe()
  })

  return {
    snapshot,
    loading,
    error,
    notice,
    watermark,
    actionLoading,
    timelineEvents,
    mfaModalOpen,
    mfaRunId,
    mfaSecondsLeft,
    mfaError,
    online,
    clearNotice,
    clearError,
    openMfa,
    closeMfa,
    fetchSnapshot,
    connect,
    relogin,
    cancelRun,
    saveSettings,
    saveCredential,
    deleteCredential,
    importTotp,
    importLegacy,
    submitMfa,
    clearBrowserProfile,
  }
}

export type VpnContext = ReturnType<typeof useVpn>
export const vpnContextKey: InjectionKey<VpnContext> = Symbol('vpn-context')

export function useVpnContext(): VpnContext {
  const ctx = inject(vpnContextKey, null)
  if (!ctx) throw new Error('useVpnContext must be used within ServicesTab providing vpnContextKey')
  return ctx
}
