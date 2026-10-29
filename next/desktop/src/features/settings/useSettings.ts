// 设置页数据与动作（第一个接真实后端的页面）。
// 读：vue-query（键以 ['settings'] 开头，收到 settings.changed 或重连后整体失效）。
// 写：普通 async 函数而非 useMutation —— mutation 缓存会保留 variables，而 PAT 不得进入任何缓存。
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, inject, onScopeDispose, ref, watch, type InjectionKey } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import { useBackendStore } from '@/stores/backend'
import {
  ApiError,
  unwrap,
  type ActivityItem,
  type AdoResponse,
  type AIView,
  type AISettingsPatch,
  type CheckResponse,
  type CredentialStatus,
  type GroupCreate,
  type GroupPatch,
  type ImportPreview,
  type JobResponse,
  type MemberCreate,
  type MemberPatch,
  type ProfileCreate,
  type ProfilePatch,
  type SettingsResponse,
  type TaskView,
  type TelegramStatusData,
  type TelegramView,
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
  const telegramTabActive = ref(false)
  const aiTabActive = ref(false)
  const mcpTabActive = ref(false)
  const ai = useQuery({
    queryKey: [...QK, 'ai'],
    enabled: computed(() => online.value && aiTabActive.value),
    retry: false,
    queryFn: (): Promise<AIView> => unwrap(api().GET('/api/ai')),
  })
  let latestWsPoller: TelegramStatusData | null = null
  let wsEventSeq = 0

  function isSinceNewer(a: string, b: string): boolean {
    const ta = Date.parse(a)
    const tb = Date.parse(b)
    if (!isNaN(ta) && !isNaN(tb)) return ta > tb
    return a > b
  }

  const telegram = useQuery({
    queryKey: [...QK, 'telegram'],
    enabled: computed(() => online.value && telegramTabActive.value),
    retry: false,
    queryFn: async (): Promise<TelegramView> => {
      const startSeq = wsEventSeq
      const fresh = await unwrap(api().GET('/api/telegram'))
      const current = qc.getQueryData<TelegramView>([...QK, 'telegram'])
      const candidate = latestWsPoller ?? current?.poller ?? null

      if (candidate?.since && fresh?.poller?.since) {
        // 如果在当前 GET 在途期间收到了 WS 事件，或当前已缓存/收到的状态时间晚于 GET 结果的时间，
        // 则以更新的状态为准，不让陈旧的 GET 结果覆盖 poller 字段；其他非 poller 字段正常按 fresh 更新。
        if (wsEventSeq > startSeq || isSinceNewer(candidate.since, fresh.poller.since)) {
          return {
            ...fresh,
            poller: {
              ...fresh.poller,
              state: candidate.state,
              since: candidate.since,
              last_error_category:
                candidate.last_error_category ?? fresh.poller.last_error_category,
            },
          }
        }
      }
      latestWsPoller = null
      return fresh
    },
  })
  const tasks = useQuery({
    queryKey: ['tasks', 'list'],
    enabled: computed(() => online.value && telegramTabActive.value),
    retry: false,
    queryFn: async (): Promise<TaskView[]> => {
      try {
        const res = await unwrap(api().GET('/api/tasks'))
        return Array.isArray(res?.items) ? res.items : []
      } catch {
        return []
      }
    },
  })

  if (runtime) {
    const unbind = runtime.onEvent((ev) => {
      if (ev.type === 'telegram.status' && ev.data) {
        const d = ev.data as unknown as TelegramStatusData
        wsEventSeq++
        latestWsPoller = d
        qc.setQueryData([...QK, 'telegram'], (old: TelegramView | undefined) => {
          if (!old) return old
          if (old.poller?.since && isSinceNewer(old.poller.since, d.since)) {
            return old
          }
          return {
            ...old,
            poller: {
              ...old.poller,
              state: d.state,
              since: d.since,
              last_error_category: d.last_error_category ?? old.poller.last_error_category,
            },
          }
        })
      }
    })
    onScopeDispose(() => unbind())
  }

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
  const revision = computed(
    () =>
      ado.data.value?.revision ??
      overview.data.value?.revision ??
      telegram.data.value?.revision ??
      null,
  )
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
    putTelegramToken: (token: string, handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().PUT('/api/telegram/token', {
              body: { revision, token },
            }),
          ),
        'Bot Token 已保存',
        handle,
      ),
    importLegacyTelegramToken: (handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/token/import-legacy', {
              body: { revision },
            }),
          ),
        '已从旧应用导入 Bot Token',
        handle,
      ),
    verifyTelegramToken: (handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/token/verify', {
              body: { revision },
            }),
          ),
        undefined,
        handle,
      ),
    deleteTelegramToken: (handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/telegram/token', {
              params: { query: { revision } },
            }),
          ),
        'Bot Token 已删除',
        handle,
      ),
    enableTelegram: (
      ack_old_bot_stopped: boolean,
      delete_webhook = false,
      handle?: (e: ApiError) => boolean,
    ) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/control/enable', {
              body: { revision, ack_old_bot_stopped, delete_webhook },
            }),
          ),
        '已启用 Telegram 长轮询',
        handle,
      ),
    disableTelegram: (handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/control/disable', {
              body: { revision },
            }),
          ),
        '已停用 Telegram 长轮询',
        handle,
      ),
    retryTelegram: (handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/control/retry', {
              body: { revision },
            }),
          ),
        '已重试接管',
        handle,
      ),
    createBindCode: (handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/owner/bind-code', {
              body: { revision },
            }),
          ),
        undefined,
        handle,
      ),
    unbindOwner: (handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/telegram/owner', {
              params: { query: { revision } },
            }),
          ),
        '所有者已解绑',
        handle,
      ),
    patchTelegramSettings: (
      notify: { include_details?: boolean | null; ui_runs_to_owner?: boolean | null },
      handle?: (e: ApiError) => boolean,
    ) =>
      act(
        (revision) =>
          unwrap(
            api().PATCH('/api/telegram/settings', {
              body: { revision, notify },
            }),
          ),
        '通知设置已保存',
        handle,
      ),
    createAclGroup: (group: Omit<GroupCreate, 'revision'>, handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/acl/groups', {
              body: { ...group, revision },
            }),
          ),
        '已新建权限组',
        handle,
      ),
    patchAclGroup: (
      id: string,
      patch: Omit<GroupPatch, 'revision'>,
      handle?: (e: ApiError) => boolean,
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().PATCH('/api/telegram/acl/groups/{id}', {
              params: { path: { id } },
              body: { ...patch, revision },
            }),
          ),
        '已保存权限组',
        handle,
        opts,
      ),
    deleteAclGroup: (id: string, handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/telegram/acl/groups/{id}', {
              params: { path: { id }, query: { revision } },
            }),
          ),
        '已删除权限组',
        handle,
      ),
    createAclMember: (member: Omit<MemberCreate, 'revision'>, handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/acl/members', {
              body: { ...member, revision },
            }),
          ),
        '已添加成员',
        handle,
      ),
    patchAclMember: (
      id: string,
      patch: Omit<MemberPatch, 'revision'>,
      handle?: (e: ApiError) => boolean,
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().PATCH('/api/telegram/acl/members/{id}', {
              params: { path: { id } },
              body: { ...patch, revision },
            }),
          ),
        '已保存成员',
        handle,
        opts,
      ),
    deleteAclMember: (id: string, handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/telegram/acl/members/{id}', {
              params: { path: { id }, query: { revision } },
            }),
          ),
        '已删除成员',
        handle,
      ),
    putLegacyWhitelist: (legacy_whitelist: string[], handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().PUT('/api/telegram/acl/legacy-whitelist', {
              body: { revision, legacy_whitelist },
            }),
          ),
        '旧白名单已保存',
        handle,
      ),
    sendTestMessage: (handle?: (e: ApiError) => boolean) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/telegram/test-message', {
              body: { revision },
            }),
          ),
        '测试消息已发送',
        handle,
      ),
    getTelegramActivity: async (limit = 50): Promise<ActivityItem[]> => {
      const res = await unwrap(
        api().GET('/api/telegram/activity', {
          params: { query: { limit } },
        }),
      )
      return res?.items ?? []
    },
    createAiProfile: (
      body: Omit<ProfileCreate, 'revision'>,
      handle?: (e: ApiError) => boolean,
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().POST('/api/ai/profiles', {
              body: { ...body, revision },
            }),
          ),
        '已添加 AI CLI 配置',
        handle,
        opts,
      ),
    patchAiProfile: (
      id: string,
      body: Omit<ProfilePatch, 'revision'>,
      handle?: (e: ApiError) => boolean,
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().PATCH('/api/ai/profiles/{pid}', {
              params: { path: { pid: id } },
              body: { ...body, revision },
            }),
          ),
        '已保存 AI CLI 配置',
        handle,
        opts,
      ),
    deleteAiProfile: (
      id: string,
      handle?: (e: ApiError) => boolean,
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().DELETE('/api/ai/profiles/{pid}', {
              params: { path: { pid: id }, query: { revision } },
            }),
          ),
        '已删除 AI CLI 配置',
        handle,
        opts,
      ),
    checkAiProfile: async (id: string): Promise<CheckResponse> =>
      unwrap(
        api().POST('/api/ai/profiles/{pid}/check', {
          params: { path: { pid: id } },
        }),
      ),
    upgradeAiProfile: async (id: string): Promise<JobResponse> =>
      unwrap(
        api().POST('/api/ai/profiles/{pid}/upgrade', {
          params: { path: { pid: id } },
        }),
      ),
    cancelAiJob: async (id: string): Promise<JobResponse> =>
      unwrap(
        api().POST('/api/ai/jobs/{jid}/cancel', {
          params: { path: { jid: id } },
        }),
      ),
    patchAiSettings: (
      body: Omit<AISettingsPatch, 'revision'>,
      handle?: (e: ApiError) => boolean,
      opts?: { revision?: number; onConflict?: () => boolean },
    ) =>
      act(
        (revision) =>
          unwrap(
            api().PATCH('/api/ai/settings', {
              body: { ...body, revision },
            }),
          ),
        '已保存 AI 设置',
        handle,
        opts,
      ),
  }

  return {
    overview,
    ado,
    credentials,
    telegram,
    telegramTabActive,
    ai,
    aiTabActive,
    mcpTabActive,
    tasks,
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
