// S1-F：设置页审计收尾回归（CR-S1B-001..004 + UX 小项）。假 fetch/假 socket，不连任何真实服务。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import { FAKE_PAT, createFake, err, json, makeAdo, makeSettings, type Fake } from './settings-fake'

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

async function open(fake: Fake) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  const t = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith('ADO 连接'))!
  await t.trigger('mousedown')
  await flushPromises()
  return b
}
type B = Awaited<ReturnType<typeof open>>
const byTid = (b: B, id: string) => b.wrapper.find(`[data-testid="${id}"]`)
async function click(b: B, id: string) {
  await b.wrapper.get(`[data-testid="${id}"]`).trigger('click')
  await flushPromises()
}
const field = (b: B, label: string) =>
  b.wrapper
    .findAll('label.text-input')
    .find((l) => l.get('.sr-only').text() === label)!
    .get('input')
const typeInto = (b: B, label: string, v: string) => field(b, label).setValue(v)
const valueOf = (b: B, label: string) => (field(b, label).element as HTMLInputElement).value
const pwd = (b: B) => b.wrapper.get('input[type=password]')
const patchesOf = (f: Fake) => f.calls.filter((c) => c.method === 'PATCH')
const isDisabled = (b: B, id: string) => byTid(b, id).attributes('disabled') !== undefined

/** 外部窗口修改：服务器数据真的变了（不只是 revision），并经 settings.changed 通知。 */
async function externalChange(b: B, fake: Fake, ado: ReturnType<typeof makeAdo>) {
  fake.state.ado = ado
  b.sock.emit(env('settings.changed', { revision: ado.revision }, { topic: 'settings' }))
  await flushPromises()
  await flushPromises()
}

function gate() {
  let release!: () => void
  const p = new Promise<void>((r) => (release = r))
  return { p, release }
}

describe('CR-S1B-001：编辑基线与 409 合并', () => {
  it('library：外部改了用户未编辑的地址；保存名称只发 name+基线 revision，409 后合并并更新基线', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH' && (c.body as { revision: number }).revision === 5
        ? err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
        : c.method === 'PATCH'
          ? json({ revision: 10 })
          : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '我的改名')

    const ext = makeAdo({ revision: 9 })
    ext.libraries[0]!.base_url = 'https://ext.example.test/tfs'
    await externalChange(b, fake, ext)

    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(1)
    expect(patchesOf(fake)[0]!.body).toEqual({ revision: 5, name: '我的改名', keep_pat: false })
    expect(byTid(b, 'settings-notice').text()).toContain(
      '设置已被其他窗口修改，已合并最新内容，请核对后再保存',
    )
    expect(valueOf(b, 'library 名称')).toBe('我的改名')
    expect(valueOf(b, 'library 地址')).toBe('https://ext.example.test/tfs')

    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(2)
    expect(patchesOf(fake)[1]!.body).toEqual({ revision: 9, name: '我的改名', keep_pat: false })
  })

  it('library：外部只推进 revision、条目字段未变时基线 revision 静默前移，保存带新 revision（不自动重试）', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH'
        ? err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 7 })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'N1')
    await externalChange(b, fake, makeAdo({ revision: 7 }))
    await click(b, 'library-save')
    expect(patchesOf(fake)[0]!.body).toMatchObject({ revision: 7 })
    await flushPromises()
    expect(patchesOf(fake)).toHaveLength(1)
  })

  it('project：外部改了未编辑的 project 名；保存 collection 只发 collection+基线 revision，409 后合并', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH' && (c.body as { revision: number }).revision === 5
        ? err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
        : c.method === 'PATCH'
          ? json({ revision: 10 })
          : undefined,
    )
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await typeInto(b, 'collection', 'MyCol')

    const ext = makeAdo({ revision: 9 })
    ext.projects[0]!.project = '外部改名'
    await externalChange(b, fake, ext)

    await click(b, 'project-save')
    expect(patchesOf(fake)[0]!.body).toEqual({ revision: 5, collection: 'MyCol' })
    expect(byTid(b, 'settings-notice').text()).toContain('已合并最新内容')
    expect(valueOf(b, 'collection')).toBe('MyCol')
    expect(valueOf(b, 'project 名称')).toBe('外部改名')

    await click(b, 'project-save')
    expect(patchesOf(fake)[1]!.body).toEqual({ revision: 9, collection: 'MyCol' })
  })

  it('自己保存成功后基线前进：再次编辑保存携带新 revision，不触发 409', async () => {
    const fake = createFake()
    fake.handlers.push((c) => (c.method === 'PATCH' ? json({ revision: 6 }) : undefined))
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'A1')
    await click(b, 'library-save')
    fake.state.ado = makeAdo({ revision: 6 })
    await typeInto(b, 'library 名称', 'A2')
    await click(b, 'library-save')
    expect(patchesOf(fake).map((c) => c.body)).toEqual([
      { revision: 5, name: 'A1', keep_pat: false },
      { revision: 6, name: 'A2', keep_pat: false },
    ])
  })
})

