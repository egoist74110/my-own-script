// S1-B 独立测试（independent=true）：PAT 不外泄、409/错误码文案、导入状态与阻断、
// 页签可访问关联与键盘、settings.changed 刷新与后续写的 revision。
// 只用假 fetch（tests/unit/settings-fake.ts）与假 socket；不连任何真实服务。
import { flushPromises } from '@vue/test-utils'
import type { QueryClient } from '@tanstack/vue-query'
import { getActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import { useBackendStore } from '@/stores/backend'
import { boot } from '../unit/boot'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'
import {
  FAKE_PAT,
  createFake,
  err,
  json,
  makeAdo,
  makePreview,
  makeSettings,
  type Fake,
} from '../unit/settings-fake'

type B = Awaited<ReturnType<typeof boot>>
interface Seen {
  url: string
  headers: string
}

const mounted: B[] = []
let consoleSpies: MockInstance[] = []

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
  consoleSpies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => {}),
  )
})
afterEach(async () => {
  for (const b of mounted.splice(0)) await b.done()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

/** 包一层 fetch，记录每个请求的完整 URL 与请求头（请求体仍交给假后端）。 */
function fetchWithSeen(fake: Fake, seen: Seen[]): typeof fetch {
  return (async (req: Request) => {
    seen.push({ url: req.url, headers: JSON.stringify(Array.from(req.headers.entries())) })
    return fake.fetch(req)
  }) as unknown as typeof fetch
}

async function open(fake: Fake, opts: { tab?: string; fetchImpl?: typeof fetch } = {}) {
  const b = await boot({ path: '/settings', fetchImpl: opts.fetchImpl ?? fake.fetch })
  mounted.push(b)
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  if (opts.tab) await selectTab(b, opts.tab)
  return b
}

async function openPath(path: string, fake: Fake = createFake()) {
  const b = await boot({ path, fetchImpl: fake.fetch })
  mounted.push(b)
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  return b
}

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
  await input.get('input').setValue(value)
}
const pwd = (b: B) => b.wrapper.get('input[type=password]')
const pwdValue = (b: B) => (pwd(b).element as HTMLInputElement).value
const gets = (fake: Fake) => fake.calls.filter((c) => c.method === 'GET').length
const writes = (fake: Fake, method: string, path: string) =>
  fake.calls.filter((c) => c.method === method && c.path === path)

/** 取得页面的 vue-query client（插件 provide 在应用上下文中）。 */
function queryClientOf(b: B): QueryClient {
  const provides = b.wrapper.vm.$.appContext.provides as Record<string, unknown>
  const qc = Object.values(provides).find(
    (v): v is QueryClient => typeof v === 'object' && v !== null && 'getQueryCache' in v,
  )
  if (!qc) throw new Error('query client not found')
  return qc
}

/** PAT 只允许出现在请求体里：检查 DOM、存储、URL、console、Pinia、query/mutation 缓存。 */
function expectNoPat(b: B) {
  const hit = (s: string) => expect(s).not.toContain(FAKE_PAT)
  hit(document.documentElement.outerHTML)
  hit(document.body.textContent ?? '')
  hit(JSON.stringify({ ...localStorage }))
  hit(JSON.stringify({ ...sessionStorage }))
  hit(location.href)
  hit(JSON.stringify(consoleSpies.map((s) => s.mock.calls)))
  hit(JSON.stringify(getActivePinia()!.state.value))
  const qc = queryClientOf(b)
  hit(
    JSON.stringify(
      qc
        .getQueryCache()
        .getAll()
        .map((q) => [q.queryKey, q.state]),
    ),
  )
  hit(
    JSON.stringify(
      qc
        .getMutationCache()
        .getAll()
        .map((m) => m.state),
    ),
  )
}

/** 请求路径、查询串、请求头都不含 PAT；PAT 只出现在指定数量的请求体中。 */
function expectPatOnlyInBodies(fake: Fake, seen: Seen[], bodies: number) {
  for (const c of fake.calls) {
    expect(c.path).not.toContain(FAKE_PAT)
    expect(JSON.stringify(c.query)).not.toContain(FAKE_PAT)
  }
  for (const s of seen) {
    expect(s.url).not.toContain(FAKE_PAT)
    expect(s.headers).not.toContain(FAKE_PAT)
  }
  expect(fake.calls.filter((c) => c.raw.includes(FAKE_PAT))).toHaveLength(bodies)
}

const patchesOf = (fake: Fake) => fake.calls.filter((c) => c.method === 'PATCH')

describe('PAT 不外泄（提交成功与失败路径）', () => {
  it('新建 library 带 PAT 被 422 拒绝：输入清空；PAT 只在一次请求体中出现', async () => {
    const fake = createFake()
    const seen: Seen[] = []
    fake.handlers.push((c) =>
      c.method === 'POST' && c.path === '/api/ado/libraries'
        ? err(422, 'validation_error', '配置校验失败')
        : undefined,
    )
    const b = await open(fake, { tab: 'ADO 连接', fetchImpl: fetchWithSeen(fake, seen) })
    await click(b, 'library-add')
    await typeInto(b, 'library 名称', '新库')
    await typeInto(b, 'library 地址', 'https://n.example.test')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'library-create')
    expect(byTid(b, 'settings-notice').text()).toContain('配置校验失败')
    expect(pwdValue(b)).toBe('')
    expect(fake.calls.find((c) => c.raw.includes(FAKE_PAT))!.path).toBe('/api/ado/libraries')
    expectPatOnlyInBodies(fake, seen, 1)
    expectNoPat(b)
  })

  it('保存 PAT 时网络异常，且异常文本含 PAT：界面只显示固定文案，输入清空，PAT 不泄漏', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method === 'PUT' && c.path.endsWith('/pat'))
        throw new TypeError(`socket reset while sending ${FAKE_PAT}`)
      return undefined
    })
    const b = await open(fake, { tab: 'ADO 连接' })
    await click(b, 'library-row-lib:b')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'pat-save')
    expect(byTid(b, 'settings-notice').text()).toContain('无法连接后端')
    expect(pwdValue(b)).toBe('')
    expectNoPat(b)
  })

  it('测试连接带候选 PAT，返回 unauthorized：结果只显示分类文案，输入清空，PAT 只在请求体', async () => {
    const fake = createFake()
    const seen: Seen[] = []
    fake.handlers.push((c) =>
      c.path.endsWith('/test')
        ? json({ ok: false, category: 'unauthorized', http_status: 401, message: '认证失败' })
        : undefined,
    )
    const b = await open(fake, { tab: 'ADO 连接', fetchImpl: fetchWithSeen(fake, seen) })
    await click(b, 'library-row-lib:a')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'library-test')
    expect(byTid(b, 'test-result').text()).toContain('认证失败（PAT 无效或已过期）')
    expect(pwdValue(b)).toBe('')
    expectPatOnlyInBodies(fake, seen, 1)
    expectNoPat(b)
  })

  it('pat_origin_change 选择“保留”时，即使输入框里有字，也不发送 pat（只发 keep_pat:true）', async () => {
    const fake = createFake()
    let first = true
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      if (first) {
        first = false
        return err(409, 'pat_origin_change', 'origin 已变化')
      }
      return json({ revision: 6 })
    })
    const b = await open(fake, { tab: 'ADO 连接' })
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'origin-keep')
    const last = patchesOf(fake).at(-1)!
    expect(last.body).toMatchObject({ keep_pat: true, base_url: 'https://other.example.test/tfs' })
    expect(last.body).not.toHaveProperty('pat')
    expect(fake.calls.filter((c) => c.raw.includes(FAKE_PAT))).toHaveLength(0)
    expect(pwdValue(b)).toBe('')
    expectNoPat(b)
  })

  it('pat_origin_change 选择“替换”但后端 502：输入清空，origin 提示保留以便重试，PAT 不泄漏', async () => {
    const fake = createFake()
    const seen: Seen[] = []
    let first = true
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      if (first) {
        first = false
        return err(409, 'pat_origin_change', 'origin 已变化')
      }
      return err(502, 'credential_backend_error', '凭据后端访问失败')
    })
    const b = await open(fake, { tab: 'ADO 连接', fetchImpl: fetchWithSeen(fake, seen) })
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://third.example.test')
    await click(b, 'library-save')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'origin-replace')
    expect(byTid(b, 'settings-notice').text()).toContain('凭据后端访问失败')
    expect(byTid(b, 'pat-origin-change').exists()).toBe(true)
    expect(pwdValue(b)).toBe('')
    expectPatOnlyInBodies(fake, seen, 1)
    expectNoPat(b)
  })

  it('“替换”分支输入框为空：不发请求，提示输入新 PAT', async () => {
    const fake = createFake()
    let first = true
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      if (first) {
        first = false
        return err(409, 'pat_origin_change', 'origin 已变化')
      }
      return json({ revision: 6 })
    })
    const b = await open(fake, { tab: 'ADO 连接' })
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test')
    await click(b, 'library-save')
    const before = patchesOf(fake).length
    await click(b, 'origin-replace')
    expect(byTid(b, 'library-local-error').text()).toContain('请输入新的 PAT')
    expect(patchesOf(fake)).toHaveLength(before)
    await b.done()
  })

  it('切换到另一个 library 后 PAT 输入框清空且 autocomplete 关闭', async () => {
    const fake = createFake()
    const b = await open(fake, { tab: 'ADO 连接' })
    await click(b, 'library-row-lib:a')
    expect(pwd(b).attributes('autocomplete')).toBe('off')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'library-row-lib:b')
    expect(pwdValue(b)).toBe('')
    expectNoPat(b)
  })

  it('后端 422 的错误体若回显 PAT：界面只显示固定 message，PAT 不出现在 DOM', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PUT' && c.path.endsWith('/pat')
        ? err(422, 'validation_error', '配置校验失败', { echo: FAKE_PAT })
        : undefined,
    )
    const b = await open(fake, { tab: 'ADO 连接' })
    await click(b, 'library-row-lib:b')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'pat-save')
    expect(byTid(b, 'settings-notice').text()).toContain('配置校验失败')
    expectNoPat(b)
  })
})

