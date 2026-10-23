// S1-B：设置页（假 fetch，按 openapi 形状；不连任何真实服务）。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useBackendStore } from '@/stores/backend'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import {
  FAKE_PAT,
  createFake,
  err,
  json,
  makeAdo,
  makePreview,
  makeSettings,
  type Fake,
} from './settings-fake'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

async function open(fake: Fake, tab?: string) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  if (tab) await selectTab(b, tab)
  return b
}
type B = Awaited<ReturnType<typeof open>>

async function selectTab(b: B, label: string) {
  const t = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith(label))
  expect(t, `tab ${label}`).toBeTruthy()
  await t!.trigger('mousedown')
  await flushPromises()
}
const byTid = (b: B, id: string) => b.wrapper.find(`[data-testid="${id}"]`)
async function click(b: B, id: string) {
  await b.wrapper.get(`[data-testid="${id}"]`).trigger('click')
  await flushPromises()
}
async function typeInto(b: B, label: string, value: string) {
  const input = b.wrapper
    .findAll('label.text-input')
    .find((l) => l.get('.sr-only').text() === label)!
    .get('input')
  await input.setValue(value)
}
const pwd = (b: B) => b.wrapper.get('input[type=password]')

describe('S1-B 导航与页签', () => {
  it('导航 08 设置启用，路由 /settings；页签 导入·ADO 连接·本地仓库·凭据·常规', async () => {
    const b = await open(createFake())
    const link = b.wrapper.get('nav a[href="/settings"]')
    expect(link.text()).toContain('设置')
    expect(link.attributes('aria-current')).toBe('page')
    const tabs = b.wrapper.findAll('[role=tab]').map((t) => t.text().replace(/\d+$/, '').trim())
    expect(tabs).toEqual(['导入', 'ADO 连接', '本地仓库', '凭据', '常规'])
    await b.done()
  })

  it('页签与面板可访问关联：aria-controls 指向含真实内容的可见 tabpanel', async () => {
    const b = await open(createFake())
    for (const label of ['导入', 'ADO 连接', '凭据', '常规']) {
      await selectTab(b, label)
      const cur = b.wrapper.get('[role=tab][aria-selected=true]')
      const panel = document.getElementById(cur.attributes('aria-controls')!)!
      expect(panel.getAttribute('role')).toBe('tabpanel')
      expect(panel.hasAttribute('hidden')).toBe(false)
      expect(panel.getAttribute('aria-labelledby')).toBe(cur.attributes('id'))
      expect(panel.textContent!.length).toBeGreaterThan(20)
    }
    await b.done()
  })

  it('页签方向键可达', async () => {
    const b = await open(createFake())
    const tabs = b.wrapper.findAll('[role=tab]')
    ;(tabs[0]!.element as HTMLElement).focus()
    await tabs[0]!.trigger('keydown', { key: 'ArrowDown' }) // R1：设置分区为竖向列表
    await flushPromises()
    expect(b.wrapper.get('[role=tab][aria-selected=true]').text()).toContain('ADO 连接')
    await b.done()
  })

  it('已完成导入时首次载入落在 ADO 连接', async () => {
    const fake = createFake()
    fake.state.settings = makeSettings({ import: { state: 'completed', summary: {} } })
    const b = await open(fake)
    expect(b.wrapper.get('[role=tab][aria-selected=true]').text()).toContain('ADO 连接')
    await b.done()
  })
})

