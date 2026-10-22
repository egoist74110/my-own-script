// 工单页的 API 辅助：类型别名、错误归一化与固定文案。
// 错误只携带后端给出的固定 code/category/message，不带请求参数，也不回显远端原文。
import type { components } from '@/api/schema'

type S = components['schemas']
export type WorkItemSummary = S['WorkItemSummary']
export type WorkItemDetail = S['WorkItemDetail']
export type ChildItem = S['ChildItem']
export type Comment = S['Comment']
export type Update = S['Update']
export type Attachment = S['Attachment']
export type WorkItemLink = S['WorkItemLink']
export type HtmlField = S['HtmlField']
export type AdoResponse = S['AdoResponse']
export type Project = S['Project']
export type LibraryView = S['LibraryView']

/** 固定看板列（与后端、旧 UI 一致；不引入 team/board 配置）。 */
export const COLUMNS = ['新建', '待开发', '开发中', '测试', '已关闭'] as const
export const DEFAULT_COLUMN = '开发中'
export const PAGE_SIZES = [10, 50, 100] as const
export const DEFAULT_PAGE_SIZE = 50

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly category: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function toApiError(status: number, body: unknown): ApiError {
  const detail =
    typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined
  if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>
    return new ApiError(
      status,
      typeof d.code === 'string' ? d.code : 'unknown',
      typeof d.message === 'string' ? d.message : `请求失败（HTTP ${status}）`,
      typeof d.category === 'string' ? d.category : null,
    )
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

/** 响应形状不符（例如后端版本不匹配）：当作 bad_response 而不是让页面崩溃。 */
export function badShape(): ApiError {
  return new ApiError(200, 'bad_shape', '响应格式异常')
}

const CATEGORY_TEXT: Record<string, string> = {
  unauthorized: '认证失败：PAT 无效或已过期',
  forbidden: '权限不足',
  redirect: 'ADO 返回了重定向，已拒绝跟随',
  blocked_origin: '请求被拦截：目标不在该代码库的地址范围内',
  tls: 'TLS 证书错误',
  timeout: '连接 ADO 超时',
  network: '无法连接 ADO',
  bad_response: 'ADO 响应格式异常',
  too_large: '内容过大，已拒绝读取',
}

/** 502 各分类的固定文案；其他 code 的固定文案。 */
export function errorText(e: unknown): string {
  if (!(e instanceof ApiError)) return '读取失败'
  switch (e.code) {
    case 'no_credential':
      return '该代码库未配置 PAT'
    case 'not_found':
      return '工单或项目不存在'
    case 'media_expired':
      return '图片已过期'
    case 'unsupported_media':
      return '非图片，可下载'
    case 'busy':
      return '服务繁忙，请稍后重试'
    case 'store_unavailable':
      return '本地存储不可用'
    case 'validation_error':
      return '请求参数无效'
    case 'network':
      return '无法连接后端'
    case 'ado_request_failed':
      return (e.category && CATEGORY_TEXT[e.category]) || 'ADO 请求失败'
    default:
      return '读取失败'
  }
}
