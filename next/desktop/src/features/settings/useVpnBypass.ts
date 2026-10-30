// VPN 分流（bypass）草稿与操作：加载/保存/安装应用/停用撤销/预览/状态轮询。草稿与服务端快照分离：
// 刷新（轮询）只在草稿未改动时覆盖；有未保存编辑时只记录“远端更新”，由用户显式点刷新才丢弃草稿。
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import { useBackendStore } from '@/stores/backend'
import {
  ApiError,
  unwrap,
  vpnErrorMessage,
  type VpnBypassApp,
  type VpnBypassConfig,
  type VpnBypassStatus,
  type VpnBypassTarget,
  type VpnBypassSweepResult,
  type VpnBypassView,
} from './api'

export const POLL_INTERVAL_MS = 5000

const IPV4 = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/

export function isIpv4(v: string): boolean {
  return IPV4.test(v)
}

export function isIpv4OrCidr(v: string): boolean {
  const [ip, len, ...rest] = v.split('/')
  if (rest.length || !isIpv4(ip ?? '')) return false
  if (len === undefined) return true
  return /^\d{1,2}$/.test(len) && Number(len) >= 1 && Number(len) <= 32
}

export function parseTargets(text: string): string[] {
  const seen = new Set<string>()
  for (const raw of text.split(/[\s,;]+/)) {
    const t = raw.trim()
    if (t) seen.add(t)
  }
  return [...seen]
}

