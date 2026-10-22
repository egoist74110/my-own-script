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
}

export type ActResult<T> = { ok: true; data: T } | { ok: false; error: ApiError }

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

  const overview = useQuery({
    queryKey: [...QK, 'overview'],
    enabled: online,
    retry: false,
    queryFn: (): Promise<SettingsResponse> => unwrap(api().GET('/api/settings')),
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

  const writable = computed(() => overview.data.value?.store_state === 'ok')
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
  ): Promise<ActResult<T>> {
    if (busy.value) return { ok: false, error: new ApiError(0, 'busy', '操作进行中') }
    busy.value = true
    notice.value = null
    try {
      const rev = revision.value
      if (rev === null) throw new ApiError(0, 'not_loaded', '设置尚未加载')
      const data = await fn(rev)
      await refresh()
      if (okText) notice.value = { kind: 'ok', text: okText }
      return { ok: true, data }
    } catch (e) {
      const error = e instanceof ApiError ? e : new ApiError(0, 'unknown', '操作失败')
      if (error.code === 'revision_conflict') {
        await refresh()
        notice.value = {
          kind: 'warn',
          text: '配置已被其他窗口或进程更新，已刷新为最新内容，请确认后重试。',
        }
      } else if (!handle?.(error)) {
        notice.value = {
          kind: 'error',
          text: error.message,
          ...(error.code === 'in_use' ? { tasks: error.tasks } : {}),
        }
      }
      return { ok: false, error }
    } finally {
      busy.value = false
    }
  }

  const actions = {
    previewImport: () => act(() => unwrap(api().POST('/api/settings/import/preview'))),
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
      act(() =>
        unwrap(
          api().POST('/api/ado/libraries/{id}/test', {
            params: { path: { id } },
            body: { collection, ...(pat ? { pat } : {}) },
          }),
        ),
      ),
    remoteProjects: (id: string, collection: string) =>
      act(() =>
        unwrap(
          api().GET('/api/ado/libraries/{id}/remote-projects', {
            params: { path: { id }, query: { collection } },
          }),
        ),
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