describe('导入', () => {
  it('none：预览（POST，无请求体）→ 分块展示 → 二次确认 → 执行携带 fingerprint', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.path === '/api/settings/import/execute' ? json({ revision: 7 }) : undefined,
    )
    const b = await open(fake)
    expect(byTid(b, 'import-confirm').exists()).toBe(false)
    await click(b, 'import-preview')
    expect(fake.to('POST', '/api/settings/import/preview')).toHaveLength(1)
    const text = b.wrapper.get('[data-testid=import-tab]').text()
    for (const s of [
      'ui_settings.yaml',
      '缺失',
      '示例库',
      '已找到',
      'HTTP 明文',
      '项目甲',
      'telegram',
    ])
      expect(text).toContain(s)
    expect(byTid(b, 'import-tasks-rule').text()).toContain('旧 flows 生成任务')
    expect(byTid(b, 'import-task-count').text()).toBe('2')
    expect(byTid(b, 'import-warnings').text()).toContain('明文')
    expect(byTid(b, 'import-execute').exists()).toBe(false)
    await click(b, 'import-confirm')
    expect(byTid(b, 'import-confirm-box').text()).toMatch(/一次/)
    expect(byTid(b, 'import-confirm-box').text()).toContain('不会修改旧配置')
    await click(b, 'import-execute')
    const exec = fake.to('POST', '/api/settings/import/execute')
    expect(exec).toHaveLength(1)
    expect(exec[0]!.body).toEqual({ fingerprint: 'fp-1' })
    await b.done()
  })

  it('有阻断错误：列出错误，确认导入被禁用', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.path === '/api/settings/import/preview'
        ? json(makePreview({ errors: ['tasks.yaml: 无法安全解析或文件越界/超限'] }))
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'import-preview')
    expect(byTid(b, 'import-errors').text()).toContain('无法安全解析')
    expect(byTid(b, 'import-confirm').attributes('disabled')).toBeDefined()
    await b.done()
  })

  it('import_source_changed：提示重新预览，丢弃旧预览', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.path === '/api/settings/import/execute'
        ? err(409, 'import_source_changed', '源配置已变化，请重新预览')
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'import-preview')
    await click(b, 'import-confirm')
    await click(b, 'import-execute')
    expect(byTid(b, 'import-stale').text()).toContain('重新预览')
    expect(byTid(b, 'import-confirm').exists()).toBe(false)
    expect(byTid(b, 'import-libraries').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=import-preview]').text()).toContain('预览导入')
    await b.done()
  })

  it('import_not_allowed 等错误进提示条', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.path === '/api/settings/import/execute'
        ? err(409, 'import_not_allowed', '只允许首次运行导入')
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'import-preview')
    await click(b, 'import-confirm')
    await click(b, 'import-execute')
    expect(byTid(b, 'settings-notice').text()).toContain('只允许首次运行导入')
    await b.done()
  })

  it('跳过导入：POST decline', async () => {
    const fake = createFake()
    const b = await open(fake)
    await click(b, 'import-decline')
    expect(fake.to('POST', '/api/settings/import/decline')).toHaveLength(1)
    await b.done()
  })

  it('failed：显示错误，可重试预览，按钮为“放弃导入”', async () => {
    const fake = createFake()
    fake.state.settings = makeSettings({
      import: { state: 'failed', error: '导入失败；可重试或放弃' },
    })
    const b = await open(fake)
    expect(byTid(b, 'import-failed').text()).toContain('导入失败')
    expect(byTid(b, 'import-decline').text()).toContain('放弃导入')
    await click(b, 'import-preview')
    expect(byTid(b, 'import-confirm').exists()).toBe(true)
    await b.done()
  })

  for (const state of ['completed', 'declined'] as const) {
    it(`${state}：只读摘要，没有预览/执行入口`, async () => {
      const fake = createFake()
      fake.state.settings = makeSettings({
        import: {
          state,
          finished_at: '2026-10-22T10:00:00Z',
          summary: state === 'completed' ? (makePreview() as unknown as Record<string, never>) : {},
        },
      })
      const b = await open(fake, '导入')
      expect(byTid(b, 'import-readonly').exists()).toBe(true)
      expect(byTid(b, 'import-preview').exists()).toBe(false)
      expect(byTid(b, 'import-execute').exists()).toBe(false)
      expect(byTid(b, 'import-decline').exists()).toBe(false)
      if (state === 'completed') expect(b.wrapper.text()).toContain('示例库')
      await b.done()
    })
  }
})

