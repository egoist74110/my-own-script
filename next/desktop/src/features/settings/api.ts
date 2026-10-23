// 设置页的 API 辅助：错误归一化与类型别名。错误只携带后端给出的固定 code/message，
// 绝不带请求体（PAT 只出现在请求体里，不会进入 ApiError）。
import type { components } from '@/api/schema'

type S = components['schemas']
export type SettingsResponse = S['SettingsResponse']
export type ImportPreview = S['ImportPreview']
export type ImportState = S['ImportState']
export type AdoResponse = S['AdoResponse']
export type LibraryView = S['LibraryView']
export type Project = S['Project']
export type LocalRepoView = S['LocalRepoView']
export type CredentialStatus = S['CredentialStatus']
export type ConnectionResult = S['ConnectionResult']
export type TelegramView = S['TelegramView']
export type BotView = S['BotView']
export type Control = S['Control']
export type OwnerView = S['OwnerView']
export type Notify = S['Notify']
export type PollerView = S['PollerView']
export type ACLView = S['ACLView']
export type ACLGroup = S['ACLGroup']
export type ACLMember = S['ACLMember']
export type ActivityResponse = S['ActivityResponse']
export type ActivityItem = S['ActivityItem']
export type BindCodeResponse = S['BindCodeResponse']
export type GroupCreate = S['GroupCreate']
export type GroupPatch = S['GroupPatch']
export type MemberCreate = S['MemberCreate']
export type MemberPatch = S['MemberPatch']
export interface TelegramStatusData {
  state: PollerView['state']
  since: string
  last_error_category?: string | null
}
export type TaskView = S['TaskView']

export type AIView = S['AIView']
export type ProfileView = S['ProfileView']
export type ProfileCreate = S['ProfileCreate']
export type ProfilePatch = S['ProfilePatch']
export type AISettingsPatch = S['AISettingsPatch']
export type CheckResponse = S['CheckResponse']
export type JobResponse = S['JobResponse']
export type ResolvedCLI = S['ResolvedCLI']
export type AgyAnalysis = S['AgyAnalysis']
export type AgyDefaults = S['AgyDefaults']
export type ClaudeAnalysis = S['ClaudeAnalysis']
export type ClaudeDefaults = S['ClaudeDefaults']
export type CodexAnalysis = S['CodexAnalysis']
export type CodexDefaults = S['CodexDefaults']
export type ModelPresets = S['ModelPresets']

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
  /** `in_use` 时后端列出的引用任务名。 */
  get tasks(): string[] {
    const t = this.detail.tasks
    return Array.isArray(t) ? t.filter((x): x is string => typeof x === 'string') : []
  }
}

function toApiError(status: number, body: unknown): ApiError {
  const detail =
    typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined
  if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>
    const code = typeof d.code === 'string' ? d.code : 'unknown'
    const message =
      typeof d.message === 'string' && d.message
        ? d.message
        : (TELEGRAM_ERROR_MESSAGES[code] ?? `请求失败（HTTP ${status}）`)
    return new ApiError(status, code, message, d)
  }
  return new ApiError(status, 'unknown', `请求失败（HTTP ${status}）`)
}

interface Result {
  data?: unknown
  error?: unknown
  response: Response
}

/** 解开 openapi-fetch 结果：非 2xx 抛 ApiError；网络异常抛 `network`（不保留原始异常文本）。 */
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

/** PAT 最小长度（前端先挡，与后端约定一致）。返回错误文案或 null。 */
export const PAT_MIN_LENGTH = 8
export const patError = (value: string): string | null =>
  value.length < PAT_MIN_LENGTH ? `PAT 至少 ${PAT_MIN_LENGTH} 个字符` : null

export function originOf(url: string): string | null {
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

export const CATEGORY_TEXT: Record<ConnectionResult['category'], string> = {
  ok: '连接成功',
  unauthorized: '认证失败（PAT 无效或已过期）',
  forbidden: '权限不足',
  not_found: '地址或 collection 不存在',
  redirect: '被重定向（未跟随，PAT 未转发）',
  tls: 'TLS 证书错误',
  timeout: '连接超时',
  network: '网络不可达',
  bad_response: '响应格式异常',
  no_credential: '尚未保存 PAT',
}

export const TELEGRAM_ERROR_MESSAGES: Record<string, string> = {
  validation_error: '输入格式不正确',
  telegram_active: 'Telegram 正在运行中，无法修改配置，请先停用',
  ack_required: '需要确认旧应用已停止轮询',
  webhook_set: '检测到 Telegram 已设置 Webhook',
  legacy_missing: '旧应用中未找到 Telegram Bot Token',
  owner_not_bound: '尚未绑定所有者',
  telegram_request_failed: 'Telegram 请求失败',
  telegram_store_unavailable: 'Telegram 存储不可用（只读错误态）',
  revision_conflict: '配置已被修改，请刷新后重试',
  no_credential: '未配置 Bot Token',
  credential_backend_error: '凭据存储异常',
  store_unavailable: '配置存储不可用',
  store_busy: '配置存储正忙',
  busy: '系统正忙',
  not_found: '条目不存在',
}

export const POLLER_STATE_LABEL: Record<PollerView['state'], string> = {
  disabled: '已停用',
  starting: '启动中',
  polling: '轮询中',
  backoff: '等待退避',
  conflict: '轮询冲突',
  token_invalid: 'Token 无效',
  webhook_set: 'Webhook 已设置',
  store_unavailable: '存储不可用',
  stopping: '停止中',
}

export const POLLER_STATE_DESC: Partial<Record<PollerView['state'], string>> = {
  conflict: '另一个程序（可能是旧应用）正在轮询这个 Bot',
  token_invalid: 'Token 无效，请核对并重新录入',
  webhook_set: '已在 Telegram 设置 Webhook，接管前需删除 Webhook',
  store_unavailable: 'Telegram 存储处于只读错误态，无法启动轮询',
}

export const TELEGRAM_TOKEN_REGEX = /^\d{5,16}:[A-Za-z0-9_-]{30,64}$/

export function isTelegramTokenValid(token: string): boolean {
  return TELEGRAM_TOKEN_REGEX.test(token.trim())
}
