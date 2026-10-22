// 设置页数据与动作（第一个接真实后端的页面）。
// 读：vue-query（键以 ['settings'] 开头，收到 settings.changed 或重连后整体失效）。
// 写：普通 async 函数而非 useMutation —— mutation 缓存会保留 variables，而 PAT 不得进入任何缓存。
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, inject, ref, watch, type InjectionKey } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import { useBackendStore } from '@/stores/backend'
import {
  ApiError,
  unwrap,
  type AdoResponse,
  type CredentialStatus,
  type ImportPreview,
  type SettingsResponse,
} from './api'

export interface Notice {
  kind: 'ok' | 'warn' | 'error'
  text: string
  tasks?: string[]
  warnings?: string[]
}

/**
 * `sent`：请求是否真正发出（被 busy/不可写/未加载拒绝的为 false，调用方据此决定是否清空 PAT）。
 * `rev`：本次写请求所用的 revision（未发出为 null）。
 */
export type ActResult<T> =
  | { ok: true; data: T; sent: boolean; rev: number | null }
  | { ok: false; error: ApiError; sent: boolean; rev: number | null }

export interface ActOptions {
  /** 默认 true：写操作（受 writable 约束、可能带 warnings）；只读类 POST/GET 传 false。 */
  write?: boolean
  /** revision_conflict 刷新后调用；返回 true 表示调用方已按基线合并，提示改用合并文案。 */
  onConflict?: () => boolean
  /** 显式 revision（编辑基线）；缺省用缓存中的最新值。 */
  revision?: number
}

const PREFLIGHT = new Set(['busy', 'not_writable', 'not_loaded', 'not_connected'])

const QK = ['settings'] as const

