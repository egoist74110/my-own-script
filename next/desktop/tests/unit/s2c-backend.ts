// S2-C：有状态的假后端（只在假 fetch 里，按 openapi 形状回应）：写请求校验 revision（不匹配 409），
// 成功后改写 fake.state.ado 并递增 revision。不连任何真实服务。
import type { components } from '@/api/schema'
import { err, json, type Call, type Fake } from './settings-fake'

type S = components['schemas']

export function bump(fake: Fake): number {
  const n = fake.state.ado.revision + 1
  fake.state.ado = { ...fake.state.ado, revision: n }
  return n
}

export interface Backend {
  /** 模拟另一个窗口/进程：改写服务器状态（递增 revision），不经过本窗口。 */
  external(mutate: (ado: S['AdoResponse']) => void): number
  /** 本次测试里被 409 拒绝的写请求数。 */
  conflicts: Call[]
}

export function statefulAdo(fake: Fake): Backend {
  const backend: Backend = {
    conflicts: [],
    external(mutate) {
      const ado = structuredClone(fake.state.ado)
      mutate(ado)
      ado.revision += 1
      fake.state.ado = ado
      return ado.revision
    },
  }
  fake.handlers.push((c) => {
    if (!c.path.startsWith('/api/ado/') || c.method === 'GET') return undefined
    if (c.path.endsWith('/test') || c.path.endsWith('/remote-projects')) return undefined
    const rev =
      c.method === 'DELETE'
        ? Number(c.query.revision)
        : (c.body as { revision?: number } | undefined)?.revision
    if (rev !== fake.state.ado.revision) {
      backend.conflicts.push(c)
      return err(409, 'revision_conflict', '配置已被其他写者更新', {
        revision: fake.state.ado.revision,
      })
    }
    const ado = structuredClone(fake.state.ado)
    const body = (c.body ?? {}) as Record<string, unknown>
    const seg = c.path.split('/')
    const kind = seg[3]
    const id = seg[4] ? decodeURIComponent(seg[4]) : undefined
    let newId: string | undefined
    if (kind === 'libraries' && id && !seg[5] && c.method === 'PATCH') {
      const l = ado.libraries.find((x) => x.id === id)
      if (!l) return err(404, 'not_found', '不存在')
      if (typeof body.name === 'string') l.name = body.name
      if (typeof body.base_url === 'string') l.base_url = body.base_url
    } else if (kind === 'active' && c.method === 'PUT') {
      ado.active_library_id = body.library_id as string | null
      ado.active_project_id = body.project_id as string | null
    } else if (kind === 'projects' && id && c.method === 'PATCH') {
      const p = ado.projects.find((x) => x.id === id)
      if (!p) return err(404, 'not_found', '不存在')
      Object.assign(p, Object.fromEntries(Object.entries(body).filter(([k]) => k !== 'revision')))
    } else if (kind === 'local-repos') {
      const repos = ado.local_repos
      const b = body as { name?: string; path?: string }
      if (c.method !== 'DELETE') {
        if (
          (b.path !== undefined && (!b.path.startsWith('/') || b.path.split('/').includes('..'))) ||
          (b.name !== undefined && (b.name.length < 1 || b.name.length > 100))
        )
          return err(422, 'validation_error', '请求校验失败')
        if (b.name !== undefined && repos.some((r) => r.id !== id && r.name === b.name))
          return err(422, 'validation_error', '仓库名称已存在')
      }
      if (c.method === 'POST') {
        newId = `repo:new-${repos.length + 1}`
        repos.push({ id: newId, name: b.name!, path: b.path!, exists: true, warnings: [] })
      } else if (c.method === 'PATCH') {
        const r = repos.find((x) => x.id === id)
        if (!r) return err(404, 'not_found', '不存在')
        if (b.name !== undefined) r.name = b.name
        if (b.path !== undefined) {
          r.path = b.path
          r.warnings = []
        }
      } else if (c.method === 'DELETE') {
        if (!repos.some((x) => x.id === id)) return err(404, 'not_found', '不存在')
        ado.local_repos = repos.filter((x) => x.id !== id)
      }
    } else {
      return undefined
    }
    ado.revision += 1
    fake.state.ado = ado
    return json({ revision: ado.revision, ...(newId ? { id: newId } : {}) })
  })
  return backend
}
