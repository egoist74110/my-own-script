// 任务与运行的 Query 与操作集合
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, inject, type Ref } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'
import { unwrap } from './api'

export const TASKS_KEY = ['tasks'] as const
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