export function emptyConfig(): VpnBypassConfig {
  return {
    enabled: false,
    gateway: null,
    interface: null,
    interval_s: 20,
    retention_s: 300,
    apps: [],
    targets: [],
  } as VpnBypassConfig
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T

export function newAppId(existing: string[]): string {
  const used = new Set(existing)
  for (;;) {
    const id = `app-${Math.random().toString(36).slice(2, 10)}`
    if (!used.has(id)) return id
  }
}

export type AppKind = 'executable' | 'application'
export const appKind = (a: VpnBypassApp): AppKind =>
  a.application_path != null && a.executable_path == null ? 'application' : 'executable'
export const appPath = (a: VpnBypassApp): string =>
  (appKind(a) === 'application' ? a.application_path : a.executable_path) ?? ''

export type BypassOp = 'saving' | 'activating' | 'deactivating'

const CANCEL_CODES = new Set([
  'bypass_authorization_cancelled',
  'bypass_auth_cancelled',
  'auth_cancelled',
  'authorization_cancelled',
])
function isAuthCancel(err: ApiError): boolean {
  return (
    CANCEL_CODES.has(err.code) ||
    (typeof err.detail.cause === 'string' && CANCEL_CODES.has(err.detail.cause)) ||
    (err.code.startsWith('bypass_') && /取消|cancel/i.test(err.message))
  )
}

export function useVpnBypass() {
  const runtime = inject(backendRuntimeKey, null)
  const store = useBackendStore()
  const online = computed(() => store.connection === 'online')

  function api(): ApiClient {
    const a = runtime?.api()
    if (!a) throw new ApiError(0, 'not_connected', '后端未连接')
    return a
  }

  // 服务端已知状态
  const server = ref<VpnBypassView | null>(null)
  // 草稿：目标列表单独用文本编辑
  const draft = ref<VpnBypassConfig>(emptyConfig())
  const targetsText = ref('')
  const baseRevision = ref(0)
  // 草稿有未保存修改时，后端出现了更新的版本（不覆盖，等用户显式刷新）
  const remote = ref<VpnBypassView | null>(null)

  const loading = ref(false)
  const op = ref<BypassOp | null>(null)
  const previewing = ref(false)
  const loadError = ref<string | null>(null)
  const saveError = ref<string | null>(null)
  // 保存已落库但同步到系统失败（不是版本冲突）
  const syncError = ref<string | null>(null)
  const actionError = ref<string | null>(null)
  // 系统授权被用户取消（不是失败）
  const cancelled = ref(false)
  const notice = ref<string | null>(null)
  const preview = ref<VpnBypassSweepResult | null>(null)
  // 每次变更操作开始/结束都会递增；更早发起的读取结果作废，避免旧快照覆盖
  let generation = 0

  const saving = computed(() => op.value === 'saving')
  const operating = computed(() => op.value !== null)
  const status = computed<VpnBypassStatus | null>(() => server.value?.status ?? null)
  const installed = computed(() => status.value?.installed === true)
  const targets = computed<VpnBypassTarget[]>(() => status.value?.targets ?? [])

  /** 把草稿规整成请求体（目标文本 → 去重列表；数值字段规整为数字）。 */
  function toConfig(): VpnBypassConfig {
    const c = clone(draft.value)
    c.targets = parseTargets(targetsText.value)
    c.gateway = c.gateway?.toString().trim() ? c.gateway.toString().trim() : null
    c.interface = c.interface?.toString().trim() ? c.interface.toString().trim() : null
    c.interval_s = Number(c.interval_s)
    c.retention_s = Number(c.retention_s)
    c.apps = c.apps.map((a) => ({
      ...a,
      name: a.name.trim(),
      executable_path: a.executable_path?.trim() ? a.executable_path.trim() : null,
      application_path: a.application_path?.trim() ? a.application_path.trim() : null,
    }))
    return c
  }

  const dirty = computed(
    () =>
      server.value !== null &&
      JSON.stringify(toConfig()) !== JSON.stringify(clone(server.value.settings)),
  )

  /** 前端预检（后端仍是最终校验）。返回问题列表。 */
  const problems = computed<string[]>(() => {
    const c = toConfig()
    const out: string[] = []
    if (c.gateway && !isIpv4(c.gateway)) out.push('网关必须是 IPv4 地址')
    if (c.interface && !/^en[0-9]+$/.test(c.interface)) out.push('网卡名格式应为 en0、en1…')
    if (c.enabled && (!c.gateway || !c.interface)) out.push('启用分流需同时填写网关与网卡')
    if (!(c.interval_s >= 5 && c.interval_s <= 300)) out.push('扫描间隔需在 5–300 秒')
    if (!(c.retention_s >= 0 && c.retention_s <= 3600)) out.push('路由保留时间需在 0–3600 秒')
    if (c.apps.length > 32) out.push('应用规则最多 32 条')
    if (c.targets.length > 256) out.push('手动目标最多 256 条')
    const bad = c.targets.filter((t) => !isIpv4OrCidr(t))
    if (bad.length) out.push(`目标不是合法 IPv4/CIDR：${bad.slice(0, 3).join('、')}`)
    c.apps.forEach((a, i) => {
      const label = a.name || `第 ${i + 1} 条规则`
      if (!a.name) out.push(`第 ${i + 1} 条规则缺少名称`)
      const set = [a.executable_path, a.application_path].filter(Boolean)
      if (set.length !== 1) out.push(`${label}：需填写且仅填写一个路径`)
      else if (!String(set[0]).startsWith('/')) out.push(`${label}：路径必须是绝对路径`)
      else if (a.application_path && !a.application_path.endsWith('.app'))
        out.push(`${label}：应用路径需以 .app 结尾`)
    })
    return out
  })

  /** 已保存配置是否允许应用（草稿必须与已保存一致）。 */
  const savedEnabled = computed(() => server.value?.settings.enabled === true)
  const canActivate = computed(
    () =>
      server.value !== null && !dirty.value && savedEnabled.value && problems.value.length === 0,
  )

  function applyView(view: VpnBypassView) {
    server.value = view
    baseRevision.value = view.revision
    draft.value = { ...emptyConfig(), ...clone(view.settings) }
    targetsText.value = (view.settings.targets ?? []).join('\n')
    remote.value = null
  }

  /** 采用服务端快照但保留用户草稿（草稿与新快照一致时等价于 applyView）。 */
  function adoptKeepDraft(view: VpnBypassView) {
    if (!dirty.value) {
      applyView(view)
      return
    }
    server.value = view
    baseRevision.value = view.revision
    remote.value = null
  }

  function errMsg(e: unknown, fallback: string): { err: ApiError; msg: string } {
    const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', fallback)
    // 校验类/同步失败类错误后端给出具体原因，优先展示
    const specific =
      (err.code === 'validation_error' && !err.message.startsWith('请求失败')) ||
      err.code === 'bypass_sync_failed'
    return { err, msg: specific ? err.message : vpnErrorMessage(err.code, err.message || fallback) }
  }

  async function fetchView(): Promise<VpnBypassView> {
    const view = await unwrap(api().GET('/api/vpn/bypass'))
    if (!view || !view.settings) throw new ApiError(0, 'unknown', '分流配置响应格式不正确')
    return view
  }

  /**
   * 读取后端。草稿未改动才覆盖；有脏草稿只记录更新版本，并刷新状态。
   * silent（轮询）不占用 loading、不报错覆盖；变更操作进行中不读取。
   */
  async function refresh(silent = false): Promise<boolean> {
    if (!online.value || operating.value) return false
    if (!silent && loading.value) return false
    const gen = generation
    if (!silent) loading.value = true
    try {
      const view = await fetchView()
      if (gen !== generation || operating.value) return false
      loadError.value = null
      if (!server.value || !dirty.value) {
        applyView(view)
      } else if (view.revision !== baseRevision.value) {
        remote.value = view
        server.value = { ...server.value, status: view.status }
      } else {
        // 同版本：仅同步状态，不动草稿
        server.value = { ...server.value, status: view.status }
      }
      return true
    } catch (e) {
      if (!silent) loadError.value = errMsg(e, '读取分流配置失败').msg
      return false
    } finally {
      if (!silent) loading.value = false
    }
  }

  /** 显式采用后端最新版本（丢弃本地草稿）。 */
  async function discardAndReload(): Promise<boolean> {
    if (operating.value) return false
    if (remote.value) {
      applyView(remote.value)
      saveError.value = null
      syncError.value = null
      return true
    }
    server.value = null // 强制覆盖
    const ok = await refresh()
    if (ok) {
      saveError.value = null
      syncError.value = null
    }
    return ok
  }

  /** 操作后取回最新快照，以服务端真实状态为准；取不到则退回 fallback。 */
  async function settle(fallback?: VpnBypassView | null): Promise<void> {
    try {
      adoptKeepDraft(await fetchView())
      loadError.value = null
    } catch {
      if (fallback?.settings) adoptKeepDraft(fallback)
    }
  }

  async function runOp<T>(kind: BypassOp, fn: () => Promise<T>): Promise<T> {
    op.value = kind
    generation++
    try {
      return await fn()
    } finally {
      generation++
      op.value = null
    }
  }

  async function save(): Promise<boolean> {
    if (operating.value || problems.value.length || !server.value) return false
    saveError.value = null
    syncError.value = null
    cancelled.value = false
    notice.value = null
    const sent = toConfig()
    const wasInstalled = installed.value
    return runOp('saving', async () => {
      try {
        const res = await unwrap(
          api().PATCH('/api/vpn/bypass/settings', {
            body: { revision: baseRevision.value, settings: sent },
          }),
        )
        // 先记录已保存的配置，再取回真实状态（已安装时后端已自动同步）
        server.value = server.value
          ? { ...server.value, revision: res.revision, settings: sent }
          : server.value
        baseRevision.value = res.revision
        remote.value = null
        preview.value = null
        await settle(null)
        notice.value = wasInstalled
          ? '分流配置已保存并提交同步，请以下方状态为准。'
          : '分流配置已保存（尚未安装，需授权安装后才会生效）。'
        return true
      } catch (e) {
        const { err, msg } = errMsg(e, '保存分流配置失败')
        if (err.code === 'bypass_sync_failed') {
          // 配置已落库、同步失败：刷新服务端版本，草稿保留，便于重试
          syncError.value = msg.includes('已保存') ? msg : `配置已保存，但同步到系统失败：${msg}`
          cancelled.value = isAuthCancel(err)
          try {
            const view = await fetchView()
            if (JSON.stringify(toConfig()) === JSON.stringify(clone(view.settings))) applyView(view)
            else adoptKeepDraft(view)
          } catch {
            // 无法确认服务端版本，保留现状
          }
          return false
        }
        saveError.value = msg
        if (err.code === 'revision_conflict') {
          try {
            const view = await fetchView()
            remote.value = view
          } catch {
            // 取回失败时保留冲突提示即可
          }
        }
        return false
      }
    })
  }

  async function operate(kind: 'activating' | 'deactivating'): Promise<boolean> {
    if (operating.value || !server.value) return false
    if (kind === 'activating' && !canActivate.value) return false
    if (kind === 'deactivating' && !installed.value) return false
    actionError.value = null
    cancelled.value = false
    notice.value = null
    const revision = server.value.revision
    const path = kind === 'activating' ? '/api/vpn/bypass/activate' : '/api/vpn/bypass/deactivate'
    return runOp(kind, async () => {
      try {
        const view = await unwrap(api().POST(path, { body: { revision } }))
        await settle(view)
        notice.value =
          kind === 'activating'
            ? '已提交应用，结果见下方状态。'
            : '已提交停用并撤销，结果见下方状态。'
        return true
      } catch (e) {
        const { err, msg } = errMsg(e, kind === 'activating' ? '应用失败' : '停用失败')
        if (isAuthCancel(err)) {
          cancelled.value = true
          actionError.value = null
        } else {
          actionError.value = msg
        }
        if (err.code === 'revision_conflict') {
          try {
            remote.value = await fetchView()
          } catch {
            // 保留冲突提示
          }
        } else {
          await settle(null)
        }
        return false
      }
    })
  }

  const activate = () => operate('activating')
  const deactivate = () => operate('deactivating')

  async function runPreview(): Promise<boolean> {
    if (dirty.value || operating.value || loading.value || previewing.value) {
      actionError.value = '请先保存当前修改，再预览已保存的配置。'
      return false
    }
    previewing.value = true
    actionError.value = null
    try {
      preview.value = await unwrap(api().POST('/api/vpn/bypass/sweep', { body: { apply: false } }))
      return true
    } catch (e) {
      preview.value = null
      actionError.value = errMsg(e, '预览失败').msg
      return false
    } finally {
      previewing.value = false
    }
  }

  // 草稿编辑
  function addApp() {
    const id = newAppId(draft.value.apps.map((a) => a.id))
    draft.value.apps.push({
      id,
      name: '',
      enabled: true,
      executable_path: null,
      application_path: null,
    } as VpnBypassApp)
  }
  function removeApp(id: string) {
    draft.value.apps = draft.value.apps.filter((a) => a.id !== id)
  }
  function setAppKind(a: VpnBypassApp, kind: AppKind) {
    const path = appPath(a)
    // 空串（非 null）用来记住所选类型；序列化时 toConfig 会规整为 null
    a.executable_path = kind === 'executable' ? path : null
    a.application_path = kind === 'application' ? path : null
  }
  function setAppPath(a: VpnBypassApp, path: string) {
    if (appKind(a) === 'application') a.application_path = path
    else a.executable_path = path
  }

  let timer: ReturnType<typeof setInterval> | null = null
  watch(online, (connected) => {
    if (connected) void refresh()
  })
  onMounted(() => {
    void refresh()
    timer = setInterval(() => void refresh(true), POLL_INTERVAL_MS)
  })
  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
    timer = null
  })

  return {
    server,
    draft,
    targetsText,
    baseRevision,
    remote,
    loading,
    op,
    saving,
    operating,
    previewing,
    loadError,
    saveError,
    syncError,
    actionError,
    cancelled,
    notice,
    preview,
    status,
    installed,
    targets,
    savedEnabled,
    canActivate,
    dirty,
    problems,
    online,
    refresh,
    discardAndReload,
    save,
    activate,
    deactivate,
    runPreview,
    addApp,
    removeApp,
    setAppKind,
    setAppPath,
  }
}
