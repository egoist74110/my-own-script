// 设置页测试用的假后端：按 openapi 形状回应，记录每次请求；不连任何真实服务。
import { vi } from 'vitest'
import type { components } from '@/api/schema'

type S = components['schemas']

export interface Call {
  method: string
  path: string
  query: Record<string, string>
  body: unknown
  raw: string
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
export const err = (status: number, code: string, message: string, extra: object = {}) =>
  json({ detail: { code, message, ...extra } }, status)

export const FAKE_PAT = 'fake-pat-UNIT-TEST-000111'

export function makeSettings(over: Partial<S['SettingsResponse']> = {}): S['SettingsResponse'] {
  return {
    app_version: '0.1.0',
    data_dir: '/tmp/fake-data',
    legacy_config_dir: '/tmp/fake-legacy',
    revision: 5,
    schema_version: 1,
    store_state: 'ok',
    import: { state: 'none' },
    ...over,
  }
}

export function makePreview(over: Partial<S['ImportPreview']> = {}): S['ImportPreview'] {
  return {
    errors: [],
    files: [
      { name: 'ui_settings.yaml', state: 'present' },
      { name: 'tasks.yaml', state: 'missing' },
    ],
    fingerprint: 'fp-1',
    libraries: [
      { id: 'lib:a', name: '示例库', base_url: 'http://ado.example.test/tfs', pat_status: 'found' },
    ],
    preserved_sections: ['telegram', 'ai'],
    projects: [{ id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '项目甲' }],
    source_dir: '/tmp/fake-legacy',
    task_count: 2,
    tasks_rule: 'migrated_from_flows',
    warnings: ['ADO 地址使用 HTTP 明文传输'],
    ...over,
  }
}

export function makeAdo(over: Partial<S['AdoResponse']> = {}): S['AdoResponse'] {
  return {
    active_library_id: 'lib:a',
    active_project_id: 'proj:a',
    libraries: [
      {
        id: 'lib:a',
        name: '示例库',
        base_url: 'https://ado.example.test/tfs',
        credential: { present: true, source: 'imported', state: 'present' },
      },
      {
        id: 'lib:b',
        name: '无凭据库',
        base_url: 'http://plain.example.test',
        credential: { present: false, source: 'unknown', state: 'missing' },
      },
    ],
    local_repos: [],
    projects: [{ id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '项目甲' }],
    revision: 5,
    ...over,
  }
}

export const makeCreds = (): S['CredentialStatus'][] => [
  {
    account: 'ado_pat:lib:a',
    kind: 'ado_pat',
    present: true,
    ref: 'lib:a',
    ref_name: '示例库',
    source: 'imported',
    state: 'present',
    updated_at: '2026-10-22T10:00:00Z',
  },
  {
    account: 'ado_pat:lib:gone',
    kind: 'ado_pat',
    present: false,
    ref: 'lib:gone',
    ref_name: null,
    source: 'unknown',
    state: 'orphan',
    updated_at: null,
  },
]

export interface Fake {
  state: { settings: S['SettingsResponse']; ado: S['AdoResponse']; creds: S['CredentialStatus'][] }
  calls: Call[]
  /** 覆盖某个路由；返回 undefined 则落到默认处理。 */
  handlers: ((c: Call) => Response | undefined | Promise<Response | undefined>)[]
  fetch: typeof fetch
  to(method: string, path: string): Call[]
}

export function createFake(): Fake {
  const fake: Fake = {
    state: { settings: makeSettings(), ado: makeAdo(), creds: makeCreds() },
    calls: [],
    handlers: [],
    to: (method, path) => fake.calls.filter((c) => c.method === method && c.path === path),
    fetch: vi.fn(async (input: Request) => {
      const url = new URL(input.url)
      const raw = input.method === 'GET' || input.method === 'DELETE' ? '' : await input.text()
      let body: unknown
      try {
        body = raw ? JSON.parse(raw) : undefined
      } catch {
        body = undefined
      }
      const call: Call = {
        method: input.method,
        path: url.pathname,
        query: Object.fromEntries(url.searchParams),
        body,
        raw,
      }
      if (call.path !== '/health') fake.calls.push(call)
      for (const h of fake.handlers) {
        const r = await h(call)
        if (r) return r
      }
      if (call.path === '/health')
        return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 1, alert: false })
      if (call.method === 'GET' && call.path === '/api/settings') return json(fake.state.settings)
      if (call.method === 'GET' && call.path === '/api/ado') return json(fake.state.ado)
      if (call.method === 'GET' && call.path === '/api/credentials') return json(fake.state.creds)
      if (call.method === 'POST' && call.path === '/api/settings/import/preview')
        return json(makePreview())
      return json({ revision: fake.state.ado.revision + 1 })
    }) as unknown as typeof fetch,
  }
  return fake
}
