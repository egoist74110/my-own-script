// S2-B 独立测试：工单页接真实接口（整 App 挂载，假 fetch 按 openapi 形状回应，不连真实服务）。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from '../unit/boot'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'

type Resp = () => Response | Promise<Response>
interface Call {
  path: string
  query: Record<string, string>
  auth: string | null
  signal: AbortSignal
  url: string
}
type Boot = Awaited<ReturnType<typeof boot>>

const j = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
const apiErr = (status: number, code: string, category?: string) =>
  j(
    { detail: { code, message: 'LEAK-BACKEND-MESSAGE', ...(category ? { category } : {}) } },
    status,
  )
const png = () =>
  new Response(new Uint8Array([137, 80, 78, 71]), {
    status: 200,
    headers: { 'content-type': 'image/png' },
  })
function deferred<T>() {
  let resolve!: (v: T) => void
  const p = new Promise<T>((r) => (resolve = r))
  return { p, resolve }
}

const ADO = {
  active_library_id: 'lib:a',
  active_project_id: 'proj:a',
  libraries: [
    {
      id: 'lib:a',
      name: '示例库',
      base_url: 'https://ado.example.test/tfs',
      credential: { present: true, source: 'imported', state: 'present' },
    },
  ],
  local_repos: [],
  projects: [
    { id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '项目甲' },
    { id: 'proj:b', library_id: 'lib:a', collection: 'Col', project: '项目乙' },
  ],
  revision: 5,
}
const sum = (id: number, over: Record<string, unknown> = {}) => ({
  id,
  title: `标题 ${id}`,
  type: 'Bug',
  state: '开发中',
  assigned_to: '甲',
  board_column: '开发中',
  priority: 2,
  severity: null,
  tags: [],
  area_path: null,
  iteration_path: null,
  created_date: null,
  changed_date: '2026-10-02T08:00:00Z',
  ...over,
})
const det = (id: number, over: Record<string, unknown> = {}) => ({
  ...sum(id),
  rev: 3,
  web_url: 'https://ado.example.test/tfs/Col/_workitems/edit/' + id,
  html: { description: { html: '<p>正文</p>' } },
  parent_id: null,
  child_ids: [],
  attachments: [],
  links: [],
  ...over,
})

function makeWi() {
  const w = {
    ado: ADO as unknown,
    adoResp: null as Resp | null,
    list: {} as Record<string, Resp>,
    detail: {} as Record<number, Resp>,
    comments: {} as Record<number, Resp>,
    updates: {} as Record<number, Resp>,
    children: {} as Record<number, Resp>,
    media: {} as Record<string, Resp>,
    calls: [] as Call[],
    count: (path: string) => w.calls.filter((c) => c.path === path).length,
    mediaCount: (id: string) =>
      w.calls.filter((c) => c.path === `/api/work-items/media/${encodeURIComponent(id)}`).length,
    fetch: undefined as unknown as typeof fetch,
  }
  w.fetch = vi.fn(async (req: Request) => {
    const u = new URL(req.url)
    if (u.pathname === '/health')
      return j({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 1, alert: false })
    w.calls.push({
      path: u.pathname,
      query: Object.fromEntries(u.searchParams),
      auth: req.headers.get('authorization'),
      signal: req.signal,
      url: req.url,
    })
    if (u.pathname === '/api/ado') return w.adoResp ? w.adoResp() : j(w.ado)
    if (u.pathname === '/api/work-items') {
      const key = `${u.searchParams.get('project_id')}|${u.searchParams.get('column')}`
      const r = w.list[key]
      return r ? r() : j({ items: [sum(1), sum(2)], truncated: false, omitted: 0 })
    }
    const mm = /^\/api\/work-items\/media\/(.+)$/.exec(u.pathname)
    if (mm) {
      const r = w.media[decodeURIComponent(mm[1]!)]
      return r ? r() : apiErr(404, 'media_expired')
    }
    const m = /^\/api\/work-items\/(\d+)(?:\/(comments|updates|children))?$/.exec(u.pathname)
    if (m) {
      const id = Number(m[1])
      const tables: Record<string, Record<number, Resp>> = {
        comments: w.comments,
        updates: w.updates,
        children: w.children,
        '': w.detail,
      }
      const r = tables[m[2] ?? '']![id]
      if (r) return r()
      if (m[2] === 'comments') return j({ comments: [], truncated: false })
      if (m[2] === 'updates') return j({ updates: [], truncated: false })
      if (m[2] === 'children') return j({ items: [], truncated: false })
      return apiErr(404, 'not_found')
    }
    return apiErr(404, 'not_found')
  }) as unknown as typeof fetch
  return w
}
type Wi = ReturnType<typeof makeWi>

