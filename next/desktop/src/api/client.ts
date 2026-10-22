import createClient from 'openapi-fetch'
import { httpBase, type BackendConnection } from './connection'
import type { paths } from './schema'

export type ApiClient = ReturnType<typeof createClient<paths>>

/** 带 Bearer 头的 API 客户端；token 只放在 Authorization 头里，不出现在 URL。 */
export function createApiClient(conn: BackendConnection, fetchImpl?: typeof fetch): ApiClient {
  return createClient<paths>({
    baseUrl: httpBase(conn),
    headers: { Authorization: `Bearer ${conn.token}` },
    ...(fetchImpl ? { fetch: fetchImpl } : {}),
  })
}