describe('409 与错误码文案', () => {
  it('revision_conflict：刷新为新 revision、不自动重试；用户再次保存时携带新 revision', async () => {
    const fake = createFake()
    let n = 0
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      n++
      if (n === 1) {
        fake.state.ado = makeAdo({ revision: 9 })
        return err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
      }
      return json({ revision: 10 })
    })
    const b = await open(fake, { tab: 'ADO 连接' })
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '又改名')
    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(1)
    expect(byTid(b, 'settings-notice').attributes('role')).toBe('alert')
    expect(byTid(b, 'settings-notice').text()).toContain('已合并最新内容')
    await flushPromises()
    expect(patchesOf(fake)).toHaveLength(1)
    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(2)
    expect(patchesOf(fake)[1]!.body).toMatchObject({ revision: 9, name: '又改名' })
  })

  it('in_use（project 删除）：列出引用任务名，忽略非字符串条目', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'DELETE' && c.path.startsWith('/api/ado/projects/')
        ? err(409, 'in_use', '条目被任务引用', { tasks: ['任务A', 42, null, '任务B'] })
        : undefined,
    )
    const b = await open(fake, { tab: 'ADO 连接' })
    await click(b, 'project-row-proj:a')
    await click(b, 'project-delete')
    await click(b, 'project-delete-confirm')
    expect(b.wrapper.findAll('[data-testid=notice-tasks] li').map((l) => l.text())).toEqual([
      '任务A',
      '任务B',
    ])
    expect(byTid(b, 'settings-notice').text()).toContain('被任务引用')
  })

  it('in_use 但 tasks 为空：只显示提示，不渲染空列表', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'DELETE' && c.path.startsWith('/api/ado/libraries/')
        ? err(409, 'in_use', '条目被任务引用', { tasks: [] })
        : undefined,
    )
    const b = await open(fake, { tab: 'ADO 连接' })
    await click(b, 'library-row-lib:a')
    await click(b, 'library-delete')
    await click(b, 'library-delete-confirm')
    expect(byTid(b, 'settings-notice').text()).toContain('被任务引用')
    expect(byTid(b, 'notice-tasks').exists()).toBe(false)
  })

  const storeErrors = [
    ['store_busy', '存储忙，请稍后重试'],
    ['store_unavailable', '存储不可用，所有写操作已停用'],
  ] as const
  for (const [code, message] of storeErrors) {
    it(`503 ${code}：显示后端固定文案，不回显被操作的凭据账号名`, async () => {
      const fake = createFake()
      fake.handlers.push((c) =>
        c.method === 'DELETE' && c.path.startsWith('/api/credentials/')
          ? err(503, code, message)
          : undefined,
      )
      const b = await open(fake, { tab: '凭据' })
      await b.wrapper.get('[data-testid="cred-ado_pat:lib:gone"] button').trigger('click')
      await flushPromises()
      const text = byTid(b, 'settings-notice').text()
      expect(text).toContain(message)
      expect(text).not.toContain('lib:gone')
      expect(byTid(b, 'cred-ado_pat:lib:gone').exists()).toBe(true)
    })
  }

  const rawFailures: [string, () => Response][] = [
    [
      '503 纯文本/HTML 体',
      () =>
        new Response('<html>upstream boom</html>', {
          status: 503,
          headers: { 'content-type': 'text/html' },
        }),
    ],
    ['404 字符串 detail', () => json({ detail: 'Not Found' }, 404)],
  ]
  for (const [label, make] of rawFailures) {
    it(`${label}：只显示 HTTP 状态文案，不显示原始响应体`, async () => {
      const fake = createFake()
      fake.handlers.push((c) => (c.method === 'PATCH' ? make() : undefined))
      const b = await open(fake, { tab: 'ADO 连接' })
      await click(b, 'library-row-lib:a')
      await typeInto(b, 'library 名称', '改')
      await click(b, 'library-save')
      const text = byTid(b, 'settings-notice').text()
      expect(text).toMatch(/请求失败（HTTP (503|404)）/)
      expect(text).not.toContain('upstream boom')
      expect(text).not.toContain('Not Found')
    })
  }
})