const instances: Boot[] = []
async function settle(n = 8) {
  for (let i = 0; i < n; i++) await flushPromises()
}
async function open(w: Wi, path = '/work-items') {
  const b = await boot({ path, fetchImpl: w.fetch })
  b.sock.emit(hello())
  await settle()
  instances.push(b)
  return b
}
const row = (b: Boot, id: number) => b.wrapper.get(`[data-testid=wi-row-${id}]`)
async function clickRow(b: Boot, id: number) {
  await row(b, id).trigger('click')
  await settle()
}
async function mousedownTab(b: Boot, list: string, label: string) {
  const t = b.wrapper
    .get(`[role=tablist][aria-label="${list}"]`)
    .findAll('[role=tab]')
    .find((x) => x.text().startsWith(label))
  expect(t, `tab ${label}`).toBeTruthy()
  await t!.trigger('mousedown', { button: 0 })
  await settle()
}
const detailEl = (b: Boot) => b.wrapper.find('section[aria-label="工单详情"]')

// 对象 URL（jsdom 没有）
let urlN = 0
let created: { url: string; blob: Blob }[] = []
let revoked: string[] = []
beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  urlN = 0
  created = []
  revoked = []
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: (blob: Blob) => {
      const url = `blob:fake/${++urlN}`
      created.push({ url, blob })
      return url
    },
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: (u: string) => {
      revoked.push(u)
    },
  })
})
afterEach(async () => {
  for (const b of instances.splice(0)) await b.done()
  document.body.innerHTML = ''
  delete (URL as unknown as Record<string, unknown>).createObjectURL
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL
  localStorage.clear()
  sessionStorage.clear()
  vi.restoreAllMocks()
})

describe('列表错误态与固定文案', () => {
  it('无项目：引导文案 + 前往设置入口，项目下拉禁用', async () => {
    const w = makeWi()
    w.ado = { ...ADO, projects: [], active_project_id: null }
    const b = await open(w)
    expect(b.wrapper.find('[data-testid=no-projects]').text()).toContain('还没有配置 ADO 项目')
    expect(b.wrapper.get('[data-testid=no-projects] a').attributes('href')).toBe('/settings')
    expect(
      (b.wrapper.get('[data-testid=project-select]').element as HTMLSelectElement).disabled,
    ).toBe(true)
    expect(w.count('/api/work-items')).toBe(0)
  })

  it('列表 no_credential：显示「该代码库未配置 PAT」并给出设置入口', async () => {
    const w = makeWi()
    w.list['proj:a|开发中'] = () => apiErr(502, 'no_credential')
    const b = await open(w)
    const e = b.wrapper.get('[data-testid=wi-error]')
    expect(e.text()).toContain('该代码库未配置 PAT')
    expect(e.get('a').attributes('href')).toBe('/settings')
  })

  const CATS: [string, string][] = [
    ['unauthorized', '认证失败：PAT 无效或已过期'],
    ['forbidden', '权限不足'],
    ['redirect', 'ADO 返回了重定向，已拒绝跟随'],
    ['blocked_origin', '请求被拦截：目标不在该代码库的地址范围内'],
    ['tls', 'TLS 证书错误'],
    ['timeout', '连接 ADO 超时'],
    ['network', '无法连接 ADO'],
    ['bad_response', 'ADO 响应格式异常'],
    ['too_large', '内容过大，已拒绝读取'],
    ['some_new_category', 'ADO 请求失败'],
  ]
  it.each(CATS)(
    'ado_request_failed/%s → 固定文案「%s」，且不回显后端 message',
    async (cat, text) => {
      const w = makeWi()
      w.list['proj:a|开发中'] = () => apiErr(502, 'ado_request_failed', cat)
      const b = await open(w)
      const t = b.wrapper.get('[data-testid=wi-error]').text()
      expect(t).toContain(text)
      expect(t).not.toContain('LEAK-BACKEND-MESSAGE')
    },
  )

  it.each([
    ['not_found', '工单或项目不存在'],
    ['busy', '服务繁忙，请稍后重试'],
    ['store_unavailable', '本地存储不可用'],
    ['validation_error', '请求参数无效'],
    ['some_unknown_code', '读取失败'],
  ])('列表错误码 %s → 「%s」', async (code, text) => {
    const w = makeWi()
    w.list['proj:a|开发中'] = () => apiErr(400, code)
    const b = await open(w)
    expect(b.wrapper.get('[data-testid=wi-error]').text()).toContain(text)
    expect(b.wrapper.get('[data-testid=wi-error]').text()).not.toContain('LEAK-BACKEND-MESSAGE')
  })

  it('网络断开（fetch 抛错）：显示「无法连接后端」，不回显异常文本', async () => {
    const w = makeWi()
    const inner = w.fetch
    w.fetch = (async (req: Request) => {
      if (new URL(req.url).pathname === '/api/work-items')
        throw new TypeError('connect ECONNREFUSED 127.0.0.1:5555')
      return inner(req)
    }) as typeof fetch
    const b = await open(w)
    const t = b.wrapper.get('[data-testid=wi-error]').text()
    expect(t).toContain('无法连接后端')
    expect(t).not.toContain('ECONNREFUSED')
  })

  it('列表响应形状不符（items 非数组）：当作读取失败，页面不崩溃', async () => {
    const w = makeWi()
    w.list['proj:a|开发中'] = () => j({ items: 'oops', truncated: false, omitted: 0 })
    const b = await open(w)
    expect(b.wrapper.get('[data-testid=wi-error]').text()).toContain('读取失败')
    expect(b.wrapper.find('[data-testid=project-select]').exists()).toBe(true)
  })

  it('项目列表形状不符（projects 非数组）：显示读取失败，列表不发请求', async () => {
    const w = makeWi()
    w.adoResp = () => j({ ...ADO, projects: null })
    const b = await open(w)
    expect(b.wrapper.get('[data-testid=wi-error]').text()).toContain('读取失败')
    expect(w.count('/api/work-items')).toBe(0)
  })

  it('项目列表 not_found 错误：显示固定文案而非崩溃', async () => {
    const w = makeWi()
    w.adoResp = () => apiErr(404, 'not_found')
    const b = await open(w)
    expect(b.wrapper.get('[data-testid=wi-error]').text()).toContain('工单或项目不存在')
  })

  it('空数组：没有匹配的工单；分页导航不出现', async () => {
    const w = makeWi()
    w.list['proj:a|开发中'] = () => j({ items: [], truncated: false, omitted: 0 })
    const b = await open(w)
    expect(b.wrapper.find('.empty').text()).toBe('没有匹配的工单')
    expect(b.wrapper.find('[data-testid=page-info]').exists()).toBe(false)
  })

  it('truncated 时提示「只显示前 500 条」；omitted 时提示跳过条数', async () => {
    const w = makeWi()
    w.list['proj:a|开发中'] = () => j({ items: [sum(1)], truncated: true, omitted: 3 })
    const b = await open(w)
    expect(b.wrapper.get('[data-testid=truncated]').text()).toBe('只显示前 500 条')
    expect(b.wrapper.get('[data-testid=omitted]').text()).toContain('有 3 条无法读取，已跳过')
  })

  it('分页 10/50/100 与翻页、筛选重置页码', async () => {
    const w = makeWi()
    const many = Array.from({ length: 120 }, (_, i) => sum(1000 + i))
    w.list['proj:a|开发中'] = () => j({ items: many, truncated: false, omitted: 0 })
    const b = await open(w)
    expect(b.wrapper.get('[data-testid=page-info]').text()).toBe('1 / 3 · 共 120 条')
    expect(b.wrapper.findAll('[data-testid^=wi-row-]').length).toBe(50)
    await b.wrapper.get('[data-testid=next-page]').trigger('click')
    await settle()
    expect(b.wrapper.get('[data-testid=page-info]').text()).toBe('2 / 3 · 共 120 条')
    await b.wrapper.get('[data-testid=page-size]').setValue('10')
    await settle()
    expect(b.wrapper.get('[data-testid=page-info]').text()).toBe('1 / 12 · 共 120 条')
    expect(b.wrapper.findAll('[data-testid^=wi-row-]').length).toBe(10)
    await b.wrapper.get('[data-testid=next-page]').trigger('click')
    await b.wrapper.get('[data-testid=next-page]').trigger('click')
    await settle()
    expect(b.wrapper.get('[data-testid=page-info]').text()).toBe('3 / 12 · 共 120 条')
    const input = b.wrapper.get('input[type=search]')
    await input.setValue('1005')
    await settle()
    expect(b.wrapper.get('[data-testid=page-info]').text()).toBe('1 / 1 · 共 1 条')
    expect(b.wrapper.find('[data-testid=wi-row-1005]').exists()).toBe(true)
  })

  it('指派人「未指派」筛选只显示 assigned_to 为空的工单', async () => {
    const w = makeWi()
    w.list['proj:a|开发中'] = () =>
      j({
        items: [sum(1, { assigned_to: null }), sum(2, { assigned_to: '甲' })],
        truncated: false,
        omitted: 0,
      })
    const b = await open(w)
    await b.wrapper.get('[data-testid=assignee-select]').setValue('__none__')
    await settle()
    expect(
      b.wrapper.findAll('[data-testid^=wi-row-]').map((r) => r.attributes('data-testid')),
    ).toEqual(['wi-row-1'])
  })
})

