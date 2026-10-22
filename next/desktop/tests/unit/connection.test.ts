import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '@/api/client'
import {
  ConnectionUnavailableError,
  defaultTauriInvoke,
  getBackendConnection,
  parseConnection,
} from '@/api/connection'

describe('连接来源', () => {
  it('Tauri 环境调用 backend_connection', async () => {
    const invoke = vi.fn(async () => ({ port: 4321, token: 'tauri-token' }))
    const conn = await getBackendConnection({ getTauriInvoke: () => invoke, env: {} })
    expect(invoke).toHaveBeenCalledWith('backend_connection')
    expect(conn).toEqual({ port: 4321, token: 'tauri-token' })
  })

  it('Tauri 优先于 dev env', async () => {
    const invoke = vi.fn(async () => ({ port: 1, token: 'a' }))
    const conn = await getBackendConnection({
      getTauriInvoke: () => invoke,
      env: { VITE_TOOLBOX_PORT: '2', VITE_TOOLBOX_TOKEN: 'b' },
    })
    expect(conn.port).toBe(1)
  })

  it('dev 环境变量来源', async () => {
    const conn = await getBackendConnection({
      getTauriInvoke: () => null,
      env: { VITE_TOOLBOX_PORT: '51234', VITE_TOOLBOX_TOKEN: 'dev-token' },
    })
    expect(conn).toEqual({ port: 51234, token: 'dev-token' })
  })

  it('两种来源都没有 -> 抛 ConnectionUnavailableError', async () => {
    await expect(
      getBackendConnection({ getTauriInvoke: () => null, env: {} }),
    ).rejects.toBeInstanceOf(ConnectionUnavailableError)
  })

  it('拒绝非法连接信息', () => {
    for (const bad of [
      null,
      {},
      { port: 0, token: 'x' },
      { port: 70000, token: 'x' },
      { port: 1, token: '' },
      { port: 1.5, token: 'x' },
    ]) {
      expect(() => parseConnection(bad)).toThrow(ConnectionUnavailableError)
    }
  })

  it('defaultTauriInvoke 依据 __TAURI_INTERNALS__ 是否存在', () => {
    expect(defaultTauriInvoke()).toBeNull()
    vi.stubGlobal('__TAURI_INTERNALS__', { invoke: async () => ({}) })
    expect(defaultTauriInvoke()).toBeTypeOf('function')
  })

  it('不把 token 写入 localStorage', async () => {
    await getBackendConnection({
      getTauriInvoke: () => null,
      env: { VITE_TOOLBOX_PORT: '1', VITE_TOOLBOX_TOKEN: 'never-stored' },
    })
    expect(JSON.stringify({ ...localStorage })).not.toContain('never-stored')
  })
})

describe('API 客户端', () => {
  it('带 Bearer 头，token 不出现在 URL', async () => {
    const fetchMock = vi.fn(
      async (_req: Request) =>
        new Response(
          JSON.stringify({ status: 'ok', version: 'v', pid: 1, uptime_s: 1, alert: false }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    )
    const api = createApiClient(
      { port: 4000, token: 'abc-secret' },
      fetchMock as unknown as typeof fetch,
    )
    await api.GET('/health')
    const req = fetchMock.mock.calls[0]![0]
    expect(req.headers.get('authorization')).toBe('Bearer abc-secret')
    expect(req.url).toBe('http://127.0.0.1:4000/health')
    expect(req.url).not.toContain('abc-secret')
  })

  it('POST /api/system/alert 带 JSON body 与 Bearer', async () => {
    const fetchMock = vi.fn(
      async (_req: Request) =>
        new Response(JSON.stringify({ active: true, reason: 'x', changed_at: 't' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    )
    const api = createApiClient({ port: 4000, token: 'tk' }, fetchMock as unknown as typeof fetch)
    await api.POST('/api/system/alert', { body: { active: true, reason: 'x' } })
    const req = fetchMock.mock.calls[0]![0]
    expect(req.method).toBe('POST')
    expect(req.headers.get('authorization')).toBe('Bearer tk')
    expect(await req.json()).toEqual({ active: true, reason: 'x' })
  })

  it('非 dev 构建不读取 dev 变量（防止 token 被内联进 dist）', async () => {
    await expect(
      getBackendConnection({
        getTauriInvoke: () => null,
        env: { VITE_TOOLBOX_PORT: '2', VITE_TOOLBOX_TOKEN: 'baked' },
        dev: false,
      }),
    ).rejects.toThrow(ConnectionUnavailableError)
  })
})