describe('CR-S1B-002：origin 变更确认冻结', () => {
  async function pendingOrigin(fake: Fake) {
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      const body = c.body as { keep_pat?: boolean; pat?: string }
      return !body.keep_pat && !body.pat
        ? err(409, 'pat_origin_change', 'origin 已变化')
        : json({ revision: 6 })
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    return b
  }

  it('确认期间名称/地址输入禁用；即使输入被绕过改动，确认也只提交冻结请求体', async () => {
    const fake = createFake()
    const b = await pendingOrigin(fake)
    expect(byTid(b, 'pat-origin-change').text()).toContain('https://other.example.test')
    expect(field(b, 'library 地址').attributes('disabled')).toBeDefined()
    expect(field(b, 'library 名称').attributes('disabled')).toBeDefined()
    expect(isDisabled(b, 'library-save')).toBe(true)

    // 绕过禁用，直接派发 input 事件篡改草稿
    const nameEl = field(b, 'library 名称').element as HTMLInputElement
    nameEl.value = '偷改名称'
    nameEl.dispatchEvent(new Event('input'))
    const urlEl = field(b, 'library 地址').element as HTMLInputElement
    urlEl.value = 'https://evil.example.test/tfs'
    urlEl.dispatchEvent(new Event('input'))
    await flushPromises()
    expect(byTid(b, 'pat-origin-change').text()).toContain('https://other.example.test')
    expect(byTid(b, 'pat-origin-change').text()).not.toContain('evil')

    await click(b, 'origin-keep')
    expect(patchesOf(fake).at(-1)!.body).toEqual({
      revision: 5,
      base_url: 'https://other.example.test/tfs',
      keep_pat: true,
    })
  })

  it('替换分支同样只提交冻结请求体；取消后输入恢复可编辑', async () => {
    const fake = createFake()
    const b = await pendingOrigin(fake)
    await click(b, 'origin-cancel')
    expect(byTid(b, 'pat-origin-change').exists()).toBe(false)
    expect(field(b, 'library 地址').attributes('disabled')).toBeUndefined()
    await click(b, 'library-save')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'origin-replace')
    expect(patchesOf(fake).at(-1)!.body).toEqual({
      revision: 5,
      base_url: 'https://other.example.test/tfs',
      pat: FAKE_PAT,
      keep_pat: false,
    })
  })
})