describe('详情错误态与降级文案', () => {
  it('详情 not_found 显示固定文案并可重试；列表仍可用', async () => {
    const w = makeWi()
    w.detail[1] = () => apiErr(404, 'not_found')
    const b = await open(w)
    await clickRow(b, 1)
    expect(detailEl(b).get('[data-testid=wi-error]').text()).toContain('工单或项目不存在')
    expect(detailEl(b).find('button').text()).toContain('重试')
    expect(row(b, 2).element).toBeTruthy()
  })

  it('详情响应缺 html 字段：视为形状不符，显示读取失败', async () => {
    const w = makeWi()
    w.detail[1] = () => j({ ...det(1), html: undefined })
    const b = await open(w)
    await clickRow(b, 1)
    expect(detailEl(b).get('[data-testid=wi-error]').text()).toContain('读取失败')
  })

  it('描述 omitted=too_large：显示「内容过大，未显示」', async () => {
    const w = makeWi()
    w.detail[1] = () => j(det(1, { html: { description: { html: null, omitted: 'too_large' } } }))
    const b = await open(w)
    await clickRow(b, 1)
    expect(b.wrapper.get('[data-testid=wi-body]').text()).toContain('内容过大，未显示')
  })

  it('没有任何描述：显示「暂无描述」', async () => {
    const w = makeWi()
    w.detail[1] = () => j(det(1, { html: { description: null } }))
    const b = await open(w)
    await clickRow(b, 1)
    expect(b.wrapper.get('[data-testid=wi-body]').text()).toContain('暂无描述')
  })

  it('AI 分析面板整体禁用并标注 S5', async () => {
    const b = await open(makeWi())
    const ai = b.wrapper.get('[data-testid=wi-ai]')
    expect(ai.attributes('aria-disabled')).toBe('true')
    expect(ai.text()).toContain('S5')
    expect(ai.findAll('button').every((x) => x.attributes('disabled') !== undefined)).toBe(true)
    expect(ai.find('fieldset').attributes('disabled')).toBeDefined()
  })
})

