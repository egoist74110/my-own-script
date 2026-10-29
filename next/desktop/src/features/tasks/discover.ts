// 发布配置的“自动发现”：本地仓库 → ADO 项目/仓库，再按需读取分支、构建/Release 目标与 Agent 队列。
// 四个接口都只读；分支/目标/队列按步骤懒加载（enabled 为真才请求），来源（项目或仓库）变化时 key 变化，旧候选自动作废。
import { useMutation, useQuery } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'
import type { components } from '@/api/schema'
import { ApiError, errorText, unwrap } from './api'
import { useTasksApi } from './queries'

export type DiscoverRepoResponse = components['schemas']['DiscoverRepoResponse']
export type DiscoverBranchesResponse = components['schemas']['DiscoverBranchesResponse']
export type DiscoverTargetsResponse = components['schemas']['DiscoverTargetsResponse']
export type DiscoverQueuesResponse = components['schemas']['DiscoverQueuesResponse']
export type DiscoveredItem = components['schemas']['DiscoveredItem']

/** 发现接口的错误码 → 写清楚发生了什么、怎么办。 */
export const DISCOVER_ERROR_MESSAGES: Record<string, string> = {
  not_git_repo: '这个路径不是 Git 仓库。请确认目录存在，并且里面已经 git clone 或 git init 过。',
  no_remote:
    '这个仓库没有配置远端地址。请先用 git remote add origin 加上 ADO 的仓库地址，再重新识别。',
  remote_not_ado:
    '这个仓库的远端不是 Azure DevOps 地址，无法自动识别。可以展开“高级：手动填写”自己填。',
  pat_missing:
    '这个仓库所属的 ADO 库还没有配置 PAT。请到“设置 → ADO 连接”填写个人访问令牌后，再回来重试。',
  ado_unreachable:
    '连不上 ADO（超时、网络、认证或权限问题）。请检查网络或 VPN 与 PAT 权限后重试；也可以展开“高级：手动填写”。',
  ado_not_found: 'ADO 上找不到这个仓库或项目。请核对远端地址，或到设置里检查 ADO 项目是否正确。',
}

export function discoverErrorText(err: unknown): string {
  if (err instanceof ApiError) return DISCOVER_ERROR_MESSAGES[err.code] ?? errorText(err)
  return errorText(err)
}

/** 这类错误要去设置里处理（补 PAT），界面给“去设置”按钮。 */
export function discoverNeedsSettings(err: unknown): boolean {
  return err instanceof ApiError && err.code === 'pat_missing'
}

export function projectNotMatchedText(): string {
  return '没有找到和这个远端对应的 ADO 项目。请到“设置 → ADO 连接”里添加该项目（库地址、集合和项目名要与远端一致），再回来重新识别。'
}

const DISCOVER_QUERY = {
  retry: false,
  staleTime: 0,
  gcTime: 0,
  refetchOnWindowFocus: false,
} as const

/** 本地路径 → 项目与仓库。用户点“识别”才触发，所以是 mutation。 */
export function useDiscoverRepo() {
  const { api } = useTasksApi()
  return useMutation({
    mutationFn: (localRepoPath: string) =>
      unwrap(
        api().POST('/api/release-configs/discover/repo', {
          body: { local_repo_path: localRepoPath },
        }),
      ),
  })
}

export function useDiscoverBranches(
  projectId: Ref<string>,
  repoId: Ref<string>,
  enabled: Ref<boolean>,
) {
  const { api, online } = useTasksApi()
  return useQuery({
    ...DISCOVER_QUERY,
    queryKey: computed(() => ['release-discover', 'branches', projectId.value, repoId.value]),
    enabled: computed(
      () => online.value && enabled.value && Boolean(projectId.value) && Boolean(repoId.value),
    ),
    queryFn: ({ signal }) =>
      unwrap(
        api().GET('/api/release-configs/discover/branches', {
          signal,
          params: { query: { project_id: projectId.value, repo_id: repoId.value } },
        }),
      ),
  })
}

export function useDiscoverTargets(
  projectId: Ref<string>,
  repoId: Ref<string>,
  enabled: Ref<boolean>,
) {
  const { api, online } = useTasksApi()
  return useQuery({
    ...DISCOVER_QUERY,
    queryKey: computed(() => ['release-discover', 'targets', projectId.value, repoId.value]),
    enabled: computed(
      () => online.value && enabled.value && Boolean(projectId.value) && Boolean(repoId.value),
    ),
    queryFn: ({ signal }) =>
      unwrap(
        api().GET('/api/release-configs/discover/targets', {
          signal,
          params: { query: { project_id: projectId.value, repo_id: repoId.value } },
        }),
      ),
  })
}

export function useDiscoverQueues(projectId: Ref<string>, enabled: Ref<boolean>) {
  const { api, online } = useTasksApi()
  return useQuery({
    ...DISCOVER_QUERY,
    queryKey: computed(() => ['release-discover', 'queues', projectId.value]),
    enabled: computed(() => online.value && enabled.value && Boolean(projectId.value)),
    queryFn: ({ signal }) =>
      unwrap(
        api().GET('/api/release-configs/discover/queues', {
          signal,
          params: { query: { project_id: projectId.value } },
        }),
      ),
  })
}
