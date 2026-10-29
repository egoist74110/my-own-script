// 工单查询的公共部分：vue-query 键空间、统一缓存参数、取 API 客户端。
// 键：['work-items','ado']（项目列表）；['work-items','p',projectId,...]（该项目下的列表/详情/评论/历史/子项）。
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, inject } from 'vue'
import type { ApiClient } from '@/api/client'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'
import { ApiError, COLUMNS, unwrap } from './api'

export const WI_KEY = ['work-items'] as const
export const projectKey = (projectId: string) => [...WI_KEY, 'p', projectId] as const

/** 列表/详情/评论/历史/子项统一：30 秒新鲜、不因窗口聚焦重取、不自动重试（刷新按钮强制重取）。 */
export const QUERY_DEFAULTS = {
  retry: false,
  staleTime: 30_000,
  refetchOnWindowFocus: false,
} as const

export function useWiApi() {
  const runtime = inject(backendRuntimeKey, null)
  const store = useBackendStore()
  const qc = useQueryClient()
  const online = computed(() => store.connection === 'online')
  function api(): ApiClient {
    const a = runtime?.api()
    if (!a) throw new ApiError(0, 'not_connected', '后端未连接')
    return a
  }
  /** 给媒体缓存用：未连接时返回 null。 */
  const maybeApi = (): ApiClient | null => runtime?.api() ?? null
  return { api, maybeApi, online, qc, store }
}

/**
 * 看板列（线路顺序）：以接口 /api/work-items/columns 为准，读不到或为空时退回内置五列。
 * 列表页与详情页共用同一个查询键，所以只会请求一次。
 */
export function useBoardColumns() {
  const { api, online } = useWiApi()
  const q = useQuery({
    ...QUERY_DEFAULTS,
    queryKey: [...WI_KEY, 'columns'],
    enabled: online,
    queryFn: ({ signal }) => unwrap(api().GET('/api/work-items/columns', { signal })),
  })
  const columns = computed<string[]>(() => {
    const cols = q.data.value?.columns
    return Array.isArray(cols) && cols.length > 0 && cols.every((c) => typeof c === 'string')
      ? cols
      : [...COLUMNS]
  })
  return { columns, defaultColumn: computed(() => q.data.value?.default) }
}