describe('评论 / 历史 / 子项 错误与降级', () => {
  it('评论 not_found：显示「该服务器不支持评论接口，可查看「历史」」，按钮切到历史页签', async () => {
    const w = makeWi()
    w.detail[1] = () => j(det(1))
    w.comments[1] = () => apiErr(404, 'not_found')
    w.updates[1] = () =>
      j({
        updates: [
          {
            id: 1,
            rev: 2,
            revised_by: '甲',
            revised_date: null,
            fields: [{ name: '状态', old: '新建', new: '开发中' }],
            relations_added: 0,
            relations_removed: 0,
          },
        ],
        truncated: false,
      })
    const b = await open(w)
    await clickRow(b, 1)
    await mousedownTab(b, '工单内容', '评论')
    expect(b.wrapper.get('[data-testid=comments-unsupported]').text()).toContain(
      '该服务器不支持评论接口，可查看「历史」',
    )
    await b.wrapper.get('[data-testid=comments-unsupported] button').trigger('click')
    await settle()
    const selected = b.wrapper
      .get('[role=tablist][aria-label="工单内容"]')
      .findAll('[role=tab]')
      .find((t) => t.attributes('aria-selected') === 'true')
    expect(selected?.text()).toContain('历史')
    expect(b.wrapper.get('[data-testid=wi-body]').text()).toContain('状态')
  })

  it('评论的其他错误（busy）不显示「不支持评论接口」', async () => {
    const w = makeWi()
    w.detail[1] = () => j(det(1))
    w.comments[1] = () => apiErr(503, 'busy')
    const b = await open(w)
    await clickRow(b, 1)
    await mousedownTab(b, '工单内容', '评论')
    expect(b.wrapper.find('[data-testid=comments-unsupported]').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=wi-error]').text()).toContain('服务繁忙，请稍后重试')
  })

  it('评论 html 经清洗：script 不出现；omitted 显示「内容过大」', async () => {
    const w = makeWi()
    w.detail[1] = () => j(det(1))
    w.comments[1] = () =>
      j({
        comments: [
          {
            id: 1,
            author: '甲',
            created_date: null,
            html: '<p>好</p><script>window.__x=1</script>',
          },
          { id: 2, author: '乙', created_date: null, html: null, omitted: 'too_large' },
        ],
        truncated: true,
      })
    const b = await open(w)
    await clickRow(b, 1)
    await mousedownTab(b, '工单内容', '评论')
    const body = b.wrapper.get('[data-testid=wi-body]')
    expect(body.find('script').exists()).toBe(false)
    expect(body.text()).toContain('好')
    expect(body.text()).toContain('内容过大，未显示')
    expect(body.text()).toContain('只显示前 100 条评论')
    expect((window as unknown as { __x?: number }).__x).toBeUndefined()
  })

  it('历史字段值以纯文本显示：带标签的值不产生 img 元素', async () => {
    const w = makeWi()
    w.detail[1] = () => j(det(1))
    w.updates[1] = () =>
      j({
        updates: [
          {
            id: 1,
            rev: 2,
            revised_by: '甲',
            revised_date: null,
            fields: [{ name: '描述', old: '', new: '<img src=x onerror="alert(1)">' }],
            relations_added: 1,
            relations_removed: 0,
          },
        ],
        truncated: false,
      })
    const b = await open(w)
    await clickRow(b, 1)
    await mousedownTab(b, '工单内容', '历史')
    const body = b.wrapper.get('[data-testid=wi-body]')
    expect(body.find('img').exists()).toBe(false)
    expect(body.text()).toContain('<img src=x onerror="alert(1)">')
    expect(body.text()).toContain('（空）')
    expect(body.text()).toContain('关联 +1 / −0')
  })

  it('子项点击会选中该子项并请求其详情；父项按钮同理', async () => {
    const w = makeWi()
    w.detail[1] = () => j(det(1, { parent_id: 9, child_ids: [2] }))
    w.detail[2] = () => j(det(2, { title: '子项二号' }))
    w.detail[9] = () => j(det(9, { title: '父项九号' }))
    w.children[1] = () => j({ items: [{ ...sum(2), parent_id: 1, depth: 1 }], truncated: false })
    const b = await open(w)
    await clickRow(b, 1)
    await b.wrapper.get('[data-testid=open-parent]').trigger('click')
    await settle()
    expect(detailEl(b).get('h2').text()).toBe('父项九号')
    expect(w.count('/api/work-items/9')).toBe(1)
    await clickRow(b, 1)
    await mousedownTab(b, '工单内容', '子项')
    await b.wrapper.get('[data-testid=child-2]').trigger('click')
    await settle()
    expect(detailEl(b).get('h2').text()).toBe('子项二号')
  })

  it('附件：被拦截的外部附件显示 origin；非图片附件只提供下载按钮', async () => {
    const w = makeWi()
    w.detail[1] = () =>
      j(
        det(1, {
          attachments: [
            {
              name: 'a.png',
              size: 10,
              is_image: true,
              media_id: null,
              blocked_origin: 'https://cdn.evil.test',
            },
            { name: 'b.pdf', size: 2048, is_image: false, media_id: 'pdf1', blocked_origin: null },
          ],
        }),
      )
    const b = await open(w)
    await clickRow(b, 1)
    await mousedownTab(b, '工单内容', '附件')
    expect(b.wrapper.get('[data-testid=attachment-blocked]').text()).toContain(
      'https://cdn.evil.test',
    )
    expect(b.wrapper.findAll('[data-testid=wi-attachment]')[1]!.text()).toContain('下载 b.pdf')
    expect(w.mediaCount('pdf1')).toBe(0)
  })
})

