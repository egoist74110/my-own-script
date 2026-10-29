// 任务与运行 API 辅助：错误归一化、时间/状态格式化与类型引用。
// 前端类型只用 schema.d.ts，不手写第二套 DTO 类型。
import type { PillState } from '@/components/pill'
import type { components } from '@/api/schema'

export type TaskView = components['schemas']['TaskView']
export type TaskListResponse = components['schemas']['TaskListResponse']
export type TaskResponse = components['schemas']['TaskResponse']
export type TaskCreate = components['schemas']['TaskCreate']
export type TaskPatch = components['schemas']['TaskPatch']
export type TaskOrder = components['schemas']['TaskOrder']
export type ReleaseView = components['schemas']['ReleaseView']
export type ReleaseListResponse = components['schemas']['ReleaseListResponse']
export type ReleaseResponse = components['schemas']['ReleaseResponse']
export type ReleaseCreate = components['schemas']['ReleaseCreate']
export type ReleasePatch = components['schemas']['ReleasePatch']
export type ReleaseTarget = components['schemas']['ReleaseTarget']
export type ReleaseTargetInput = components['schemas']['ReleaseTargetInput']
export type ReleaseBranch = components['schemas']['ReleaseBranch']
export type ReleaseBranchInput = components['schemas']['ReleaseBranchInput']
export type CommandView = components['schemas']['CommandView']
export type CommandCreate = components['schemas']['CommandCreate']
export type CommandPatch = components['schemas']['CommandPatch']
export type LastRunSummary = components['schemas']['LastRunSummary']
export type FlowInput = components['schemas']['FlowInput']
export type TargetInput = components['schemas']['TargetInput']
export type PlanResponse = components['schemas']['PlanResponse']
export type PlanStep = components['schemas']['PlanStep']
export type PlanTarget = components['schemas']['PlanTarget']
export type PreflightRequest = components['schemas']['PreflightRequest']
export type StartRequest = components['schemas']['StartRequest']
export type StartResponse = components['schemas']['StartResponse']
export type RunResponse = components['schemas']['RunResponse']
export type RunListResponse = components['schemas']['RunListResponse']
export type RunEventsResponse = components['schemas']['RunEventsResponse']
export type RunEventData = components['schemas']['RunEventData']
export type LogPayload = components['schemas']['LogPayload']
export type StatePayload = components['schemas']['StatePayload']
export type StepView = components['schemas']['StepView']
export type EffectView = components['schemas']['EffectView']
export type TaskOperation = RunResponse['operation']
export type RunStatus = RunResponse['status']

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function toApiError(status: number, body: unknown): ApiError {
  const detail =
    typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined
  if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>
    const code = typeof d.code === 'string' ? d.code : 'unknown'
    const message =
      typeof d.message === 'string'
        ? d.message
        : (TASK_ERROR_MESSAGES[code] ?? `请求失败（HTTP ${status}）`)
    return new ApiError(status, code, message, d)
  }
  if (typeof detail === 'string') {
    return new ApiError(status, 'unknown', detail)
  }
  return new ApiError(status, 'unknown', `请求失败（HTTP ${status}）`)
}

interface Result {
  data?: unknown
  error?: unknown
  response: Response
}

export async function unwrap<R extends Result>(req: Promise<R>): Promise<NonNullable<R['data']>> {
  let result: R
  try {
    result = await req
  } catch {
    throw new ApiError(0, 'network', '无法连接后端')
  }
  if (result.error !== undefined) throw toApiError(result.response.status, result.error)
  return result.data as NonNullable<R['data']>
}

export const TASK_ERROR_MESSAGES: Record<string, string> = {
  revision_conflict: '配置已被修改，请刷新后重试',
  task_active: '任务正在运行中，无法修改、删除或重复启动',
  resource_active: '任务引用的仓库或发布资源正在被占用',
  task_referenced: '任务被 Telegram 权限组引用，无法直接删除',
  idempotency_conflict: '重复提交冲突，请勿重复操作',
  plan_expired: '执行计划已过期，推送和发布未执行，请重新确认',
  plan_changed: '仓库分支或远端状态已改变，执行计划已失效，请重新确认',
  no_credential: '未配置凭据，请前往「设置 → ADO 连接」配置个人访问令牌 (PAT)',
  unsafe_repository: '仓库路径或配置不安全，无法执行',
  unsupported_task: '任务配置包含不支持的操作或协议',
  run_store_unavailable: '运行记录库不可用（只读模式），无法启动新任务或记录取消',
  store_unavailable: '配置存储不可用，无法修改任务',
  busy: '系统繁忙，当前已有过多排队任务，请稍后重试',
  ado_request_failed: 'ADO 请求失败',
  not_found: '任务或运行记录不存在',
  validation_error: '输入校验失败，请检查字段填写',
}

