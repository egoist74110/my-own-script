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
export type CredentialStatus = S['CredentialStatus']
export type ConnectionResult = S['ConnectionResult']

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
    const message = typeof d.message === 'string' ? d.message : `请求失败（HTTP ${status}）`
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