async function openDetailWithImages(w: Wi, id = 1) {
  w.detail[id] = () =>
    j(
      det(id, {
        html: {
          description: {
            html: '<p><img data-media-id="m1" alt="甲"> <img data-media-id="m2"></p>',
          },
        },
      }),
    )
  const b = await open(w)
  await clickRow(b, id)
  return b
}

describe('媒体：去重、并发、token、路径编码', () => {
  it('同一详情内相同 media id 只请求一次（描述内重复、切换到评论页再引用也复用）', async () => {
    const w = makeWi()
    w.detail[1] = () =>
      j(
        det(1, {
          html: {
            description: { html: '<p><img data-media-id="m1"><img data-media-id="m1"></p>' },
          },
        }),
      )
    w.comments[1] = () =>
      j({
        comments: [{ id: 1, author: '甲', created_date: null, html: '<img data-media-id="m1">' }],
        truncated: false,
      })
    w.media['m1'] = () => png()
    const b = await open(w)
    await clickRow(b, 1)
    expect(w.mediaCount('m1')).toBe(1)
    await mousedownTab(b, '工单内容', '评论')
    expect(w.mediaCount('m1')).toBe(1)
    expect(b.wrapper.findAll('[data-testid=wi-body] img').length).toBe(1)
  })

  it('图片加载成功：img.src 为 blob: URL；取字节时带 Bearer 头', async () => {
    const w = makeWi()
    w.media['m1'] = () => png()
    w.media['m2'] = () => png()
    const b = await openDetailWithImages(w)
    const imgs = b.wrapper.findAll('[data-testid=wi-body] img')
    expect(imgs[0]!.attributes('src')).toMatch(/^blob:fake\//)
    expect(imgs[0]!.attributes('src')).toBe(created[0]!.url)
    const mediaCalls = w.calls.filter((c) => c.path.startsWith('/api/work-items/media/'))
    expect(mediaCalls.length).toBe(2)
    expect(mediaCalls.every((c) => c.auth === 'Bearer fake-token')).toBe(true)
  })

  it('token 不出现在任何请求 URL、DOM、localStorage 或 sessionStorage 中', async () => {
    const w = makeWi()
    w.media['m1'] = () => png()
    w.media['m2'] = () => png()
    const b = await openDetailWithImages(w)
    await mousedownTab(b, '工单内容', '附件')
    expect(w.calls.some((c) => c.url.includes('fake-token'))).toBe(false)
    expect(created.some((c) => c.url.includes('fake-token'))).toBe(false)
    expect(document.documentElement.outerHTML).not.toContain('fake-token')
    for (let i = 0; i < localStorage.length; i++) {
      expect(localStorage.getItem(localStorage.key(i)!)).not.toContain('fake-token')
    }
    for (let i = 0; i < sessionStorage.length; i++) {
      expect(sessionStorage.getItem(sessionStorage.key(i)!)).not.toContain('fake-token')
    }
  })

  it('media id 含 / ? # 等字符：路径按段编码，不会穿越到其他接口', async () => {
    const w = makeWi()
    const evil = '../../settings?x=1#f'
    w.detail[1] = () =>
      j(det(1, { html: { description: { html: `<p><img data-media-id="${evil}"></p>` } } }))
    w.media[evil] = () => apiErr(404, 'media_expired')
    const b = await open(w)
    await clickRow(b, 1)
    expect(w.count('/api/settings')).toBe(0)
    expect(w.count('/api/ado')).toBe(1)
    const mc = w.calls.find((c) => c.path.startsWith('/api/work-items/media/'))!
    expect(mc.path).toBe(`/api/work-items/media/${encodeURIComponent(evil)}`)
    expect(mc.url).not.toMatch(/\/api\/settings/)
    expect(b.wrapper.get('[data-testid=wi-body] .media-ph').text()).toBe('图片已过期')
  })

  it('同时在途的媒体请求最多 4 个；完成一个后补位', async () => {
    const w = makeWi()
    const pend = Array.from({ length: 6 }, () => deferred<Response>())
    w.detail[1] = () =>
      j(
        det(1, {
          html: {
            description: {
              html: Array.from({ length: 6 }, (_, i) => `<img data-media-id="p${i}">`).join(''),
            },
          },
        }),
      )
    for (let i = 0; i < 6; i++) w.media[`p${i}`] = () => pend[i]!.p
    const b = await open(w)
    await clickRow(b, 1)
    const inflight = () => w.calls.filter((c) => c.path.startsWith('/api/work-items/media/')).length
    expect(inflight()).toBe(4)
    pend[0]!.resolve(png())
    await settle()
    expect(inflight()).toBe(5)
    for (let i = 1; i < 6; i++) pend[i]!.resolve(png())
    await settle()
    expect(
      b.wrapper
        .findAll('[data-testid=wi-body] img')
        .every((x) => x.attributes('src')?.startsWith('blob:')),
    ).toBe(true)
  })

  it('切换工单：正在加载的媒体被中止，迟到的字节不会创建 blob；已加载的 blob 被 revoke', async () => {
    const w = makeWi()
    const slow = deferred<Response>()
    w.media['m1'] = () => png()
    w.media['m2'] = () => slow.p
    const b = await openDetailWithImages(w, 1)
    expect(created.length).toBe(1)
    const firstBlob = created[0]!.url
    const slowCall = w.calls.find((c) => c.path.endsWith('/m2'))!
    w.detail[2] = () => j(det(2))
    await clickRow(b, 2)
    expect(slowCall.signal.aborted).toBe(true)
    expect(revoked).toContain(firstBlob)
    slow.resolve(png())
    await settle()
    expect(created.length).toBe(1)
  })

  it('切换项目同样清理媒体 blob', async () => {
    const w = makeWi()
    w.media['m1'] = () => png()
    w.media['m2'] = () => png()
    const b = await openDetailWithImages(w)
    expect(created.length).toBe(2)
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:b')
    await settle()
    expect(revoked.sort()).toEqual(created.map((c) => c.url).sort())
    expect(b.wrapper.find('section[aria-label="工单详情"] h2').exists()).toBe(false)
  })

  it('媒体失败后不自动重试；「刷新详情」后重新请求并恢复图片', async () => {
    const w = makeWi()
    let attempt = 0
    w.detail[1] = () =>
      j(det(1, { html: { description: { html: '<p><img data-media-id="e1"></p>' } } }))
    w.media['e1'] = () => (++attempt === 1 ? apiErr(404, 'media_expired') : png())
    const b = await open(w)
    await clickRow(b, 1)
    expect(b.wrapper.get('[data-testid=media-expired]').text()).toContain('部分图片已过期')
    expect(b.wrapper.get('[data-testid=wi-body] .media-ph').text()).toBe('图片已过期')
    await settle(10)
    expect(w.mediaCount('e1')).toBe(1)
    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle(10)
    expect(w.mediaCount('e1')).toBe(2)
    expect(b.wrapper.get('[data-testid=wi-body] img').attributes('src')).toMatch(/^blob:fake\//)
    expect(b.wrapper.find('[data-testid=media-expired]').exists()).toBe(false)
  })

  it('附件里的过期图片在「刷新详情」后也应重新加载（同一缓存的恢复路径）', async () => {
    const w = makeWi()
    let attempt = 0
    w.detail[1] = () =>
      j(
        det(1, {
          attachments: [
            { name: 'p.png', size: 4, is_image: true, media_id: 'ap1', blocked_origin: null },
          ],
        }),
      )
    w.media['ap1'] = () => (++attempt === 1 ? apiErr(404, 'media_expired') : png())
    const b = await open(w)
    await clickRow(b, 1)
    await mousedownTab(b, '工单内容', '附件')
    expect(b.wrapper.get('[data-testid=wi-attachment]').text()).toContain('图片已过期')
    const detailBefore = w.count('/api/work-items/1')
    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle(10)
    expect(w.count('/api/work-items/1')).toBe(detailBefore + 1)
    expect(w.mediaCount('ap1')).toBe(2)
    expect(b.wrapper.find('[data-testid=wi-attachment] img').exists()).toBe(true)
  })

  it.each([
    ['unsupported_media', null, '非图片，可下载'],
    ['ado_request_failed', 'blocked_origin', '图片被拦截'],
    ['ado_request_failed', 'tls', '图片加载失败'],
    ['busy', null, '服务繁忙，图片未加载'],
    ['no_credential', null, '该代码库未配置 PAT'],
  ])('描述图片失败 code=%s category=%s → 占位「%s」', async (code, cat, text) => {
    const w = makeWi()
    w.detail[1] = () =>
      j(det(1, { html: { description: { html: '<p><img data-media-id="x1"></p>' } } }))
    w.media['x1'] = () => apiErr(code === 'busy' ? 503 : 404, code, cat ?? undefined)
    const b = await open(w)
    await clickRow(b, 1)
    await settle()
    expect(b.wrapper.get('[data-testid=wi-body] .media-ph').text()).toBe(text)
    expect(b.wrapper.find('[data-testid=wi-body] img[src]').exists()).toBe(false)
  })

  it('描述里的外部 src 不发请求，也不产生任何对外请求', async () => {
    const w = makeWi()
    w.detail[1] = () =>
      j(
        det(1, {
          html: { description: { html: '<p><img src="https://evil.example/t.png"></p>' } },
        }),
      )
    const b = await open(w)
    await clickRow(b, 1)
    expect(w.calls.some((c) => c.url.includes('evil.example'))).toBe(false)
    expect(b.wrapper.get('[data-testid=wi-body] .media-ph').text()).toBe('图片未显示')
  })

  it('非图片附件：点击下载，字节经 blob 触发保存；失败显示文案', async () => {
    const clicks: { download: string; href: string }[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push({ download: this.download, href: this.href })
    })
    const w = makeWi()
    w.detail[1] = () =>
      j(
        det(1, {
          attachments: [
            { name: 'ok.bin', size: 1, is_image: false, media_id: 'd1', blocked_origin: null },
            { name: 'bad.bin', size: 1, is_image: false, media_id: 'd2', blocked_origin: null },
          ],
        }),
      )
    w.media['d1'] = () => png()
    w.media['d2'] = () => apiErr(404, 'unsupported_media')
    const b = await open(w)
    await clickRow(b, 1)
    await mousedownTab(b, '工单内容', '附件')
    const items = b.wrapper.findAll('[data-testid=wi-attachment]')
    await items[0]!.get('button').trigger('click')
    await settle()
    expect(clicks).toEqual([{ download: 'ok.bin', href: 'blob:fake/1' }])
    await items[1]!.get('button').trigger('click')
    await settle()
    expect(items[1]!.get('[role=alert]').text()).toBe('非图片，可下载')
  })
})

describe('缓存：staleTime、焦点、刷新、settings.changed、切项目', () => {
  it('窗口聚焦不重取列表与项目列表', async () => {
    const w = makeWi()
    const b = await open(w)
    const lists = w.count('/api/work-items')
    const ados = w.count('/api/ado')
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    expect(w.count('/api/work-items')).toBe(lists)
    expect(w.count('/api/ado')).toBe(ados)
    await b.wrapper.get('[data-testid=project-select]').trigger('change')
    await settle()
    expect(w.count('/api/work-items')).toBe(lists)
  })

  it('离开页面再回来：30 秒内不重新请求列表', async () => {
    const w = makeWi()
    const b = await open(w)
    const lists = w.count('/api/work-items')
    await b.router.push('/settings')
    await settle()
    await b.router.push('/work-items')
    await settle()
    expect(w.count('/api/work-items')).toBe(lists)
    expect(b.wrapper.findAll('[data-testid^=wi-row-]').length).toBe(2)
  })

  it('刷新按钮强制重取项目列表与工单列表', async () => {
    const w = makeWi()
    const b = await open(w)
    const lists = w.count('/api/work-items')
    const ados = w.count('/api/ado')
    await b.wrapper.get('[data-testid=refresh]').trigger('click')
    await settle()
    expect(w.count('/api/work-items')).toBe(lists + 1)
    expect(w.count('/api/ado')).toBe(ados + 1)
  })

  it('settings.changed 事件使项目列表与工单查询失效并重取', async () => {
    const w = makeWi()
    const b = await open(w)
    const lists = w.count('/api/work-items')
    const ados = w.count('/api/ado')
    b.sock.emit(env('settings.changed', { revision: 9 }))
    await settle()
    expect(w.count('/api/ado')).toBe(ados + 1)
    expect(w.count('/api/work-items')).toBe(lists + 1)
  })

  it('切换项目：列表只显示新项目的工单，请求带新 project_id，筛选与选中被清空', async () => {
    const w = makeWi()
    w.list['proj:b|开发中'] = () =>
      j({ items: [sum(77, { title: '乙项目工单' })], truncated: false, omitted: 0 })
    const b = await open(w)
    await b.wrapper.get('input[type=search]').setValue('标题')
    await clickRow(b, 1)
    expect(detailEl(b).exists()).toBe(true)
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:b')
    await settle()
    expect(w.calls.at(-1)!.query.project_id).toBe('proj:b')
    expect(
      b.wrapper.findAll('[data-testid^=wi-row-]').map((r) => r.attributes('data-testid')),
    ).toEqual(['wi-row-77'])
    expect((b.wrapper.get('input[type=search]').element as HTMLInputElement).value).toBe('')
    expect(b.wrapper.find('section[aria-label="工单详情"] h2').exists()).toBe(false)
  })
})

describe('选择持久化：localStorage 只存 {project_id, column}，读写失败不影响页面', () => {
  it('写入的内容只有 project_id 与 column', async () => {
    const b = await open(makeWi())
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:b')
    await settle()
    const raw = localStorage.getItem('toolbox.work-items.selection')!
    expect(JSON.parse(raw)).toEqual({ project_id: 'proj:b', column: '开发中' })
    expect(raw).not.toContain('fake-token')
  })

  it('已保存的项目与列被恢复', async () => {
    localStorage.setItem(
      'toolbox.work-items.selection',
      JSON.stringify({ project_id: 'proj:b', column: '测试' }),
    )
    const w = makeWi()
    const b = await open(w)
    expect(w.calls.find((c) => c.path === '/api/work-items')!.query).toEqual({
      project_id: 'proj:b',
      column: '测试',
    })
    const sel = b.wrapper
      .get('[role=tablist][aria-label="看板列"]')
      .findAll('[role=tab]')
      .find((t) => t.attributes('aria-selected') === 'true')
    expect(sel?.text()).toContain('测试')
  })

  it('已保存的项目已不存在：回退到后端 active 项目', async () => {
    localStorage.setItem(
      'toolbox.work-items.selection',
      JSON.stringify({ project_id: 'proj:gone', column: '测试' }),
    )
    const w = makeWi()
    await open(w)
    expect(w.calls.find((c) => c.path === '/api/work-items')!.query.project_id).toBe('proj:a')
  })

  it('已保存的列不在五列中：使用默认列「开发中」', async () => {
    localStorage.setItem(
      'toolbox.work-items.selection',
      JSON.stringify({ project_id: 'proj:a', column: '不存在' }),
    )
    const w = makeWi()
    await open(w)
    expect(w.calls.find((c) => c.path === '/api/work-items')!.query.column).toBe('开发中')
  })

  it('损坏的 JSON：页面正常加载，使用默认值', async () => {
    localStorage.setItem('toolbox.work-items.selection', '{not json')
    const w = makeWi()
    const b = await open(w)
    expect(b.wrapper.findAll('[data-testid^=wi-row-]').length).toBe(2)
    expect(w.calls.find((c) => c.path === '/api/work-items')!.query).toEqual({
      project_id: 'proj:a',
      column: '开发中',
    })
  })

  it('localStorage 读写都抛错：页面照常渲染与切换', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    const w = makeWi()
    const b = await open(w)
    expect(b.wrapper.findAll('[data-testid^=wi-row-]').length).toBe(2)
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:b')
    await settle()
    expect(w.calls.at(-1)!.query.project_id).toBe('proj:b')
  })
})