describe('ADO 连接：增改删与校验', () => {
  it('列表显示 libraries/projects、当前标记与 HTTP 明文警告标签', async () => {
    const b = await open(createFake(), 'ADO 连接')
    const libs = b.wrapper.get('[data-testid=library-table]').text()
    expect(libs).toContain('示例库')
    expect(libs).toContain('无凭据库')
    expect(libs).toContain('HTTP 明文')
    expect(libs).toContain('未保存')
    expect(libs).toContain('当前')
    expect(b.wrapper.get('[data-testid=project-table]').text()).toContain('项目甲')
    await b.done()
  })

  it('新建 library：POST 带 revision，可带 pat，成功后选中新项且 PAT 输入清空', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method !== 'POST' || c.path !== '/api/ado/libraries') return undefined
      fake.state.ado.libraries.push({
        id: 'lib:new',
        name: '新库',
        base_url: 'https://new.example.test/tfs',
        credential: { present: true, source: 'manual', state: 'present' },
      })
      return json({ id: 'lib:new', revision: 6 })
    })
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-add')
    await typeInto(b, 'library 名称', '  新库  ')
    await typeInto(b, 'library 地址', 'https://new.example.test/tfs')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'library-create')
    const post = fake.to('POST', '/api/ado/libraries')
    expect(post).toHaveLength(1)
    expect(post[0]!.body).toEqual({
      revision: 5,
      name: '新库',
      base_url: 'https://new.example.test/tfs',
      pat: FAKE_PAT,
    })
    expect(byTid(b, 'library-detail').text()).toContain('新库')
    expect((pwd(b).element as HTMLInputElement).value).toBe('')
    await b.done()
  })

  it('客户端先挡明显非法输入（空名称、非 http 地址）：不发请求', async () => {
    const fake = createFake()
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-add')
    await click(b, 'library-create')
    expect(byTid(b, 'library-local-error').text()).toContain('名称')
    await typeInto(b, 'library 名称', 'x')
    await typeInto(b, 'library 地址', 'ftp://x.test')
    await click(b, 'library-create')
    expect(byTid(b, 'library-local-error').text()).toContain('http')
    expect(fake.to('POST', '/api/ado/libraries')).toHaveLength(0)
    await b.done()
  })

  it('422 validation_error：展示后端固定文案（不回显输入）', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'POST' && c.path === '/api/ado/libraries'
        ? err(422, 'validation_error', '配置校验失败')
        : undefined,
    )
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-add')
    await typeInto(b, 'library 名称', '重名')
    await typeInto(b, 'library 地址', 'https://a.example.test')
    await click(b, 'library-create')
    expect(byTid(b, 'settings-notice').text()).toContain('配置校验失败')
    await b.done()
  })

  it('修改 library 名称：PATCH 只含变更字段与 revision', async () => {
    const fake = createFake()
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '改名后')
    await click(b, 'library-save')
    const patch = fake.to('PATCH', '/api/ado/libraries/lib%3Aa')
    const call = patch[0] ?? fake.calls.find((c) => c.method === 'PATCH')!
    expect(call.body).toEqual({ revision: 5, name: '改名后', keep_pat: false })
    await b.done()
  })

  it('删除 library 需二次确认；删除请求带 revision 查询参数', async () => {
    const fake = createFake()
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:b')
    await click(b, 'library-delete')
    expect(fake.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await click(b, 'library-delete-confirm')
    const del = fake.calls.find((c) => c.method === 'DELETE')!
    expect(del.path).toBe('/api/ado/libraries/lib%3Ab')
    expect(del.query).toEqual({ revision: '5' })
    await b.done()
  })

  it('in_use 409：列出引用任务名', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'DELETE' && c.path.startsWith('/api/ado/libraries/')
        ? err(409, 'in_use', '条目被任务引用', { tasks: ['发布任务甲', '同步乙'] })
        : undefined,
    )
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await click(b, 'library-delete')
    await click(b, 'library-delete-confirm')
    const tasks = b.wrapper.findAll('[data-testid=notice-tasks] li').map((l) => l.text())
    expect(tasks).toEqual(['发布任务甲', '同步乙'])
    await b.done()
  })

  it('revision_conflict 409：刷新数据并提示，不静默重试', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH'
        ? err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
        : undefined,
    )
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '又改名')
    const before = fake.to('GET', '/api/ado').length
    await click(b, 'library-save')
    expect(fake.calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
    expect(fake.to('GET', '/api/ado').length).toBeGreaterThan(before)
    expect(byTid(b, 'settings-notice').text()).toContain('已合并最新内容')
    await b.done()
  })

  it('pat_origin_change 409：提示 PAT 将发往新地址；保留 -> keep_pat:true；替换 -> 带新 pat 且输入清空', async () => {
    const fake = createFake()
    let first = true
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      const body = c.body as { keep_pat?: boolean; pat?: string }
      if (first && !body.keep_pat && !body.pat) {
        first = false
        return err(409, 'pat_origin_change', 'origin 已变化')
      }
      return json({ revision: 6 })
    })
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    const box = byTid(b, 'pat-origin-change')
    expect(box.text()).toContain('PAT 将发往新地址')
    expect(box.text()).toContain('https://other.example.test')
    expect(byTid(b, 'settings-notice').exists()).toBe(false)
    await click(b, 'origin-keep')
    const keep = fake.calls.filter((c) => c.method === 'PATCH').at(-1)!
    expect(keep.body).toMatchObject({ base_url: 'https://other.example.test/tfs', keep_pat: true })
    expect(byTid(b, 'pat-origin-change').exists()).toBe(false)

    // 替换分支
    first = true
    await typeInto(b, 'library 地址', 'https://third.example.test')
    await click(b, 'library-save')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'origin-replace')
    const rep = fake.calls.filter((c) => c.method === 'PATCH').at(-1)!
    expect(rep.body).toMatchObject({ pat: FAKE_PAT, keep_pat: false })
    expect((pwd(b).element as HTMLInputElement).value).toBe('')
    await b.done()
  })

  it('project 新建：校验路径分隔符；获取远端项目并填入；POST 带 revision', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.path.endsWith('/remote-projects')) return json([{ name: '远端甲' }, { name: '远端乙' }])
      if (c.method === 'POST' && c.path === '/api/ado/projects')
        return json({ id: 'proj:n', revision: 6 })
      return undefined
    })
    const b = await open(fake, 'ADO 连接')
    await click(b, 'project-add')
    await typeInto(b, 'collection', 'a/b')
    await typeInto(b, 'project 名称', 'p')
    await click(b, 'project-save')
    expect(byTid(b, 'project-local-error').text()).toContain('不能含')
    expect(fake.to('POST', '/api/ado/projects')).toHaveLength(0)
    await typeInto(b, 'collection', 'Col')
    await click(b, 'remote-fetch')
    const remote = fake.calls.find((c) => c.path.endsWith('/remote-projects'))!
    expect(remote.query).toEqual({ collection: 'Col' })
    const items = b.wrapper.findAll('[data-testid=remote-list] button')
    expect(items.map((i) => i.text())).toEqual(['远端甲', '远端乙'])
    await items[1]!.trigger('click')
    await click(b, 'project-save')
    expect(fake.to('POST', '/api/ado/projects')[0]!.body).toEqual({
      revision: 5,
      library_id: 'lib:a',
      collection: 'Col',
      project: '远端乙',
    })
    await b.done()
  })

  it('project 设为当前：PUT /api/ado/active；删除二次确认', async () => {
    const fake = createFake()
    fake.state.ado = makeAdo({ active_project_id: null })
    const b = await open(fake, 'ADO 连接')
    await click(b, 'project-row-proj:a')
    await click(b, 'project-activate')
    expect(fake.to('PUT', '/api/ado/active')[0]!.body).toEqual({
      revision: 5,
      library_id: 'lib:a',
      project_id: 'proj:a',
    })
    await click(b, 'project-delete')
    expect(fake.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await click(b, 'project-delete-confirm')
    expect(fake.calls.find((c) => c.method === 'DELETE')!.path).toBe('/api/ado/projects/proj%3Aa')
    await b.done()
  })
})