describe('CR-S1B-003：store_unavailable', () => {
  it('503 store_unavailable：立即刷新 overview，存储变只读错误态后写入口停用且 act 入口拒绝', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      fake.state.settings = makeSettings({ store_state: 'readonly_error', store_error: '存储损坏' })
      return err(503, 'store_unavailable', '存储不可用')
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    const before = fake.to('GET', '/api/settings').length
    await click(b, 'library-save')
    expect(fake.to('GET', '/api/settings').length).toBeGreaterThan(before)
    expect(byTid(b, 'store-error').exists()).toBe(true)
    expect(isDisabled(b, 'library-save')).toBe(true)

    // 绕过禁用：入口直接拒绝，不发请求
    const el = byTid(b, 'library-save').element as HTMLButtonElement
    el.removeAttribute('disabled')
    el.click()
    await flushPromises()
    expect(patchesOf(fake)).toHaveLength(1)
    expect(byTid(b, 'settings-notice').text()).toContain('不可写')
  })

  it('503 后刷新失败：保持不可写，直到确认 store_state=ok', async () => {
    const fake = createFake()
    let broken = false
    fake.handlers.push((c) => {
      if (c.method === 'PATCH') {
        broken = true
        return err(503, 'store_unavailable', '存储不可用')
      }
      if (broken && c.method === 'GET' && c.path === '/api/settings')
        return err(500, 'internal', '失败')
      return undefined
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(isDisabled(b, 'library-save')).toBe(true)
    expect(isDisabled(b, 'library-add')).toBe(true)
  })

  it('503 后刷新确认 ok：恢复可写', async () => {
    const fake = createFake()
    let first = true
    fake.handlers.push((c) => {
      if (c.method === 'PATCH' && first) {
        first = false
        return err(503, 'store_unavailable', '存储不可用')
      }
      return undefined
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    const before = fake.to('GET', '/api/settings').length
    await click(b, 'library-save')
    expect(fake.to('GET', '/api/settings').length).toBeGreaterThan(before)
    expect(isDisabled(b, 'library-save')).toBe(false)
  })

  it('503 store_busy：只提示稍后重试，不改变可写状态、不额外刷新 overview', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH' ? err(503, 'store_busy', '存储忙，请稍后重试') : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    const before = fake.to('GET', '/api/settings').length
    await click(b, 'library-save')
    expect(byTid(b, 'settings-notice').text()).toContain('稍后重试')
    expect(isDisabled(b, 'library-save')).toBe(false)
    expect(fake.to('GET', '/api/settings').length).toBe(before)
  })
})

describe('CR-S1B-004：写响应 warnings', () => {
  it('删除 library 响应含 warnings：显示警告而非成功文案，并刷新凭据', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'DELETE' && c.path.startsWith('/api/ado/libraries/')
        ? json({ revision: 6, warnings: ['Keychain 条目删除失败，已保留为待删除'] })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:b')
    await click(b, 'library-delete')
    const before = fake.to('GET', '/api/credentials').length
    await click(b, 'library-delete-confirm')
    const n = byTid(b, 'settings-notice')
    expect(n.attributes('data-kind')).toBe('warn')
    expect(n.text()).not.toContain('已删除 library')
    expect(byTid(b, 'notice-warnings').text()).toContain('Keychain 条目删除失败')
    expect(fake.to('GET', '/api/credentials').length).toBeGreaterThan(before)
  })

  it('无 warnings 时仍显示成功文案', async () => {
    const fake = createFake()
    const b = await open(fake)
    await click(b, 'library-row-lib:b')
    await click(b, 'library-delete')
    await click(b, 'library-delete-confirm')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('ok')
    expect(byTid(b, 'settings-notice').text()).toContain('已删除 library')
  })
})

describe('UX：busy 提示、被拒请求不清空 PAT、PAT 最小长度', () => {
  it('写操作进行中再次触发：提示“操作进行中，请稍候”，不重复发请求', async () => {
    const fake = createFake()
    const g = gate()
    fake.handlers.push(async (c) => {
      if (c.method !== 'PATCH') return undefined
      await g.p
      return json({ revision: 6 })
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    const btn = byTid(b, 'library-save')
    const p1 = btn.trigger('click')
    const p2 = btn.trigger('click')
    await Promise.all([p1, p2])
    await flushPromises()
    expect(byTid(b, 'settings-notice').text()).toContain('操作进行中，请稍候')
    g.release()
    await flushPromises()
    expect(patchesOf(fake)).toHaveLength(1)
  })

  it('被 busy 拒绝的请求不清空 PAT 输入；请求真正发出后才清空', async () => {
    const fake = createFake()
    const g = gate()
    fake.handlers.push(async (c) => {
      if (c.method !== 'PATCH') return undefined
      await g.p
      return json({ revision: 6 })
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:b')
    await typeInto(b, 'library 名称', 'X')
    await pwd(b).setValue(FAKE_PAT)
    const p1 = byTid(b, 'library-save').trigger('click')
    const p2 = byTid(b, 'pat-save').trigger('click')
    await Promise.all([p1, p2])
    await flushPromises()
    expect((pwd(b).element as HTMLInputElement).value).toBe(FAKE_PAT)
    expect(fake.calls.some((c) => c.method === 'PUT')).toBe(false)
    g.release()
    await flushPromises()
    expect((pwd(b).element as HTMLInputElement).value).toBe(FAKE_PAT)
    await click(b, 'pat-save')
    expect(fake.calls.filter((c) => c.method === 'PUT')).toHaveLength(1)
    expect((pwd(b).element as HTMLInputElement).value).toBe('')
  })

  it('不可写时被拒绝的 PAT 请求不清空输入', async () => {
    const fake = createFake()
    const b = await open(fake)
    await click(b, 'library-row-lib:b')
    await pwd(b).setValue(FAKE_PAT)
    fake.state.settings = makeSettings({ store_state: 'readonly_error', store_error: 'x' })
    b.sock.emit(env('settings.changed', { revision: 6 }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()
    const el = byTid(b, 'pat-save').element as HTMLButtonElement
    el.removeAttribute('disabled')
    el.click()
    await flushPromises()
    expect(fake.calls.some((c) => c.method === 'PUT')).toBe(false)
    expect((pwd(b).element as HTMLInputElement).value).toBe(FAKE_PAT)
  })

  it('PAT 少于 8 字符：不发请求、提示、输入保留；8 字符放行（保存/新建/测试）', async () => {
    const fake = createFake()
    const b = await open(fake)
    await click(b, 'library-row-lib:b')
    await pwd(b).setValue('1234567')
    await click(b, 'pat-save')
    expect(fake.calls.some((c) => c.method === 'PUT')).toBe(false)
    expect(byTid(b, 'library-local-error').text()).toContain('8')
    expect((pwd(b).element as HTMLInputElement).value).toBe('1234567')

    await typeInto(b, '测试用 collection', 'Col')
    await click(b, 'library-test')
    expect(fake.calls.some((c) => c.path.endsWith('/test'))).toBe(false)

    await pwd(b).setValue('12345678')
    await click(b, 'pat-save')
    expect(fake.calls.filter((c) => c.method === 'PUT')).toHaveLength(1)

    await click(b, 'library-add')
    await typeInto(b, 'library 名称', 'n')
    await typeInto(b, 'library 地址', 'https://n.example.test')
    await pwd(b).setValue('short')
    await click(b, 'library-create')
    expect(fake.to('POST', '/api/ado/libraries')).toHaveLength(0)
    expect((pwd(b).element as HTMLInputElement).value).toBe('short')
  })
})
