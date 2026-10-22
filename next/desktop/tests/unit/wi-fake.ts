// 工单页测试用的假后端：按 openapi 形状回应，记录每次请求（含 Authorization 头）；不连任何真实服务。
import { vi } from 'vitest'
import type { components } from '@/api/schema'
import { err, json, makeAdo } from './settings-fake'

type S = components['schemas']

export interface WiCall {
  method: string
  path: string
  query: Record<string, string>
  url: string
  auth: string | null
}

export const summary = (
  id: number,
  over: Partial<S['WorkItemSummary']> = {},
): S['WorkItemSummary'] => ({
  id,
  title: `工单标题 ${id}`,
  type: 'Bug',
  state: '开发中',
  assigned_to: '示例开发者',
  board_column: '开发中',
  priority: 2,
  severity: null,
  tags: [],
  area_path: 'A\\B',
  iteration_path: 'I\\1',
  created_date: '2026-10-01T08:00:00Z',
  changed_date: '2026-10-02T08:00:00Z',
  ...over,
})

export const detail = (
  id: number,
  over: Partial<S['WorkItemDetail']> = {},
): S['WorkItemDetail'] => ({
  ...summary(id),
  rev: 3,
  web_url: `https://ado.example.test/tfs/Col/%E9%A1%B9%E7%9B%AE%E7%94%B2/_workitems/edit/${id}`,
  html: {
    description: { html: '<p>描述正文</p>' },
    repro_steps: null,
    acceptance_criteria: null,
  },
  parent_id: null,
  child_ids: [],
  attachments: [],
  links: [],
  ...over,
})

export interface WiFake {
  ado: S['AdoResponse']
  /** 列表：key `${project_id}|${column}` */
  lists: Record<string, S['WorkItemsResponse'] | Response>
  details: Record<number, S['WorkItemDetail'] | Response>
  comments: Record<number, S['CommentsResponse'] | Response>
  updates: Record<number, S['UpdatesResponse'] | Response>
  children: Record<number, S['ChildrenResponse'] | Response>
  /** media id -> 响应工厂（每次调用返回新 Response） */
  media: Record<string, () => Response>
  calls: WiCall[]
  fetch: typeof fetch
  to(pathPrefix: string): WiCall[]
}

export const PNG = () =>
  new Response(new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]), {
    status: 200,
    headers: { 'content-type': 'image/png' },
  })
export const wiErr = (status: number, code: string, category?: string) =>
  err(status, code, '固定文案', category ? { category } : {})

export function createWiFake(): WiFake {
  const f: WiFake = {
    ado: makeAdo({
      active_project_id: 'proj:a',
      projects: [
        { id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '项目甲' },
        { id: 'proj:b', library_id: 'lib:b', collection: 'Col', project: '项目乙' },
      ],
    }),
    lists: {},
    details: {},
    comments: {},
    updates: {},
    children: {},
    media: {},
    calls: [],
    to: (p) => f.calls.filter((c) => c.path.startsWith(p)),
    fetch: vi.fn(async (input: Request) => {
      const url = new URL(input.url)
      const path = url.pathname
      if (path === '/health')
        return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 1, alert: false })
      f.calls.push({
        method: input.method,
        path,
        query: Object.fromEntries(url.searchParams),
        url: input.url,
        auth: input.headers.get('authorization'),
      })
      const pick = <T>(m: Record<string | number, T | Response>, k: string | number, dflt: T) => {
        const v = m[k]
        return v instanceof Response ? v.clone() : json(v ?? dflt)
      }
      if (path === '/api/ado') return json(f.ado)
      if (path === '/api/work-items')
        return pick(
          f.lists,
          `${url.searchParams.get('project_id')}|${url.searchParams.get('column')}`,
          {
            items: [],
            truncated: false,
            omitted: 0,
          },
        )
      let m = /^\/api\/work-items\/media\/(.+)$/.exec(path)
      if (m) {
        const make = f.media[m[1]!]
        return make ? make() : wiErr(404, 'media_expired')
      }
      m = /^\/api\/work-items\/(\d+)(?:\/(comments|updates|children))?$/.exec(path)
      if (m) {
        const id = Number(m[1])
        switch (m[2]) {
          case 'comments':
            return pick(f.comments, id, { comments: [], truncated: false })
          case 'updates':
            return pick(f.updates, id, { updates: [], truncated: false })
          case 'children':
            return pick(f.children, id, { items: [], truncated: false })
          default: {
            const v = f.details[id]
            return v instanceof Response ? v.clone() : v ? json(v) : wiErr(404, 'not_found')
          }
        }
      }
      return json({})
    }) as unknown as typeof fetch,
  }
  return f
}
