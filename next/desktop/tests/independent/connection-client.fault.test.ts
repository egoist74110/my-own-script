// 连接信息来源与 API 客户端（独立编写）：Tauri / dev env 两种来源、Bearer、token 不进 URL。
import { describe, expect, it, vi } from 'vitest'
import {
  ConnectionUnavailableError,
  getBackendConnection,
  httpBase,
  parseConnection,
  wsUrl,
  type ConnectionSources,
} from '@/api/connection'
import { createApiClient } from '@/api/client'
import { FAKE_TOKEN } from './support'

const noTauri = (): null => null

function sources(over: Partial<ConnectionSources> = {}): ConnectionSources {
  return { getTauriInvoke: noTauri, env: {}, ...over }
}

describe('连接信息来源', () => {
  it('Tauri 环境调用 backend_connection 命令，并校验返回值', async () => {
    const invoke = vi.fn(async () => ({ port: 40123, token: FAKE_TOKEN }))
    const conn = await getBackendConnection(sources({ getTauriInvoke: () => invoke }))
    expect(invoke).toHaveBeenCalledTimes(1)
    expect(invoke).toHaveBeenCalledWith('backend_connection')
    expect(conn).toEqual({ port: 40123, token: FAKE_TOKEN })
  })

  it('Tauri 命令失败时错误向上抛出（不回退到 dev 环境变量）', async () => {
    const invoke = vi.fn(async () => {
      throw new Error('backend not ready')
    })
    await expect(
      getBackendConnection(
        sources({
          getTauriInvoke: () => invoke,
          env: { VITE_TOOLBOX_PORT: '5555', VITE_TOOLBOX_TOKEN: 'fake' },
        }),
      ),
    ).rejects.toThrow('backend not ready')
  })

  it('Tauri 命令返回非法结构时报 ConnectionUnavailableError', async () => {
    for (const bad of [null, 'x', { port: 0, token: 'a' }, { port: 1, token: '' }, {}]) {
      await expect(
        getBackendConnection(sources({ getTauriInvoke: () => async () => bad })),
      ).rejects.toBeInstanceOf(ConnectionUnavailableError)
    }
  })

  it('Tauri 与 dev 环境变量同时存在时以 Tauri 为准', async () => {
    const conn = await getBackendConnection(
      sources({
        getTauriInvoke: () => async () => ({ port: 1111, token: 'from-tauri' }),
        env: { VITE_TOOLBOX_PORT: '2222', VITE_TOOLBOX_TOKEN: 'from-env' },
      }),
    )
    expect(conn).toEqual({ port: 1111, token: 'from-tauri' })
  })

  it('dev 环境：端口字符串被转为数字', async () => {
    const conn = await getBackendConnection(
      sources({ env: { VITE_TOOLBOX_PORT: '5555', VITE_TOOLBOX_TOKEN: FAKE_TOKEN } }),
    )
    expect(conn).toEqual({ port: 5555, token: FAKE_TOKEN })
  })

  it('dev 环境缺少端口或 token 时报错，不回退到默认值', async () => {
    await expect(
      getBackendConnection(sources({ env: { VITE_TOOLBOX_PORT: '5555' } })),
    ).rejects.toBeInstanceOf(ConnectionUnavailableError)
    await expect(
      getBackendConnection(sources({ env: { VITE_TOOLBOX_TOKEN: FAKE_TOKEN } })),
    ).rejects.toBeInstanceOf(ConnectionUnavailableError)
    await expect(
      getBackendConnection(sources({ env: { VITE_TOOLBOX_PORT: '5555', VITE_TOOLBOX_TOKEN: '' } })),
    ).rejects.toBeInstanceOf(ConnectionUnavailableError)
  })

  it('非 Tauri 且无 dev 变量：报错', async () => {
    await expect(getBackendConnection(sources())).rejects.toBeInstanceOf(ConnectionUnavailableError)
  })
})