describe('导入状态与阻断', () => {
  it('in_progress：只显示进行中说明，没有预览/跳过/执行入口', async () => {
    const fake = createFake()
    fake.state.settings = makeSettings({ import: { state: 'in_progress' } })
    const b = await open(fake, { tab: '导入' })
    expect(byTid(b, 'import-in-progress').exists()).toBe(true)
    expect(b.wrapper.get('[data-testid=import-tab]').text()).toContain('导入进行中')
    expect(byTid(b, 'import-preview').exists()).toBe(false)
    expect(byTid(b, 'import-decline').exists()).toBe(false)
    expect(byTid(b, 'import-readonly').exists()).toBe(false)
  })

  it('failed：“放弃导入”发送 decline，且不会在预览前执行', async () => {
    const fake = createFake()
    fake.state.settings = makeSettings({ import: { state: 'failed', error: '写入失败' } })
    const b = await open(fake, { tab: '导入' })
    await click(b, 'import-decline')
    expect(writes(fake, 'POST', '/api/settings/import/decline')).toHaveLength(1)
    expect(writes(fake, 'POST', '/api/settings/import/execute')).toHaveLength(0)
  })

  it('确认按钮只打开二次确认框，此时不发送 execute', async () => {
    const fake = createFake()
    const b = await open(fake, { tab: '导入' })
    await click(b, 'import-preview')
    await click(b, 'import-confirm')
    expect(byTid(b, 'import-confirm-box').exists()).toBe(true)
    expect(writes(fake, 'POST', '/api/settings/import/execute')).toHaveLength(0)
  })

  it('预览进行中连续点击：只发一次 preview（busy 时不重复提交）', async () => {
    const fake = createFake()
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    fake.handlers.push(async (c) => {
      if (c.path === '/api/settings/import/preview') {
        await gate
        return json(makePreview())
      }
      return undefined
    })
    const b = await open(fake, { tab: '导入' })
    const btn = b.wrapper.get('[data-testid=import-preview]')
    await btn.trigger('click')
    await btn.trigger('click')
    await flushPromises()
    expect(writes(fake, 'POST', '/api/settings/import/preview')).toHaveLength(1)
    release()
    await flushPromises()
    await flushPromises()
    expect(writes(fake, 'POST', '/api/settings/import/preview')).toHaveLength(1)
    expect(byTid(b, 'import-confirm').exists()).toBe(true)
  })

  it('执行进行中连续点击：只发一次 execute，fingerprint 与预览一致', async () => {
    const fake = createFake()
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    fake.handlers.push(async (c) => {
      if (c.path === '/api/settings/import/execute') {
        await gate
        return json({ revision: 7 })
      }
      return undefined
    })
    const b = await open(fake, { tab: '导入' })
    await click(b, 'import-preview')
    await click(b, 'import-confirm')
    const btn = b.wrapper.get('[data-testid=import-execute]')
    await btn.trigger('click')
    await btn.trigger('click')
    await flushPromises()
    release()
    await flushPromises()
    await flushPromises()
    const exec = writes(fake, 'POST', '/api/settings/import/execute')
    expect(exec).toHaveLength(1)
    expect(exec[0]!.body).toEqual({ fingerprint: 'fp-1' })
  })

  it('重新预览出现阻断错误：之前打开的确认框消失，确认按钮禁用', async () => {
    const fake = createFake()
    let errors: string[] = []
    fake.handlers.push((c) =>
      c.path === '/api/settings/import/preview' ? json(makePreview({ errors })) : undefined,
    )
    const b = await open(fake, { tab: '导入' })
    await click(b, 'import-preview')
    await click(b, 'import-confirm')
    expect(byTid(b, 'import-confirm-box').exists()).toBe(true)
    errors = ['tasks.yaml: tasks 不是列表']
    await click(b, 'import-preview')
    expect(byTid(b, 'import-confirm-box').exists()).toBe(false)
    expect(byTid(b, 'import-errors').text()).toContain('tasks 不是列表')
    expect(byTid(b, 'import-confirm').attributes('disabled')).toBeDefined()
    expect(writes(fake, 'POST', '/api/settings/import/execute')).toHaveLength(0)
  })

  it('import_source_changed 后必须重新预览：旧 fingerprint 不再使用，新预览用新 fingerprint', async () => {
    const fake = createFake()
    let previews = 0
    fake.handlers.push((c) => {
      if (c.path === '/api/settings/import/preview') {
        previews++
        return json(makePreview({ fingerprint: previews === 1 ? 'fp-1' : 'fp-2' }))
      }
      if (c.path === '/api/settings/import/execute') {
        return previews === 1
          ? err(409, 'import_source_changed', '源配置已变化，请重新预览')
          : json({ revision: 7 })
      }
      return undefined
    })
    const b = await open(fake, { tab: '导入' })
    await click(b, 'import-preview')
    await click(b, 'import-confirm')
    await click(b, 'import-execute')
    expect(byTid(b, 'import-stale').exists()).toBe(true)
    expect(byTid(b, 'import-confirm').exists()).toBe(false)
    expect(byTid(b, 'settings-notice').exists()).toBe(false)
    await click(b, 'import-preview')
    expect(byTid(b, 'import-stale').exists()).toBe(false)
    await click(b, 'import-confirm')
    await click(b, 'import-execute')
    const exec = writes(fake, 'POST', '/api/settings/import/execute')
    expect(exec.map((c) => (c.body as { fingerprint: string }).fingerprint)).toEqual([
      'fp-1',
      'fp-2',
    ])
  })
})