describe('键盘可达与无障碍名称', () => {
  it('列表行是原生 button（可聚焦、可由 Enter 触发），点击后选中并标记 aria-current', async () => {
    const b = await open(makeWi())
    const r = row(b, 1)
    expect(r.element.tagName).toBe('BUTTON')
    expect(r.attributes('type')).toBe('button')
    expect(r.attributes('tabindex')).toBeUndefined()
    await clickRow(b, 1)
    expect(row(b, 1).attributes('aria-current')).toBe('true')
    expect(row(b, 2).attributes('aria-current')).toBeUndefined()
  })

  it('看板列页签支持方向键切换，并触发对应列的请求', async () => {
    const w = makeWi()
    const b = await open(w)
    const active = b.wrapper
      .get('[role=tablist][aria-label="看板列"]')
      .findAll('[role=tab]')
      .find((t) => t.attributes('aria-selected') === 'true')!
    expect(active.text()).toContain('开发中')
    await active.trigger('keydown', { key: 'ArrowRight' })
    await settle()
    expect(w.calls.at(-1)!.query.column).toBe('测试')
    const nowActive = b.wrapper
      .get('[role=tablist][aria-label="看板列"]')
      .findAll('[role=tab]')
      .find((t) => t.attributes('aria-selected') === 'true')!
    expect(nowActive.text()).toContain('测试')
  })

  it('页面中每个按钮都有可访问名称（文字或 aria-label）', async () => {
    const w = makeWi()
    w.detail[1] = () =>
      j(
        det(1, {
          attachments: [
            { name: 'f.bin', size: 1, is_image: false, media_id: 'k', blocked_origin: null },
          ],
        }),
      )
    const b = await open(w)
    await clickRow(b, 1)
    const names = b.wrapper.findAll('button').map((x) => ({
      text: x.text().trim(),
      label: x.attributes('aria-label') ?? '',
    }))
    expect(names.length).toBeGreaterThan(5)
    for (const n of names) expect(n.text || n.label, JSON.stringify(n)).toBeTruthy()
    expect(b.wrapper.get('[data-testid=refresh]').attributes('aria-label')).toBe('刷新')
  })

  it('下拉框与搜索框都有可访问标签', async () => {
    const b = await open(makeWi())
    for (const sel of [
      '[data-testid=project-select]',
      '[data-testid=assignee-select]',
      '[data-testid=page-size]',
    ]) {
      expect(b.wrapper.get(sel).element.closest('label'), sel).not.toBeNull()
    }
    expect(b.wrapper.get('input[type=search]').element.closest('label')?.textContent).toContain(
      '搜索工单',
    )
  })

  it('工单内容页签支持方向键切换', async () => {
    const w = makeWi()
    w.detail[1] = () => j(det(1))
    const b = await open(w)
    await clickRow(b, 1)
    const tabs = b.wrapper.get('[role=tablist][aria-label="工单内容"]').findAll('[role=tab]')
    await tabs[0]!.trigger('keydown', { key: 'ArrowRight' })
    await settle()
    const sel = b.wrapper
      .get('[role=tablist][aria-label="工单内容"]')
      .findAll('[role=tab]')
      .find((t) => t.attributes('aria-selected') === 'true')
    expect(sel?.text()).toContain('评论')
  })
})
