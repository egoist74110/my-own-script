// 任务与运行的 Query 与操作集合
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, inject, type Ref } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'
import {
  isRevisionConflict,
  unwrap,
  type CommandCreate,
  type CommandPatch,
  type ReleaseCreate,
  type ReleasePatch,
  type RunResponse,
} from './api'

export const TASKS_KEY = ['tasks'] as const
export const RELEASE_KEY = ['release-configs'] as const
export const releaseKey = (id: string) => ['release-configs', id] as const
export const RUNS_KEY = ['runs'] as const
export const taskKey = (id: string) => ['tasks', id] as const
export const runKey = (id: string) => ['run', id] as const

export const QUERY_DEFAULTS = {
  staleTime: 3000,
  retry: false,
}

export function useTasksApi() {
  const runtime = inject(backendRuntimeKey)
  const store = useBackendStore()
  const qc = useQueryClient()

  const online = computed(() => store.connection === 'online')

  function api() {
    const client = runtime?.api()
    if (!client) throw new Error('API 客户端未就绪')
    return client
  }

  return {
    runtime,
    store,
    qc,
    online,
    api,
  }
}

export function useTasksList(
  online: Ref<boolean>,
  api: () => ReturnType<typeof useTasksApi>['api'] extends () => infer T ? T : never,
) {
  return useQuery({
    ...QUERY_DEFAULTS,
    queryKey: TASKS_KEY,
    enabled: online,
    queryFn: async ({ signal }) => {
      return unwrap(api().GET('/api/tasks', { signal }))
    },
  })
}

export function useTaskRuns(
  taskId: Ref<string | null>,
  online: Ref<boolean>,
  api: () => ReturnType<typeof useTasksApi>['api'] extends () => infer T ? T : never,
) {
  return useQuery({
    ...QUERY_DEFAULTS,
    queryKey: computed(() => [...RUNS_KEY, taskId.value ?? '']),
    enabled: computed(() => online.value && Boolean(taskId.value)),
    queryFn: async ({ signal }) => {
      if (!taskId.value) return { items: [], cursor: null }
      return unwrap(
        api().GET('/api/runs', {
          signal,
          params: { query: { task_id: taskId.value, limit: 50, order: 'desc' } },
        }),
      )
    },
  })
}

export function useRunDetail(
  runId: Ref<string | null>,
  online: Ref<boolean>,
  api: () => ReturnType<typeof useTasksApi>['api'] extends () => infer T ? T : never,
) {
  return useQuery({
    ...QUERY_DEFAULTS,
    queryKey: computed(() => runKey(runId.value ?? '')),
    enabled: computed(() => online.value && Boolean(runId.value)),
    queryFn: async ({ signal }) => {
      if (!runId.value) return null
      return unwrap(
        api().GET('/api/runs/{run_id}', {
          signal,
          params: { path: { run_id: runId.value } },
        }),
      )
    },
  })
}

type ApiFn = () => ReturnType<typeof useTasksApi>['api'] extends () => infer T ? T : never

/** 发布配置列表（含每个配置下的运行命令与最近一次运行概览）。 */
export function useReleaseConfigs(online: Ref<boolean>, api: ApiFn) {
  return useQuery({
    ...QUERY_DEFAULTS,
    queryKey: RELEASE_KEY,
    enabled: online,
    queryFn: async ({ signal }) => unwrap(api().GET('/api/release-configs', { signal })),
  })
}

/** 读取单个发布配置的最新内容与 revision（绕过缓存，编辑前用它拿到最新版本）。 */
export function fetchReleaseConfig(qc: ReturnType<typeof useQueryClient>, api: ApiFn, id: string) {
  return qc.fetchQuery({
    queryKey: releaseKey(id),
    staleTime: 0,
    queryFn: ({ signal }) =>
      unwrap(
        api().GET('/api/release-configs/{config_id}', {
          signal,
          params: { path: { config_id: id } },
        }),
      ),
  })
}