describe('页签：可访问关联与键盘', () => {
  it('设置页签 Home/End/ArrowUp 可达（竖向列表，ArrowUp 从首项回绕到末项）', async () => {
    const b = await open(createFake())
    const tabs = b.wrapper.findAll('[role=tab]')
    const selected = () => b.wrapper.get('[role=tab][aria-selected=true]').text()
    ;(tabs[0]!.element as HTMLElement).focus()
    await tabs[0]!.trigger('keydown', { key: 'End' })
    await flushPromises()
    expect(selected()).toContain('常规')
    await b.wrapper.findAll('[role=tab]')[3]!.trigger('keydown', { key: 'Home' })
    await flushPromises()
    expect(selected()).toContain('导入')
    await b.wrapper.findAll('[role=tab]')[0]!.trigger('keydown', { key: 'ArrowUp' })
    await flushPromises()
    expect(selected()).toContain('常规')
  })

  it('设置页签 roving tabindex：只有当前页签在 Tab 序列中', async () => {
    const b = await open(createFake())
    await selectTab(b, 'ADO 连接')
    const idx = b.wrapper.findAll('[role=tab]').map((t) => t.attributes('tabindex'))
    expect(idx).toEqual(['-1', '0', '-1', '-1', '-1', '-1', '-1', '-1'])
  })

  it('/work-items 看板列页签：aria-controls 与 tabpanel 的 aria-labelledby 一致', async () => {
    const b = await openPath('/work-items')
    const sel = () => b.wrapper.get('[role=tab][aria-selected=true]')
    expect(sel().attributes('aria-controls')).toBe('wi-list-panel')
    const panel = document.getElementById('wi-list-panel')!
    expect(panel.getAttribute('role')).toBe('tabpanel')
    expect(panel.getAttribute('aria-labelledby')).toBe(sel().attributes('id'))
    const before = sel().text()
    // 看板列固定为五列、默认「开发中」（mock 删除后不再是原来的列序）：在当前选中的页签上按 →
    await sel().trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(sel().text()).not.toBe(before)
    expect(panel.getAttribute('aria-labelledby')).toBe(sel().attributes('id'))
  })

  it('/ai 筛选页签：aria-controls 指向 ai-sessions-panel，切换后 aria-labelledby 跟随', async () => {
    const b = await openPath('/ai')
    const sel = () => b.wrapper.get('[role=tab][aria-selected=true]')
    expect(sel().attributes('aria-controls')).toBe('ai-sessions-panel')
    const panel = document.getElementById('ai-sessions-panel')!
    expect(panel.getAttribute('role')).toBe('tabpanel')
    expect(panel.getAttribute('aria-labelledby')).toBe(sel().attributes('id'))
    await b.wrapper.findAll('[role=tab]')[0]!.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(panel.getAttribute('aria-labelledby')).toBe(sel().attributes('id'))
  })
})