describe('PAT：只写、不预填、不外泄', () => {
  it('保存 PAT：PUT 只含 revision+pat；成功后输入清空；PAT 不在 DOM/存储/URL/console/Pinia/query 缓存', async () => {
    const fake = createFake()
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => {}),
    )
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:b')
    const input = pwd(b)
    expect(input.attributes('type')).toBe('password')
    expect((input.element as HTMLInputElement).value).toBe('')
    await input.setValue(FAKE_PAT)
    await click(b, 'pat-save')
    const put = fake.calls.find((c) => c.method === 'PUT' && c.path.endsWith('/pat'))!
    expect(put.body).toEqual({ revision: 5, pat: FAKE_PAT })
    expect(put.query).toEqual({})
    expect((pwd(b).element as HTMLInputElement).value).toBe('')

    // 除请求体外，任何地方都找不到 PAT
    expect(document.documentElement.outerHTML).not.toContain(FAKE_PAT)
    expect(JSON.stringify({ ...localStorage })).not.toContain(FAKE_PAT)
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(FAKE_PAT)
    expect(location.href).not.toContain(FAKE_PAT)
    for (const s of spies) expect(JSON.stringify(s.mock.calls)).not.toContain(FAKE_PAT)
    const pinia = (
      b.wrapper.vm.$.appContext.config.globalProperties.$pinia as {
        state: { value: unknown }
      }
    ).state.value
    expect(JSON.stringify(pinia)).not.toContain(FAKE_PAT)
    const provides = b.wrapper.vm.$.appContext.provides as Record<symbol | string, unknown>
    const qc = Object.values(provides).find(
      (v): v is import('@tanstack/vue-query').QueryClient =>
        typeof v === 'object' && v !== null && 'getQueryCache' in v,
    )
    expect(qc, '找到 query client').toBeTruthy()
    expect(
      JSON.stringify(
        qc!
          .getQueryCache()
          .getAll()
          .map((q) => [q.queryKey, q.state.data]),
      ),
    ).not.toContain(FAKE_PAT)
    // PAT 不经 mutation（mutation 缓存会保留 variables）
    expect(qc!.getMutationCache().getAll()).toHaveLength(0)
    await b.done()
  })

  it('请求失败时同样清空 PAT 输入', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PUT' && c.path.endsWith('/pat')
        ? err(502, 'credential_backend_error', '凭据后端访问失败')
        : undefined,
    )
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:b')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'pat-save')
    expect((pwd(b).element as HTMLInputElement).value).toBe('')
    expect(byTid(b, 'settings-notice').text()).toContain('凭据后端访问失败')
    expect(document.documentElement.outerHTML).not.toContain(FAKE_PAT)
    await b.done()
  })

  it('删除 PAT：DELETE 带 revision', async () => {
    const fake = createFake()
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await click(b, 'pat-delete')
    const del = fake.calls.find((c) => c.method === 'DELETE')!
    expect(del.path).toBe('/api/ado/libraries/lib%3Aa/pat')
    expect(del.query).toEqual({ revision: '5' })
    await b.done()
  })
})

