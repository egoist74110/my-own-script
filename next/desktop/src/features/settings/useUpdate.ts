// S9-C：设置页“关于与更新”状态与操作 composable
// 经 Tauri invoke 调用 update_status/update_check/update_install/update_cancel/update_restart，
// 订阅 update://status 事件推送更新。非 Tauri 环境降级为只读 disabled。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { defaultTauriInvoke, type TauriInvoke } from '@/api/connection'

export type UpdateState =
  'disabled' | 'idle' | 'checking' | 'up_to_date' | 'available' | 'downloading' | 'ready' | 'error'

export type UpdateErrorCode =
  | 'update_not_configured'
  | 'update_unsupported_dev'
  | 'update_busy'
  | 'update_check_failed'
  | 'update_download_failed'
  | 'update_signature_invalid'
  | 'update_install_failed'
  | 'update_cancelled'

export interface UpdateProgress {
  downloaded: number
  total: number | null
}

export interface UpdateStatus {
  state: UpdateState
  current_version: string
  available_version: string | null
  notes: string | null
  progress: UpdateProgress | null
  error_code: UpdateErrorCode | null
  checked_at: number | null
}

export type TauriUnlisten = () => void
export type TauriListen = <T = unknown>(
  event: string,
  handler: (event: { payload: T }) => void,
) => Promise<TauriUnlisten>

export interface UpdateSources {
  getTauriInvoke?: () => TauriInvoke | null
  getTauriListen?: () => TauriListen | null
}

export const UPDATE_ERROR_MESSAGES: Record<UpdateErrorCode, string> = {
  update_not_configured: '未配置更新源',
  update_unsupported_dev: '开发态不支持更新',
  update_busy: '正在进行',
  update_check_failed: '检查更新失败',
  update_download_failed: '下载失败',
  update_signature_invalid: '更新包签名校验未通过（已保留当前版本）',
  update_install_failed: '安装失败（已保留当前版本）',
  update_cancelled: '已取消',
}

export function updateErrorMessage(code: string | null | undefined): string {
  if (!code) return ''
  return (UPDATE_ERROR_MESSAGES as Record<string, string>)[code] ?? code
}

function resolveTauriListen(): TauriListen | null {
  const g = globalThis as unknown as {
    __TAURI_LISTEN__?: TauriListen
    __TAURI_INTERNALS__?: { listen?: TauriListen }
  }
  if (typeof g.__TAURI_LISTEN__ === 'function') {
    return g.__TAURI_LISTEN__
  }
  if (typeof g.__TAURI_INTERNALS__?.listen === 'function') {
    return g.__TAURI_INTERNALS__.listen
  }
  return null
}

async function getDefaultListen(): Promise<TauriListen | null> {
  const resolved = resolveTauriListen()
  if (resolved) return resolved
  try {
    const { listen } = await import('@tauri-apps/api/event')
    return listen as TauriListen
  } catch {
    return null
  }
}

