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