export const RUN_REASON_MESSAGES: Record<string, string> = {
  git_failed: 'Git 操作失败',
  repo_needs_attention: '代码仓库需要注意或有未提交变动',
  plan_changed: '执行计划发生变更',
  build_failed: '构建失败',
  release_failed: '发布部署失败',
  deploy_failed: '部署失败',
  remote_failed: '远端服务执行失败',
  remote_running: '远端任务仍在执行中',
  remote_unknown: '远端状态未知',
  local_failed: '本地执行失败',
  interrupted: '执行被中断',
  timeout: '执行超时',
  cancelled: '已取消',
  busy: '系统繁忙',
  backend_restart: '后端服务已重启',
  worker_lost: '执行进程异常丢失',
}

export function formatRunReason(reasonCode?: string | null): string {
  if (!reasonCode) return ''
  return RUN_REASON_MESSAGES[reasonCode] ?? reasonCode
}

/**
 * 发布配置与运行命令的错误文案：写清楚出了什么事、接下来怎么办。
 * 校验失败时后端的 message 是具体原因（如“目标仍被运行命令引用”），翻成“怎么办”；认不出的原样展示。
 */
export const RELEASE_ERROR_MESSAGES: Record<string, string> = {
  revision_conflict: '这份配置刚刚被修改过，已重新读取最新内容。请核对后再保存一次。',
  task_active: '这里有命令正在运行。等运行结束或先停止它，再重试。',
  task_referenced: '有命令被 Telegram 权限组引用，不能直接删除。',
  resource_active: '配置用到的仓库或发布资源正被占用。稍后再试。',
  not_found: '配置或命令已不存在。列表已刷新，请重新选择。',
  target_in_use: '这个发布目标仍被运行命令使用，不能删除。请先在对应命令里取消勾选它。',
  branch_in_use: '这个分支仍被运行命令使用，不能删除。请先把这些命令改用别的分支。',
}

function releaseValidationHint(message: string): string {
  // 旧版后端把引用保护当成 validation_error 返回，按文本兜底；新版走 target_in_use / branch_in_use 错误码
  if (message.includes('目标仍被运行命令引用')) return RELEASE_ERROR_MESSAGES.target_in_use!
  if (message.includes('分支仍被运行命令引用')) return RELEASE_ERROR_MESSAGES.branch_in_use!
  if (message.includes('所选分支必须属于本配置'))
    return '命令里选的分支已不在这个配置里。请重新选择分支。'
  if (message.includes('所选目标必须属于本配置'))
    return '命令里选的目标已不在这个配置里，或重复选择。请重新勾选目标。'
  if (message.includes('TG 指令已存在')) return '这个 TG 命令已被别的命令使用。请换一个名字。'
  if (message.includes('项目不存在')) return '找不到所选的 ADO 项目。请先在设置里同步项目。'
  if (!message || message === '任务配置无效') return TASK_ERROR_MESSAGES.validation_error!
  return message
}

export function releaseErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'validation_error') return releaseValidationHint(err.message)
    if (err.code === 'target_in_use' || err.code === 'branch_in_use')
      return RELEASE_ERROR_MESSAGES[err.code]!
    return RELEASE_ERROR_MESSAGES[err.code] ?? errorText(err)
  }
  return errorText(err)
}

export function isRevisionConflict(err: unknown): boolean {
  return err instanceof ApiError && err.code === 'revision_conflict'
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    return TASK_ERROR_MESSAGES[err.code] ?? err.message
  }
  if (err instanceof Error) return err.message
  return '发生未知错误'
}

export function mapStatusToPill(taskEnabled: boolean, runStatus?: RunStatus | null): PillState {
  if (!taskEnabled) return 'disabled'
  if (!runStatus) return 'queued'
  switch (runStatus) {
    case 'queued':
      return 'queued'
    case 'running':
      return 'running'
    case 'cancelling':
      return 'stopping'
    case 'succeeded':
      return 'success'
    case 'failed':
      return 'failed'
    case 'cancelled':
      return 'cancelled'
    case 'unknown':
      return 'verify'
    default:
      return 'queued'
  }
}

export function resolveRowPillState(
  task: TaskView,
  isSelected: boolean,
  liveStatus: RunStatus | null,
): PillState | null {
  if (!task.enabled) return 'disabled'
  const status = isSelected
    ? (liveStatus ?? task.last_run?.status ?? null)
    : task.active_run_id
      ? 'running'
      : (task.last_run?.status ?? null)
  if (!status) return null
  return mapStatusToPill(true, status)
}

export function operationLabel(op?: TaskOperation | null): string {
  switch (op) {
    case 'sync_build_release':
      return '同步 → 构建 → 发布'
    case 'deploy_only':
      return '只发布'
    case 'rollback':
      return '回滚'
    default:
      return '运行'
  }
}