export function useSettingsContext() {
  const runtime = inject(backendRuntimeKey, null)
  const store = useBackendStore()
  const qc = useQueryClient()
  const online = computed(() => store.connection === 'online')

  function api(): ApiClient {
    const a = runtime?.api()
    if (!a) throw new ApiError(0, 'not_connected', '后端未连接')
    return a
  }

  // overview 请求的发起/完成序号：故障后只认「故障之后发起、且未被取消并真正完成」的请求。
  let overviewStarted = 0
  let overviewDoneMax = 0
  const overview = useQuery({
    queryKey: [...QK, 'overview'],
    enabled: online,
    retry: false,
    // 读取 signal 使 vue-query 在取消（被新的刷新取代）时置 aborted
    queryFn: async ({ signal }): Promise<SettingsResponse> => {
      const idx = ++overviewStarted
      const data = await unwrap(api().GET('/api/settings'))
      if (!signal.aborted) overviewDoneMax = Math.max(overviewDoneMax, idx)
      return data
    },
  })
  const ado = useQuery({
    queryKey: [...QK, 'ado'],
    enabled: online,
    retry: false,
    queryFn: (): Promise<AdoResponse> => unwrap(api().GET('/api/ado')),
  })
  const credentials = useQuery({
    queryKey: [...QK, 'credentials'],
    enabled: online,
    retry: false,
    queryFn: (): Promise<CredentialStatus[]> => unwrap(api().GET('/api/credentials')),
  })

  // settings.changed（任意窗口/进程的写入）让全部设置查询失效
  watch(
    () => store.settingsRevision,
    () => void qc.invalidateQueries({ queryKey: QK }),
  )

  // 写请求收到 503 store_unavailable 后记下当时已发起的 overview 请求数（故障标记）；
  // 只有标记之后发起并实际完成、且返回 store_state=ok 的 overview 请求才解除禁写。
  // 离线（查询未启用）、刷新未执行/失败/被取消都保持禁写。
  const faultMark = ref<number | null>(null)
  const storeFault = computed(() => faultMark.value !== null)
  function maybeReleaseFault() {
    if (
      faultMark.value !== null &&
      overviewDoneMax > faultMark.value &&
      overview.isSuccess.value &&
      overview.data.value?.store_state === 'ok'
    )
      faultMark.value = null
  }
  watch(() => overview.dataUpdatedAt.value, maybeReleaseFault)
  const writable = computed(() => overview.data.value?.store_state === 'ok' && !storeFault.value)
  const revision = computed(() => ado.data.value?.revision ?? overview.data.value?.revision ?? null)
  const loadError = computed(() =>
    overview.error.value || ado.error.value || credentials.error.value ? '读取设置失败' : null,
  )

  const busy = ref(false)
  const notice = ref<Notice | null>(null)
  const clearNotice = () => (notice.value = null)

  const refresh = () => qc.invalidateQueries({ queryKey: QK })

  /**
   * 执行一次写操作。`handle` 返回 true 表示调用方已自行展示该错误（如 pat_origin_change），
   * 其余错误统一进 notice。revision_conflict 会刷新数据并提示。
   */
  async function act<T>(
    fn: (revision: number) => Promise<T>,
    okText?: string,
    handle?: (e: ApiError) => boolean,
    opts: ActOptions = {},
  ): Promise<ActResult<T>> {
    const write = opts.write ?? true
    if (busy.value) {
      notice.value = { kind: 'warn', text: '操作进行中，请稍候' }
      return { ok: false, error: new ApiError(0, 'busy', '操作进行中'), sent: false, rev: null }
    }
    if (write && !writable.value) {
      notice.value = { kind: 'error', text: '存储当前不可写，写操作已停用' }
      return {
        ok: false,
        error: new ApiError(0, 'not_writable', '存储当前不可写'),
        sent: false,
        rev: null,
      }
    }
    busy.value = true
    notice.value = null
    let sent = false
    let used: number | null = null
    try {
      const rev = opts.revision ?? revision.value
      if (rev === null) throw new ApiError(0, 'not_loaded', '设置尚未加载')
      used = rev
      sent = true
      const data = await fn(rev)
      await refresh()
      const w = write ? (data as { warnings?: unknown } | null)?.warnings : undefined
      const warnings = Array.isArray(w)
        ? w.filter((x): x is string => typeof x === 'string' && x !== '')
        : []
      if (warnings.length) {
        notice.value = { kind: 'warn', text: '操作已完成，但有需要留意的警告', warnings }
      } else if (okText) {
        notice.value = { kind: 'ok', text: okText }
      }
      return { ok: true, data, sent, rev: used }
    } catch (e) {
      const error = e instanceof ApiError ? e : new ApiError(0, 'unknown', '操作失败')
      if (PREFLIGHT.has(error.code) && error.status === 0) sent = false
      if (error.code === 'revision_conflict') {
        await refresh()
        const merged = opts.onConflict?.() ?? false
        notice.value = {
          kind: 'warn',
          text: merged
            ? '设置已被其他窗口修改，已合并最新内容，请核对后再保存'
            : '配置已被其他窗口或进程更新，已刷新为最新内容，请确认后重试。',
        }
      } else if (!handle?.(error)) {
        notice.value = {
          kind: 'error',
          text: error.message,
          ...(error.code === 'in_use' ? { tasks: error.tasks } : {}),
        }
      }
      if (error.code === 'store_unavailable') {
        faultMark.value = overviewStarted
        await refresh()
        maybeReleaseFault()
      }
      return { ok: false, error, sent, rev: used }
    } finally {
      busy.value = false
    }
  }

  const actions = {
    previewImport: () =>
      act(() => unwrap(api().POST('/api/settings/import/preview')), undefined, undefined, {
        write: false,
      }),
    executeImport: (fingerprint: string, handle?: (e: ApiError) => boolean) =>
      act(
        () => unwrap(api().POST('/api/settings/import/execute', { body: { fingerprint } })),
        '导入完成',
        handle,
      ),
    declineImport: () =>
      act(() => unwrap(api().POST('/api/settings/import/decline')), '已跳过导入'),
    createLibrary: (name: string, base_url: string, pat: string | null) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/ado/libraries', {
              body: { revision, name, base_url, ...(pat ? { pat } : {}) },
            }),
          ),
        '已新建 library',
      ),
    patchLibrary: (
      id: string,
      body: { name?: string; base_url?: string; keep_pat?: boolean; pat?: string },
      handle?: (e: ApiError) => boolean,
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().PATCH('/api/ado/libraries/{id}', {
              params: { path: { id } },
              body: { ...body, keep_pat: body.keep_pat ?? false, revision },
            }),
          ),
        '已保存 library',
        handle,
        opts,
      ),
    deleteLibrary: (id: string) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/ado/libraries/{id}', {
              params: { path: { id }, query: { revision } },
            }),
          ),
        '已删除 library',
      ),
    putPat: (id: string, pat: string) =>
      act(
        (revision) =>
          unwrap(
            api().PUT('/api/ado/libraries/{id}/pat', {
              params: { path: { id } },
              body: { revision, pat },
            }),
          ),
        'PAT 已保存',
      ),
    deletePat: (id: string) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/ado/libraries/{id}/pat', {
              params: { path: { id }, query: { revision } },
            }),
          ),
        'PAT 已删除',
      ),
    testConnection: (id: string, collection: string, pat: string | null) =>
      act(
        () =>
          unwrap(
            api().POST('/api/ado/libraries/{id}/test', {
              params: { path: { id } },
              body: { collection, ...(pat ? { pat } : {}) },
            }),
          ),
        undefined,
        undefined,
        { write: false },
      ),
    remoteProjects: (id: string, collection: string) =>
      act(
        () =>
          unwrap(
            api().GET('/api/ado/libraries/{id}/remote-projects', {
              params: { path: { id }, query: { collection } },
            }),
          ),
        undefined,
        undefined,
        { write: false },
      ),
    createProject: (library_id: string, collection: string, project: string) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/ado/projects', {
              body: { revision, library_id, collection, project },
            }),
          ),
        '已新建 project',
      ),
    patchProject: (
      id: string,
      body: { library_id?: string; collection?: string; project?: string },
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().PATCH('/api/ado/projects/{id}', {
              params: { path: { id } },
              body: { ...body, revision },
            }),
          ),
        '已保存 project',
        undefined,
        opts,
      ),
    deleteProject: (id: string) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/ado/projects/{id}', {
              params: { path: { id }, query: { revision } },
            }),
          ),
        '已删除 project',
      ),
    createLocalRepo: (name: string, path: string) =>
      act(
        (revision) =>
          unwrap(api().POST('/api/ado/local-repos', { body: { revision, name, path } })),
        '已新建本地仓库',
      ),
    patchLocalRepo: (
      id: string,
      body: { name?: string; path?: string },
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().PATCH('/api/ado/local-repos/{id}', {
              params: { path: { id } },
              body: { ...body, revision },
            }),
          ),
        '已保存本地仓库',
        undefined,
        opts,
      ),
    deleteLocalRepo: (id: string) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/ado/local-repos/{id}', {
              params: { path: { id }, query: { revision } },
            }),
          ),
        '已删除本地仓库',
      ),
    setActive: (library_id: string | null, project_id: string | null) =>
      act(
        (revision) =>
          unwrap(api().PUT('/api/ado/active', { body: { revision, library_id, project_id } })),
        '已设为当前',
      ),
    deleteCredential: (account: string) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/credentials/{account}', {
              params: { path: { account }, query: { revision } },
            }),
          ),
        '已清理凭据条目',
      ),
  }

  return {
    overview,
    ado,
    credentials,
    writable,
    revision,
    loadError,
    busy,
    notice,
    clearNotice,
    refresh,
    ...actions,
  }
}

export type SettingsContext = ReturnType<typeof useSettingsContext>
export const settingsContextKey: InjectionKey<SettingsContext> = Symbol('settings-context')
export type { ImportPreview }