describe('parseConnection 边界', () => {
  it.each([
    ['端口 0', { port: 0, token: 'a' }],
    ['端口 65536', { port: 65536, token: 'a' }],
    ['端口负数', { port: -1, token: 'a' }],
    ['端口小数', { port: 5555.5, token: 'a' }],
    ['端口非数字字符串', { port: 'abc', token: 'a' }],
    ['端口 NaN', { port: Number.NaN, token: 'a' }],
    ['端口空字符串', { port: '', token: 'a' }],
    ['token 为空', { port: 5555, token: '' }],
    ['token 缺失', { port: 5555 }],
    ['token 非字符串', { port: 5555, token: 12 }],
    ['整体为 null', null],
    ['整体为数字', 5555],
  ])('%s → 拒绝', (_name, value) => {
    expect(() => parseConnection(value)).toThrow(ConnectionUnavailableError)
  })

  it('合法边界：端口 1 与 65535', () => {
    expect(parseConnection({ port: 1, token: 'x' })).toEqual({ port: 1, token: 'x' })
    expect(parseConnection({ port: 65535, token: 'x' })).toEqual({ port: 65535, token: 'x' })
  })

  it('地址只能是 127.0.0.1（HTTP 与 WS）', () => {
    const conn = { port: 5555, token: FAKE_TOKEN }
    expect(httpBase(conn)).toBe('http://127.0.0.1:5555')
    expect(wsUrl(conn)).toBe('ws://127.0.0.1:5555/ws/events')
    expect(wsUrl(conn)).not.toContain(FAKE_TOKEN)
  })
})

describe('createApiClient（Bearer 与 URL）', () => {
  type Seen = { url: string; auth: string | null; body: string }

  function recordingFetch(status = 200, body: unknown = {}) {
    const seen: Seen[] = []
    const fetchImpl = vi.fn(async (input: Request | string | URL, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(String(input), init)
      seen.push({
        url: req.url,
        auth: req.headers.get('authorization'),
        body: await req.text(),
      })
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      })
    }) as unknown as typeof fetch
    return { fetchImpl, seen }
  }

  const conn = { port: 5555, token: FAKE_TOKEN }

  it('GET /health 带 Bearer 头，URL 与任何请求中都不含 token', async () => {
    const { fetchImpl, seen } = recordingFetch(200, {
      status: 'ok',
      version: '1',
      pid: 1,
      uptime_s: 1,
      alert: false,
    })
    const api = createApiClient(conn, fetchImpl)
    const { data } = await api.GET('/health')
    expect(data?.status).toBe('ok')
    expect(seen).toHaveLength(1)
    expect(seen[0]!.url).toBe('http://127.0.0.1:5555/health')
    expect(seen[0]!.auth).toBe(`Bearer ${FAKE_TOKEN}`)
    expect(seen[0]!.url).not.toContain(FAKE_TOKEN)
  })

  it('POST /api/system/alert 带 Bearer 与 JSON 体，token 不进 URL', async () => {
    const { fetchImpl, seen } = recordingFetch(200, {
      active: true,
      reason: 'r',
      changed_at: 'T',
    })
    const api = createApiClient(conn, fetchImpl)
    await api.POST('/api/system/alert', { body: { active: true, reason: 'r' } })
    expect(seen[0]!.auth).toBe(`Bearer ${FAKE_TOKEN}`)
    expect(JSON.parse(seen[0]!.body)).toEqual({ active: true, reason: 'r' })
    expect(seen[0]!.url).not.toContain(FAKE_TOKEN)
  })

  it('401 作为 error 返回而不是抛出', async () => {
    const { fetchImpl } = recordingFetch(401, { detail: 'unauthorized' })
    const api = createApiClient(conn, fetchImpl)
    const res = await api.GET('/health')
    expect(res.error).not.toBeUndefined()
    expect(res.response.status).toBe(401)
  })

  it('网络异常时 fetch 的错误向上抛出（由调用方处理）', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('fetch failed')
    }) as unknown as typeof fetch
    const api = createApiClient(conn, fetchImpl)
    await expect(api.GET('/health')).rejects.toThrow('fetch failed')
  })
})