export function useUpdate(sources?: UpdateSources) {
  function getInvoke(): TauriInvoke | null {
    if (sources?.getTauriInvoke) {
      return sources.getTauriInvoke()
    }
    return defaultTauriInvoke()
  }

  async function getListen(): Promise<TauriListen | null> {
    if (sources?.getTauriListen) {
      return sources.getTauriListen()
    }
    return await getDefaultListen()
  }

  const status = ref<UpdateStatus>({
    state: 'disabled',
    current_version: '1.0.0',
    available_version: null,
    notes: null,
    progress: null,
    error_code: null,
    checked_at: null,
  })

  const loading = ref(false)
  const error = ref<string | null>(null)
  let unlistenFn: TauriUnlisten | null = null
  let disposed = false

  const isTauriReady = computed(() => {
    return getInvoke() !== null
  })

  const disabledReason = computed(() => {
    if (status.value.state !== 'disabled') return ''
    if (status.value.error_code === 'update_not_configured') {
      return UPDATE_ERROR_MESSAGES.update_not_configured
    }
    if (status.value.error_code === 'update_unsupported_dev') {
      return UPDATE_ERROR_MESSAGES.update_unsupported_dev
    }
    return '仅桌面应用内可用'
  })

  async function checkUpdate() {
    const invoke = getInvoke()
    if (!invoke || status.value.state === 'disabled') return
    if (status.value.state === 'checking' || status.value.state === 'downloading') return
    status.value.state = 'checking'
    status.value.error_code = null
    error.value = null
    loading.value = true
    try {
      const res = (await invoke('update_check')) as UpdateStatus
      if (res) {
        status.value = res
      }
    } catch (err) {
      const code = (
        typeof err === 'string' ? err : (err as Error)?.message || 'update_check_failed'
      ) as UpdateErrorCode
      status.value.state = 'error'
      status.value.error_code = code
      error.value = updateErrorMessage(code)
    } finally {
      loading.value = false
    }
  }

  async function installUpdate() {
    const invoke = getInvoke()
    if (!invoke || status.value.state !== 'available') return
    error.value = null
    loading.value = true
    try {
      const res = (await invoke('update_install')) as UpdateStatus
      if (res) {
        status.value = res
      }
    } catch (err) {
      const code = (
        typeof err === 'string' ? err : (err as Error)?.message || 'update_install_failed'
      ) as UpdateErrorCode
      status.value.state = 'error'
      status.value.error_code = code
      error.value = updateErrorMessage(code)
    } finally {
      loading.value = false
    }
  }

  async function cancelUpdate() {
    const invoke = getInvoke()
    if (!invoke) return
    if (status.value.state !== 'checking' && status.value.state !== 'downloading') return
    error.value = null
    try {
      const res = (await invoke('update_cancel')) as UpdateStatus
      if (res) {
        status.value = res
      }
    } catch (err) {
      const code = (
        typeof err === 'string' ? err : (err as Error)?.message || 'update_cancelled'
      ) as UpdateErrorCode
      error.value = updateErrorMessage(code)
    }
  }

  async function restartUpdate() {
    const invoke = getInvoke()
    if (!invoke || status.value.state !== 'ready') return
    error.value = null
    try {
      await invoke('update_restart')
    } catch (err) {
      const code = (
        typeof err === 'string' ? err : (err as Error)?.message || 'update_install_failed'
      ) as UpdateErrorCode
      error.value = updateErrorMessage(code)
    }
  }

  onMounted(async () => {
    const invoke = getInvoke()
    if (!invoke) {
      // 非 Tauri 环境：降级为 disabled，文案“仅桌面应用内可用”
      status.value = {
        state: 'disabled',
        current_version: '1.0.0',
        available_version: null,
        notes: null,
        progress: null,
        error_code: null,
        checked_at: null,
      }
      return
    }

    try {
      const listen = await getListen()
      if (disposed) return
      if (listen) {
        const unlisten = await listen<UpdateStatus>('update://status', (event) => {
          if (disposed) return
          if (event && event.payload) {
            status.value = event.payload
          }
        })
        if (disposed) {
          unlisten()
        } else {
          unlistenFn = unlisten
        }
      }
    } catch {
      // 忽略 listen 异常
    }

    try {
      const res = (await invoke('update_status')) as UpdateStatus
      if (!disposed && res) {
        status.value = res
      }
    } catch (err) {
      if (!disposed) {
        const code = (typeof err === 'string' ? err : (err as Error)?.message) as UpdateErrorCode
        if (code === 'update_not_configured' || code === 'update_unsupported_dev') {
          status.value.state = 'disabled'
          status.value.error_code = code
        } else if (code) {
          status.value.state = 'error'
          status.value.error_code = code
          error.value = updateErrorMessage(code)
        }
      }
    }
  })

  onUnmounted(() => {
    disposed = true
    if (unlistenFn) {
      unlistenFn()
      unlistenFn = null
    }
  })

  return {
    status,
    loading,
    error,
    isTauriReady,
    disabledReason,
    checkUpdate,
    installUpdate,
    cancelUpdate,
    restartUpdate,
  }
}