describe('测试连接', () => {
  const cats = [
    ['ok', true, '连接成功'],
    ['unauthorized', false, '认证失败'],
    ['forbidden', false, '权限不足'],
    ['not_found', false, '不存在'],
    ['redirect', false, '重定向'],
    ['tls', false, 'TLS'],
    ['timeout', false, '超时'],
    ['network', false, '网络不可达'],
    ['bad_response', false, '响应格式异常'],
    ['no_credential', false, '尚未保存 PAT'],
  ] as const
  for (const [category, ok, text] of cats) {
    it(`分类 ${category}`, async () => {
      const fake = createFake()
      fake.handlers.push((c) =>
        c.path.endsWith('/test')
          ? json({ ok, category, http_status: ok ? 200 : null, message: '消息' })
          : undefined,
      )
      const b = await open(fake, 'ADO 连接')
      await click(b, 'library-row-lib:a')
      await click(b, 'library-test')
      const call = fake.calls.find((c) => c.path.endsWith('/test'))!
      expect(call.body).toEqual({ collection: 'Col' })
      const box = byTid(b, 'test-result')
      expect(box.attributes('data-category')).toBe(category)
      expect(box.text()).toContain(text)
      await b.done()
    })
  }

  it('带输入框 PAT 测试：请求体带候选 PAT，随后清空', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.path.endsWith('/test')
        ? json({ ok: true, category: 'ok', http_status: 200, message: '' })
        : undefined,
    )
    const b = await open(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'library-test')
    expect(fake.calls.find((c) => c.path.endsWith('/test'))!.body).toEqual({
      collection: 'Col',
      pat: FAKE_PAT,
    })
    expect((pwd(b).element as HTMLInputElement).value).toBe('')
    expect(document.documentElement.outerHTML).not.toContain(FAKE_PAT)
    await b.done()
  })
})

