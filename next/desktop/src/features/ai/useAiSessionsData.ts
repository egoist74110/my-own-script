import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import type { BackendRuntime } from '@/app/backend-runtime'
import type { AISessionData } from '@/api/events'
import { useBackendStore } from '@/stores/backend'
import {
  fetchAiOverview,
  fetchAiSessions,
  type ProfileView,
  type RepoView,
  type SessionView,
} from './api'

export function useAiSessionsData(runtime: BackendRuntime | undefined) {
  const queryClient = useQueryClient()
  const store = useBackendStore()
  const online = computed(() => store.connection === 'online')

  // 真实后端会话查询
  const sessionsQuery = useQuery({
    queryKey: ['ai', 'sessions'],
    enabled: online,
    queryFn: async () => {
      const client = runtime?.api()
      if (!client) throw new Error('未连接后端')
      return fetchAiSessions(client)
    },
    staleTime: 5000,
  })

  // 真实后端 AI 配置查询（profiles、selected_profile_id 等）
  const aiOverviewQuery = useQuery({
    queryKey: ['ai', 'overview'],
    enabled: online,
    queryFn: async () => {
      const client = runtime?.api()
      if (!client) throw new Error('未连接后端')
      return fetchAiOverview(client)
    },
    staleTime: 10000,
  })

  // 真实后端 ADO 本地仓库查询
  const adoQuery = useQuery({
    queryKey: ['ado', 'settings'],
    enabled: online,
    queryFn: async () => {
      const client = runtime?.api()
      if (!client) throw new Error('未连接后端')
      const res = await client.GET('/api/ado')
      return res.data
    },
    staleTime: 10000,
  })

  // 本地维护实时的会话状态缓存（由 WS ai.session 事件更新，不搞乐观写）
  const sessionStateOverrides = ref<Record<string, Partial<SessionView>>>({})

  let unbindEvents: (() => void) | null = null
  onMounted(() => {
    if (runtime) {
      unbindEvents = runtime.onEvent((envelope) => {
        if (envelope.topic === 'ai' && envelope.type === 'ai.session') {
          const data = envelope.data as unknown as AISessionData
          if (data?.session_id) {
            const current = sessionStateOverrides.value[data.session_id]
            const currSeq = typeof current?.last_seq === 'number' ? current.last_seq : -1
            const newSeq = typeof data.last_seq === 'number' ? data.last_seq : -1
            if (newSeq >= currSeq) {
              sessionStateOverrides.value[data.session_id] = {
                ...current,
                state: data.state,
                ended_reason: data.ended_reason,
                last_seq: data.last_seq,
              }
            }
          }
        }
      })
      runtime.subscribeAi?.()
    }
  })

  onUnmounted(() => {
    if (unbindEvents) {
      unbindEvents()
      unbindEvents = null
    }
    if (runtime) {
      runtime.unsubscribeAi?.()
    }
  })

  const profiles = computed<ProfileView[]>(() => {
    const p = aiOverviewQuery.data.value?.profiles ?? []
    return p as ProfileView[]
  })

  const localRepos = computed<RepoView[]>(() => {
    const r = adoQuery.data.value?.local_repos ?? []
    return r.map((item) => ({ id: item.id, name: item.name }))
  })

  function invalidateSessions() {
    void queryClient.invalidateQueries({ queryKey: ['ai', 'sessions'] })
  }

  return {
    sessionsQuery,
    aiOverviewQuery,
    adoQuery,
    sessionStateOverrides,
    profiles,
    localRepos,
    online,
    queryClient,
    invalidateSessions,
  }
}
