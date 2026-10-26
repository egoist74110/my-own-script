// MCP 状态与操作 composable：WS 订阅 + 水位管理 + 快照单飞刷新 + 各操作独立状态与幂等请求
import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import type { EventEnvelope } from '@/api/events'
import { useBackendStore } from '@/stores/backend'
import {
  ApiError,
  MCP_ERROR_MESSAGES,
  unwrap,
  type AdoMcp,
  type ClientConfig,
  type FigmaMcp,
  type LarkMcp,
  type MCPSnapshot,
  type McpJobView,
  type SelfTestResult,
} from './api'
import { settingsContextKey } from './useSettings'

export function useMcp() {
  const runtime = inject(backendRuntimeKey, null)
  const settingsCtx = inject(settingsContextKey, null)
  const store = useBackendStore()
  const online = computed(() => store.connection === 'online')

  function api(): ApiClient {
    const a = runtime?.api()
    if (!a) throw new ApiError(0, 'not_connected', '后端未连接')
    return a
  }

  // --- 快照与实时 WS 状态 ---
  const snapshot = ref<MCPSnapshot | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const watermark = ref(0)
  const activeJob = computed<McpJobView | null>(() => snapshot.value?.active_job ?? null)

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
      const res = await unwrap(api().GET('/api/mcp'))
      snapshot.value = res
      error.value = null
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', '读取 MCP 状态失败')
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
    if (envelope.topic !== 'mcp') return

    // 水位去重
    const seq = envelope.seq
    if (seq <= watermark.value && envelope.type !== 'mcp.subscribed') return

    if (envelope.type === 'mcp.subscribed') {
      const data = envelope.data as { last_seq?: number }
      if (typeof data.last_seq === 'number') {
        watermark.value = Math.max(watermark.value, data.last_seq)
      }
      return
    }

    watermark.value = seq

    if (envelope.type === 'mcp.status') {
      snapshot.value = envelope.data as unknown as MCPSnapshot
      error.value = null
    } else if (envelope.type === 'mcp.job') {
      const job = envelope.data as unknown as McpJobView
      if (snapshot.value) {
        snapshot.value = {
          ...snapshot.value,
          active_job: job,
        }
      }
    }
  }

  function subscribe() {
    if (!runtime) return
    // 先订阅 WS：确保新产生的实时增量进入队列，避免在 GET 快照与订阅之间漏事件
    runtime.subscribeMcp?.(watermark.value)
    void fetchSnapshot()
  }

  function unsubscribe() {
    runtime?.unsubscribeMcp?.()
  }

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
  })

  // --- 操作级局部 Loading 状态与结果 ---
  const adoTesting = ref(false)
  const adoTestResult = ref<SelfTestResult | null>(null)
  const adoError = ref<string | null>(null)

  const figmaTesting = ref(false)
  const figmaTestResult = ref<SelfTestResult | null>(null)
  const figmaError = ref<string | null>(null)

  const larkStarting = ref(false)
  const larkStopping = ref(false)
  const larkLoggingIn = ref(false)
  const larkCancellingLogin = ref(false)
  const larkLoggingOut = ref(false)
  const larkConfirmingOwner = ref(false)
  const larkRevokingOwner = ref(false)
  const larkError = ref<string | null>(null)

  const runtimeInstalling = ref(false)
  const runtimeCancelling = ref(false)
  const runtimeError = ref<string | null>(null)

  // 格式化错误文案
  function formatError(e: unknown): string {
    if (e instanceof ApiError) {
      return MCP_ERROR_MESSAGES[e.code] ?? e.message
    }
    if (e instanceof Error) return e.message
    return String(e)
  }

  // --- ADO 操作 ---
  async function runAdoSelfTest(timeoutS = 15): Promise<SelfTestResult | null> {
    adoTesting.value = true
    adoError.value = null
    adoTestResult.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/ado/self-test', {
          body: { timeout_s: timeoutS },
        }),
      )
      adoTestResult.value = res
      return res
    } catch (e) {
      adoError.value = formatError(e)
      return null
    } finally {
      adoTesting.value = false
    }
  }

  async function updateAdoSettings(adoConfig: AdoMcp): Promise<boolean> {
    adoError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().PATCH('/api/mcp/settings', {
          body: {
            ado: adoConfig,
            revision: rev,
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      adoError.value = formatError(e)
      if (e instanceof ApiError && e.code === 'revision_conflict') {
        await fetchSnapshot()
      }
      return false
    }
  }

  // --- Figma 操作 ---
  async function runFigmaSelfTest(timeoutS = 15): Promise<SelfTestResult | null> {
    figmaTesting.value = true
    figmaError.value = null
    figmaTestResult.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/figma/self-test', {
          body: { timeout_s: timeoutS },
        }),
      )
      figmaTestResult.value = res
      return res
    } catch (e) {
      figmaError.value = formatError(e)
      return null
    } finally {
      figmaTesting.value = false
    }
  }

  async function updateFigmaSettings(figmaConfig: FigmaMcp): Promise<boolean> {
    figmaError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().PATCH('/api/mcp/settings', {
          body: {
            figma: figmaConfig,
            revision: rev,
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      figmaError.value = formatError(e)
      if (e instanceof ApiError && e.code === 'revision_conflict') {
        await fetchSnapshot()
      }
      return false
    }
  }

  async function saveFigmaToken(value: string, expiryDays: 1 | 7 | 30 | 90): Promise<boolean> {
    figmaError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().PUT('/api/mcp/credentials/{kind}', {
          params: { path: { kind: 'figma_token' } },
          body: {
            value,
            expiry_days: expiryDays,
            revision: rev,
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      figmaError.value = formatError(e)
      return false
    }
  }

  async function deleteFigmaToken(): Promise<boolean> {
    figmaError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().DELETE('/api/mcp/credentials/{kind}', {
          params: {
            path: { kind: 'figma_token' },
            query: { revision: rev },
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      figmaError.value = formatError(e)
      return false
    }
  }

  async function importLegacyFigmaToken(): Promise<boolean> {
    figmaError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().POST('/api/mcp/credentials/import-legacy', {
          body: {
            kinds: ['figma_token'],
            revision: rev,
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      figmaError.value = formatError(e)
      return false
    }
  }

  // --- Lark 操作 ---
  async function updateLarkSettings(larkConfig: LarkMcp): Promise<boolean> {
    larkError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().PATCH('/api/mcp/settings', {
          body: {
            lark: larkConfig,
            revision: rev,
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      larkError.value = formatError(e)
      if (e instanceof ApiError && e.code === 'revision_conflict') {
        await fetchSnapshot()
      }
      return false
    }
  }

  async function saveLarkSecret(appId: string, value: string): Promise<boolean> {
    larkError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().PUT('/api/mcp/credentials/{kind}', {
          params: { path: { kind: 'lark_app_secret' } },
          body: {
            app_id: appId,
            value,
            expiry_days: 90,
            revision: rev,
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    }
  }

  async function deleteLarkSecret(appId: string): Promise<boolean> {
    larkError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().DELETE('/api/mcp/credentials/{kind}', {
          params: {
            path: { kind: 'lark_app_secret' },
            query: { revision: rev, app_id: appId },
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    }
  }

  async function importLegacyLarkSecret(appId: string): Promise<boolean> {
    larkError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      await unwrap(
        api().POST('/api/mcp/credentials/import-legacy', {
          body: {
            kinds: ['lark_app_secret'],
            app_id: appId,
            revision: rev,
          },
        }),
      )
      await fetchSnapshot()
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    }
  }

  async function confirmLarkOwnership(ackOldAppStopped: boolean): Promise<boolean> {
    larkConfirmingOwner.value = true
    larkError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      const res = await unwrap(
        api().POST('/api/mcp/lark/ownership', {
          body: {
            ack_old_app_stopped: ackOldAppStopped,
            request_id: crypto.randomUUID(),
            revision: rev,
          },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    } finally {
      larkConfirmingOwner.value = false
    }
  }

  async function revokeLarkOwnership(): Promise<boolean> {
    larkRevokingOwner.value = true
    larkError.value = null
    try {
      const rev = snapshot.value?.revision ?? 0
      const res = await unwrap(
        api().DELETE('/api/mcp/lark/ownership', {
          params: { query: { revision: rev } },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    } finally {
      larkRevokingOwner.value = false
    }
  }

  async function startLark(): Promise<boolean> {
    larkStarting.value = true
    larkError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/lark/start', {
          body: { request_id: crypto.randomUUID() },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    } finally {
      larkStarting.value = false
    }
  }

  async function stopLark(): Promise<boolean> {
    larkStopping.value = true
    larkError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/lark/stop', {
          body: { request_id: crypto.randomUUID() },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    } finally {
      larkStopping.value = false
    }
  }

  async function loginLark(): Promise<boolean> {
    larkLoggingIn.value = true
    larkError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/lark/login', {
          body: { request_id: crypto.randomUUID() },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    } finally {
      larkLoggingIn.value = false
    }
  }

  async function cancelLarkLogin(): Promise<boolean> {
    larkCancellingLogin.value = true
    larkError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/lark/login/cancel', {
          body: { request_id: crypto.randomUUID() },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    } finally {
      larkCancellingLogin.value = false
    }
  }

  async function logoutLark(): Promise<boolean> {
    larkLoggingOut.value = true
    larkError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/lark/logout', {
          body: { request_id: crypto.randomUUID() },
        }),
      )
      snapshot.value = res
      return true
    } catch (e) {
      larkError.value = formatError(e)
      return false
    } finally {
      larkLoggingOut.value = false
    }
  }

  // --- Runtime 安装与取消 ---
  async function installRuntime(forceNode = false): Promise<boolean> {
    runtimeInstalling.value = true
    runtimeError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/runtime/install', {
          body: {
            force_node: forceNode,
            request_id: crypto.randomUUID(),
          },
        }),
      )
      if (snapshot.value) {
        snapshot.value = {
          ...snapshot.value,
          active_job: res,
        }
      }
      return true
    } catch (e) {
      runtimeError.value = formatError(e)
      return false
    } finally {
      runtimeInstalling.value = false
    }
  }

  async function cancelRuntimeJob(jobId: string): Promise<boolean> {
    runtimeCancelling.value = true
    runtimeError.value = null
    try {
      const res = await unwrap(
        api().POST('/api/mcp/jobs/{job_id}/cancel', {
          params: { path: { job_id: jobId } },
          body: { request_id: crypto.randomUUID() },
        }),
      )
      if (snapshot.value) {
        snapshot.value = {
          ...snapshot.value,
          active_job: res,
        }
      }
      return true
    } catch (e) {
      runtimeError.value = formatError(e)
      return false
    } finally {
      runtimeCancelling.value = false
    }
  }

  // --- 接入片段获取 ---
  async function fetchClientConfig(
    server: 'ado' | 'lark' | 'figma',
    cli: 'claude' | 'codex' | 'agy',
  ): Promise<ClientConfig | null> {
    try {
      return await unwrap(
        api().GET('/api/mcp/client-config', {
          params: { query: { server, cli } },
        }),
      )
    } catch {
      return null
    }
  }

  // --- 分析来源切换 ---
  async function switchAnalysisSource(
    targetSource: 'legacy' | 'toolbox',
    ackCliRegistered: boolean,
  ): Promise<boolean> {
    if (!settingsCtx) return false
    try {
      const aiView = settingsCtx.ai.data.value
      const currentAnalysis = aiView?.analysis ?? { mcp_source: 'legacy' }
      const rev = aiView?.revision ?? 0
      const res = await settingsCtx.patchAiSettings(
        {
          selected_profile_id: aiView?.selected_profile_id || null,
          ack_cli_registered: ackCliRegistered,
          analysis: {
            ...currentAnalysis,
            mcp_source: targetSource,
          },
          defaults: aiView?.defaults ?? null,
          model_presets: aiView?.model_presets ?? null,
          mcp_tool_prefix: aiView?.mcp_tool_prefix ?? null,
        },
        undefined,
        { revision: rev },
      )
      return res.ok
    } catch {
      return false
    }
  }

  return {
    snapshot,
    activeJob,
    loading,
    error,
    watermark,
    fetchSnapshot,
    // ADO
    adoTesting,
    adoTestResult,
    adoError,
    runAdoSelfTest,
    updateAdoSettings,
    switchAnalysisSource,
    // Figma
    figmaTesting,
    figmaTestResult,
    figmaError,
    runFigmaSelfTest,
    updateFigmaSettings,
    saveFigmaToken,
    deleteFigmaToken,
    importLegacyFigmaToken,
    // Lark
    larkStarting,
    larkStopping,
    larkLoggingIn,
    larkCancellingLogin,
    larkLoggingOut,
    larkConfirmingOwner,
    larkRevokingOwner,
    larkError,
    updateLarkSettings,
    saveLarkSecret,
    deleteLarkSecret,
    importLegacyLarkSecret,
    confirmLarkOwnership,
    revokeLarkOwnership,
    startLark,
    stopLark,
    loginLark,
    cancelLarkLogin,
    logoutLark,
    // Runtime
    runtimeInstalling,
    runtimeCancelling,
    runtimeError,
    installRuntime,
    cancelRuntimeJob,
    // Snippets
    fetchClientConfig,
  }
}