export function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch {
    return '—'
  }
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return '—'
  }
}

export function formatDuration(
  startedAt?: string | null,
  finishedAt?: string | null,
  nowMs = Date.now(),
): string {
  if (!startedAt) return '—'
  const start = new Date(startedAt).getTime()
  if (Number.isNaN(start)) return '—'
  const end = finishedAt ? new Date(finishedAt).getTime() : nowMs
  if (Number.isNaN(end) || end < start) return '0:00'
  const totalSecs = Math.floor((end - start) / 1000)
  const mins = Math.floor(totalSecs / 60)
  const secs = totalSecs % 60
  return `${mins}:${String(secs).padStart(2, '0')}`
}

export function formatRelativeTime(iso?: string | null, nowMs = Date.now()): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const diffSec = Math.floor((nowMs - t) / 1000)
  if (diffSec < 60) return '刚刚'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`
  if (diffSec < 86400 * 2) return '昨天'
  return formatDateTime(iso)
}

export function formatRepoShort(repoName?: string | null, localRepoPath?: string | null): string {
  if (repoName && repoName.trim()) return repoName.trim()
  if (!localRepoPath) return '—'
  const normalized = localRepoPath.replace(/[/\\]+$/, '')
  const lastSlash = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'))
  return lastSlash >= 0 ? normalized.slice(lastSlash + 1) : normalized
}

/** 配置下最近一次运行（按创建时间取各命令 last_run 里最新的一条）。 */
export function configLastRun(
  cfg: Pick<ReleaseView, 'commands'>,
): (LastRunSummary & { command: CommandView }) | null {
  let best: (LastRunSummary & { command: CommandView }) | null = null
  for (const c of cfg.commands) {
    const r = c.last_run
    if (!r) continue
    if (!best || r.created_at > best.created_at) best = { ...r, command: c }
  }
  return best
}

/** 配置下正在运行的命令（若有多条，取第一条）。 */
export function configActiveCommand(cfg: Pick<ReleaseView, 'commands'>): CommandView | null {
  return cfg.commands.find((c) => Boolean(c.active_run_id)) ?? null
}

/** 配置列表项的状态标签：有运行中的命令显示运行中，否则取最近一次运行的结果。 */
export function resolveConfigPillState(
  cfg: Pick<ReleaseView, 'commands'>,
  isSelected: boolean,
  liveStatus: RunStatus | null,
): PillState | null {
  const active = configActiveCommand(cfg)
  const last = configLastRun(cfg)
  const fallback: RunStatus | null = active ? 'running' : (last?.status ?? null)
  const status = isSelected ? (liveStatus ?? fallback) : fallback
  if (!status) return null
  return mapStatusToPill(true, status)
}

/** 命令选中的目标名（按命令里的顺序）；找不到的目标跳过。 */
export function commandTargetNames(
  cfg: Pick<ReleaseView, 'targets'>,
  cmd: Pick<CommandView, 'target_ids'>,
): string[] {
  const byId = new Map((cfg.targets ?? []).map((t) => [t.id, t.name]))
  return (cmd.target_ids ?? []).map((id) => byId.get(id)).filter((n): n is string => Boolean(n))
}

/** 命令用的分支：没选返回 null；选了但配置里已经没有这个分支也返回 null（用 commandBranchIssue 区分）。 */
export function commandBranch(
  cfg: Pick<ReleaseView, 'branches'>,
  cmd: Pick<CommandView, 'branch_id'>,
): ReleaseBranch | null {
  if (!cmd.branch_id) return null
  return (cfg.branches ?? []).find((b) => b.id === cmd.branch_id) ?? null
}

/** 命令的分支有什么问题：没选 / 已不存在；没问题返回 null。 */
export function commandBranchIssue(
  cfg: Pick<ReleaseView, 'branches'>,
  cmd: Pick<CommandView, 'branch_id'>,
): 'none' | 'missing' | null {
  if (!cmd.branch_id) return 'none'
  return commandBranch(cfg, cmd) ? null : 'missing'
}

/** 命令一句话概述：“main 分支，发布 管理、租户”；分支有问题时如实写出。 */
export function commandRouteText(
  cfg: Pick<ReleaseView, 'branches' | 'targets'>,
  cmd: Pick<CommandView, 'branch_id' | 'target_ids'>,
): string {
  const issue = commandBranchIssue(cfg, cmd)
  const branch =
    issue === 'none'
      ? '未选分支'
      : issue === 'missing'
        ? '分支已不存在'
        : `${commandBranch(cfg, cmd)!.build_branch} 分支`
  const names = commandTargetNames(cfg, cmd)
  return `${branch}，${names.length ? `发布 ${names.join('、')}` : '未选发布目标'}`
}