describe('凭据页', () => {
  it('表格显示 kind/所属/存在/来源/状态；没有任何值字段；孤立项可清理', async () => {
    const fake = createFake()
    const b = await open(fake, '凭据')
    const t = b.wrapper.get('[data-testid=credentials-table]')
    const heads = t.findAll('th').map((h) => h.text())
    expect(heads).toEqual(['类型', '所属', '存在', '来源', '状态', '更新时间', '操作'])
    expect(t.text()).toContain('ADO PAT')
    expect(t.text()).toContain('示例库')
    expect(t.text()).toContain('孤立')
    expect(b.wrapper.find('[data-testid=credentials-tab] input').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=credentials-tab]').text()).not.toMatch(
      /fake-pat|secret|token/i,
    )
    expect(b.wrapper.findAll('[data-testid="cred-ado_pat:lib:a"] button')).toHaveLength(0)
    await b.wrapper.get('[data-testid="cred-ado_pat:lib:gone"] button').trigger('click')
    await flushPromises()
    const del = fake.calls.find((c) => c.method === 'DELETE')!
    expect(del.path).toBe('/api/credentials/ado_pat%3Alib%3Agone')
    expect(del.query).toEqual({ revision: '5' })
    await b.done()
  })
})

describe('常规页与只读错误态', () => {
  it('显示数据目录、旧配置目录、版本、schema 版本、store 状态', async () => {
    const b = await open(createFake(), '常规')
    expect(byTid(b, 'general-data-dir').text()).toBe('/tmp/fake-data')
    expect(byTid(b, 'general-legacy-dir').text()).toBe('/tmp/fake-legacy')
    expect(byTid(b, 'general-app-version').text()).toBe('0.1.0')
    expect(byTid(b, 'general-schema').text()).toBe('1')
    expect(byTid(b, 'general-store-state').text()).toBe('正常')
    await b.done()
  })

  it('readonly_error：页面级提示原因与文件位置，写入口全部停用', async () => {
    const fake = createFake()
    fake.state.settings = makeSettings({
      store_state: 'readonly_error',
      store_error: 'config.json 校验失败',
    })
    const b = await open(fake, '常规')
    expect(byTid(b, 'store-error').text()).toContain('config.json 校验失败')
    expect(byTid(b, 'store-error').text()).toContain('/tmp/fake-data')
    expect(byTid(b, 'general-store-error').exists()).toBe(true)
    await selectTab(b, '导入')
    expect(byTid(b, 'import-preview').attributes('disabled')).toBeDefined()
    await selectTab(b, 'ADO 连接')
    expect(byTid(b, 'library-add').attributes('disabled')).toBeDefined()
    await click(b, 'library-row-lib:a')
    expect(byTid(b, 'library-save').attributes('disabled')).toBeDefined()
    await b.done()
  })
})

describe('settings.changed 事件', () => {
  it('收到事件后设置查询失效并重新取数', async () => {
    const fake = createFake()
    const b = await open(fake, 'ADO 连接')
    const before = {
      s: fake.to('GET', '/api/settings').length,
      a: fake.to('GET', '/api/ado').length,
      c: fake.to('GET', '/api/credentials').length,
    }
    fake.state.ado = makeAdo({
      revision: 6,
      libraries: [
        {
          id: 'lib:z',
          name: '别处新增',
          base_url: 'https://z.example.test',
          credential: { present: false, source: 'unknown', state: 'missing' },
        },
      ],
      projects: [],
    })
    b.sock.emit(env('settings.changed', { revision: 6 }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()
    expect(fake.to('GET', '/api/settings').length).toBeGreaterThan(before.s)
    expect(fake.to('GET', '/api/ado').length).toBeGreaterThan(before.a)
    expect(fake.to('GET', '/api/credentials').length).toBeGreaterThan(before.c)
    expect(b.wrapper.get('[data-testid=library-table]').text()).toContain('别处新增')
    expect(useBackendStore().settingsRevision).toBe(6)
    await b.done()
  })
})

describe('pnpm dev:web 隔离环境（合同）', () => {
  it('脚本给后端设置临时数据目录、假旧配置、内存凭据与假 PAT 预置，并在退出时删除临时目录', async () => {
    const { readFileSync } = await import('node:fs')
    const src = readFileSync('scripts/dev-web.mjs', 'utf8')
    for (const k of [
      'TOOLBOX_DATA_DIR: dataDir',
      'TOOLBOX_LEGACY_CONFIG_DIR: legacyDir',
      "TOOLBOX_CREDENTIALS: 'memory'",
      'TOOLBOX_DEV_FAKE_CREDENTIALS: fakeCredentials',
      "mkdtempSync(join(tmpdir(), 'toolbox-dev-web-'))",
      'rmSync(dataDir',
      "'tests', 'fixtures', 'legacy'",
      "'tests', 'fixtures', 'dev-credentials.json'",
    ])
      expect(src).toContain(k)
  })
})