describe('settings.changed 刷新与后续写的 revision', () => {
  it('事件后 ADO 页写请求携带事件之后的 revision', async () => {
    const fake = createFake()
    const b = await open(fake, { tab: 'ADO 连接' })
    fake.state.ado = makeAdo({ revision: 6 })
    b.sock.emit(env('settings.changed', { revision: 6 }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '事件后改名')
    await click(b, 'library-save')
    expect(patchesOf(fake).at(-1)!.body).toMatchObject({ revision: 6 })
  })

  it('事件后导入状态变为 completed：页面切换为只读摘要，不再有预览入口', async () => {
    const fake = createFake()
    const b = await open(fake, { tab: '导入' })
    expect(byTid(b, 'import-preview').exists()).toBe(true)
    fake.state.settings = makeSettings({
      revision: 6,
      import: {
        state: 'completed',
        finished_at: '2026-10-22T10:05:00Z',
        summary: makePreview() as unknown as Record<string, never>,
      },
    })
    b.sock.emit(env('settings.changed', { revision: 6 }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()
    expect(byTid(b, 'import-readonly').exists()).toBe(true)
    expect(byTid(b, 'import-preview').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=import-tab]').text()).toContain('示例库')
  })

  it('事件后凭据表格更新为新数据', async () => {
    const fake = createFake()
    const b = await open(fake, { tab: '凭据' })
    fake.state.creds = [
      ...fake.state.creds,
      { ...fake.state.creds[0]!, account: 'ado_pat:lib:new', ref: 'lib:new', ref_name: '新增库' },
    ]
    b.sock.emit(env('settings.changed', { revision: 6 }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()
    expect(byTid(b, 'cred-ado_pat:lib:new').text()).toContain('新增库')
  })

  it('seq 不新于已处理事件的 settings.changed 被忽略：不重新取数，revision 不更新', async () => {
    const fake = createFake()
    const b = await open(fake, { tab: '常规' })
    const before = gets(fake)
    b.sock.emit({ ...env('settings.changed', { revision: 99 }, { topic: 'settings' }), seq: 0 })
    await flushPromises()
    await flushPromises()
    expect(gets(fake)).toBe(before)
    expect(useBackendStore().settingsRevision).toBeNull()
  })
})

describe('断线重连', () => {
  it('socket 断开后重连并重新 hello：设置查询重新取数并更新界面', async () => {
    const fake = createFake()
    const b = await open(fake, { tab: 'ADO 连接' })
    const before = gets(fake)
    const n = FakeSocket.instances.length
    b.sock.drop()
    await flushPromises()
    for (let i = 0; i < 50 && FakeSocket.instances.length === n; i++)
      await new Promise((r) => setTimeout(r, 100))
    expect(FakeSocket.instances.length).toBeGreaterThan(n)
    fake.state.ado = makeAdo({ revision: 8, projects: [] })
    FakeSocket.last().open()
    await flushPromises()
    FakeSocket.last().emit(hello())
    await flushPromises()
    await flushPromises()
    expect(gets(fake)).toBeGreaterThan(before)
    expect(fake.to('GET', '/api/ado').length).toBeGreaterThan(1)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '重连后改名')
    await click(b, 'library-save')
    expect(patchesOf(fake).at(-1)!.body).toMatchObject({ revision: 8 })
  })
})

describe('凭据与常规的只读边界', () => {
  it('凭据页与常规页不存在任何可编辑输入框', async () => {
    const fake = createFake()
    const b = await open(fake, { tab: '凭据' })
    expect(b.wrapper.find('[data-testid=credentials-tab] input').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=credentials-tab] textarea').exists()).toBe(false)
    await selectTab(b, '常规')
    expect(b.wrapper.find('[data-testid=general-tab] input').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=general-tab] textarea').exists()).toBe(false)
  })

  it('凭据表格的 cleanable 判定：仅 orphan / pending_delete 行有清理按钮', async () => {
    const fake = createFake()
    fake.state.creds = [
      ...fake.state.creds,
      { ...fake.state.creds[0]!, account: 'ado_pat:lib:pend', state: 'pending_delete' },
    ]
    const b = await open(fake, { tab: '凭据' })
    expect(b.wrapper.findAll('[data-testid="cred-ado_pat:lib:a"] button')).toHaveLength(0)
    expect(b.wrapper.findAll('[data-testid="cred-ado_pat:lib:gone"] button')).toHaveLength(1)
    expect(b.wrapper.findAll('[data-testid="cred-ado_pat:lib:pend"] button')).toHaveLength(1)
  })
})