/**
 * 一个配置下所有命令的运行记录，按创建时间倒序合并。
 * 接口只支持按命令（task_id）过滤，所以每条命令各取一页再合并；只含配置里现存的命令。
 */
export function useConfigRuns(commandIds: Ref<string[]>, online: Ref<boolean>, api: ApiFn) {
  return useQuery({
    ...QUERY_DEFAULTS,
    queryKey: computed(() => [...RUNS_KEY, 'config', commandIds.value.join(',')]),
    enabled: computed(() => online.value && commandIds.value.length > 0),
    queryFn: async ({ signal }) => {
      const pages = await Promise.all(
        commandIds.value.map((id) =>
          unwrap(
            api().GET('/api/runs', {
              signal,
              params: { query: { task_id: id, limit: 50, order: 'desc' } },
            }),
          ),
        ),
      )
      const items: RunResponse[] = pages.flatMap((p) => p.items)
      items.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0))
      return { items: items.slice(0, 50), cursor: null }
    },
  })
}

/**
 * 发布配置与运行命令的写操作。
 * 每个写操作都带调用方给的 revision（乐观锁）；成功后刷新配置列表与任务概览。
 * 遇到 revision_conflict 不重试：重新读取最新配置后把错误交给界面，让用户核对再保存。
 */
export function useReleaseActions() {
  const { api, qc } = useTasksApi()

  async function refresh() {
    await Promise.all([
      qc.invalidateQueries({ queryKey: RELEASE_KEY }),
      qc.invalidateQueries({ queryKey: TASKS_KEY }),
    ])
  }

  async function run<T>(op: () => Promise<T>): Promise<T> {
    try {
      const res = await op()
      await refresh()
      return res
    } catch (e) {
      // 冲突或对象已不存在：列表已过期，重新读取（不重发这次写入）
      if (isRevisionConflict(e) || (e as { code?: string })?.code === 'not_found') await refresh()
      throw e
    }
  }

  return {
    createConfig: (body: ReleaseCreate) =>
      run(() => unwrap(api().POST('/api/release-configs', { body }))),
    patchConfig: (id: string, body: ReleasePatch) =>
      run(() =>
        unwrap(
          api().PATCH('/api/release-configs/{config_id}', {
            params: { path: { config_id: id } },
            body,
          }),
        ),
      ),
    deleteConfig: (id: string, revision: number, detachAcl = false) =>
      run(() =>
        unwrap(
          api().DELETE('/api/release-configs/{config_id}', {
            params: {
              path: { config_id: id },
              query: { revision, ...(detachAcl ? { detach_acl: true } : {}) },
            },
          }),
        ),
      ),
    orderConfigs: (ids: string[], revision: number) =>
      run(() => unwrap(api().PUT('/api/release-configs/order', { body: { ids, revision } }))),
    createCommand: (configId: string, body: CommandCreate) =>
      run(() =>
        unwrap(
          api().POST('/api/release-configs/{config_id}/commands', {
            params: { path: { config_id: configId } },
            body,
          }),
        ),
      ),
    patchCommand: (configId: string, commandId: string, body: CommandPatch) =>
      run(() =>
        unwrap(
          api().PATCH('/api/release-configs/{config_id}/commands/{command_id}', {
            params: { path: { config_id: configId, command_id: commandId } },
            body,
          }),
        ),
      ),
    deleteCommand: (configId: string, commandId: string, revision: number, detachAcl = false) =>
      run(() =>
        unwrap(
          api().DELETE('/api/release-configs/{config_id}/commands/{command_id}', {
            params: {
              path: { config_id: configId, command_id: commandId },
              query: { revision, ...(detachAcl ? { detach_acl: true } : {}) },
            },
          }),
        ),
      ),
    orderCommands: (configId: string, ids: string[], revision: number) =>
      run(() =>
        unwrap(
          api().PUT('/api/release-configs/{config_id}/commands/order', {
            params: { path: { config_id: configId } },
            body: { ids, revision },
          }),
        ),
      ),
  }
}
