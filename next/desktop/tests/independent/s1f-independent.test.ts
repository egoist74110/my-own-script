// S1-F 独立测试（independent=true）：草稿基线与 409 合并的边界组合、origin 确认冻结、
// store_unavailable 之后的只读与恢复、warnings 展示与过滤、写操作 UX 边界。
// 只用假 fetch（tests/unit/settings-fake.ts）与假 socket；不连任何真实服务。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

type B = Awaited<ReturnType<typeof open>>

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

async function open(fake: Fake, tab = 'ADO 连接') {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  const t = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith(tab))!
  await t.trigger('mousedown')
  await flushPromises()
  return b
}
async function selectTab(b: B, tab: string) {
  const t = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith(tab))!
  await t.trigger('mousedown')
  await flushPromises()
}
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
const pwdValue = (b: B) => (pwd(b).element as HTMLInputElement).value
const patchesOf = (f: Fake) => f.calls.filter((c) => c.method === 'PATCH')
const puts = (f: Fake) => f.calls.filter((c) => c.method === 'PUT')
const isDisabled = (b: B, id: string) => byTid(b, id).attributes('disabled') !== undefined
const warnItems = (b: B) =>
  b.wrapper.findAll('[data-testid=notice-warnings] li').map((l) => l.text())

/** 服务器侧的外部写入：数据真的变了，并经 settings.changed 通知。 */
async function externalChange(b: B, fake: Fake, ado: ReturnType<typeof makeAdo>) {
  fake.state.ado = ado
  b.sock.emit(env('settings.changed', { revision: ado.revision }, { topic: 'settings' }))
  await flushPromises()
  await flushPromises()
}

/** 外部改动 lib:a 的名称与地址（用于冲突场景）。 */
function extLibA(revision: number, name: string, base_url: string) {
  const ext = makeAdo({ revision })
  ext.libraries[0]!.name = name
  ext.libraries[0]!.base_url = base_url
  return ext
}

describe('草稿基线与 409 合并：字段改动组合', () => {
  it('library：名称与地址都被用户改，外部也都改：两者保留用户输入；合并后再保存只发基线以来仍不同的字段', async () => {
    const fake = createFake()
    let n = 0
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      n++
      if (n === 1) {
        fake.state.ado = extLibA(9, '外部名', 'https://ext.example.test/tfs')
        return err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
      }
      return json({ revision: 10 })
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'U名')
    await typeInto(b, 'library 地址', 'https://user.example.test/tfs')
    await click(b, 'library-save')
    expect(patchesOf(fake)[0]!.body).toEqual({
      revision: 5,
      name: 'U名',
      base_url: 'https://user.example.test/tfs',
      keep_pat: false,
    })
    expect(byTid(b, 'settings-notice').text()).toContain('已合并最新内容')
    expect(valueOf(b, 'library 名称')).toBe('U名')
    expect(valueOf(b, 'library 地址')).toBe('https://user.example.test/tfs')

    await click(b, 'library-save')
    expect(patchesOf(fake)[1]!.body).toEqual({
      revision: 9,
      name: 'U名',
      base_url: 'https://user.example.test/tfs',
      keep_pat: false,
    })
  })

  it('library：用户只改名称，外部同时改名称与地址：名称保留，地址换成服务器新值，之后保存只发 name', async () => {
    const fake = createFake()
    let n = 0
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      n++
      if (n === 1) {
        fake.state.ado = extLibA(9, '外部名', 'https://ext.example.test/tfs')
        return err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
      }
      return json({ revision: 10 })
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'U名')
    await click(b, 'library-save')
    expect(valueOf(b, 'library 名称')).toBe('U名')
    expect(valueOf(b, 'library 地址')).toBe('https://ext.example.test/tfs')
    await click(b, 'library-save')
    expect(patchesOf(fake)[1]!.body).toEqual({ revision: 9, name: 'U名', keep_pat: false })
  })

  it('library：用户只改地址，外部只改名称：地址保留，名称换成服务器新值，之后保存只发 base_url', async () => {
    const fake = createFake()
    let n = 0
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      n++
      if (n === 1) {
        fake.state.ado = extLibA(9, '外部名', 'https://ado.example.test/tfs')
        return err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
      }
      return json({ revision: 10 })
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://user.example.test/tfs')
    await click(b, 'library-save')
    expect(valueOf(b, 'library 名称')).toBe('外部名')
    expect(valueOf(b, 'library 地址')).toBe('https://user.example.test/tfs')
    await click(b, 'library-save')
    expect(patchesOf(fake)[1]!.body).toEqual({
      revision: 9,
      base_url: 'https://user.example.test/tfs',
      keep_pat: false,
    })
  })

  it('library：冲突后服务器已删除该条目：显示通用刷新文案（不声称已合并），不自动重发，详情收起', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      fake.state.ado = makeAdo({
        revision: 9,
        libraries: makeAdo().libraries.filter((l) => l.id !== 'lib:a'),
        projects: [],
      })
      return err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'U名')
    await click(b, 'library-save')
    await flushPromises()
    expect(byTid(b, 'settings-notice').text()).toContain('请确认后重试')
    expect(byTid(b, 'settings-notice').text()).not.toContain('已合并')
    expect(byTid(b, 'library-detail').exists()).toBe(false)
    expect(byTid(b, 'ado-inspector-empty').exists()).toBe(true)
    expect(patchesOf(fake)).toHaveLength(1)
  })

  it('project：用户改了 library 与 project 名，外部改了 collection 与 project 名：library/名称保留，collection 换成新值', async () => {
    const fake = createFake()
    let n = 0
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      n++
      if (n === 1) {
        const ext = makeAdo({ revision: 9 })
        ext.projects[0]!.collection = 'ExtCol'
        ext.projects[0]!.project = 'ExtProj'
        fake.state.ado = ext
        return err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
      }
      return json({ revision: 10 })
    })
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await b.wrapper.get('#proj-lib').setValue('lib:b')
    await typeInto(b, 'project 名称', 'U项目')
    await click(b, 'project-save')
    expect(patchesOf(fake)[0]!.body).toEqual({
      revision: 5,
      library_id: 'lib:b',
      project: 'U项目',
    })
    expect(valueOf(b, 'collection')).toBe('ExtCol')
    expect(valueOf(b, 'project 名称')).toBe('U项目')
    expect((b.wrapper.get('#proj-lib').element as HTMLSelectElement).value).toBe('lib:b')

    await click(b, 'project-save')
    expect(patchesOf(fake)[1]!.body).toEqual({
      revision: 9,
      library_id: 'lib:b',
      project: 'U项目',
    })
  })

  it('草稿与服务器一致（改了又改回）时保存不发请求，即使基线 revision 已过期', async () => {
    const fake = createFake()
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '临时')
    await typeInto(b, 'library 名称', '示例库')
    await externalChange(b, fake, makeAdo({ revision: 7 }))
    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(0)
  })
})

describe('origin 变更确认：冻结与撤销', () => {
  it('确认前同时改了名称与地址：冻结体包含两者；外部把服务器地址改走后确认，仍只提交冻结体，提示仍显示冻结 origin', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      const body = c.body as { keep_pat?: boolean }
      return body.keep_pat ? json({ revision: 6 }) : err(409, 'pat_origin_change', 'origin 已变化')
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'U名')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')

    const ext = makeAdo({ revision: 6 })
    ext.libraries[0]!.name = 'MOVED名'
    ext.libraries[0]!.base_url = 'https://moved.example.test'
    await externalChange(b, fake, ext)

    expect(byTid(b, 'pat-origin-change').text()).toContain('https://other.example.test')
    expect(byTid(b, 'pat-origin-change').text()).not.toContain('moved')

    await click(b, 'origin-keep')
    expect(patchesOf(fake).at(-1)!.body).toEqual({
      revision: 5,
      name: 'U名',
      base_url: 'https://other.example.test/tfs',
      keep_pat: true,
    })
  })

  it('确认提交后遇到 revision_conflict：待确认被撤销，草稿保留用户输入；再次保存按新基线重新发起确认', async () => {
    const fake = createFake()
    let n = 0
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      n++
      if (n === 1) return err(409, 'pat_origin_change', 'origin 已变化')
      if (n === 2) {
        fake.state.ado = extLibA(9, '外部名', 'https://ext.example.test')
        return err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 9 })
      }
      return err(409, 'pat_origin_change', 'origin 已变化')
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'U名')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    await click(b, 'origin-keep')

    expect(byTid(b, 'pat-origin-change').exists()).toBe(false)
    expect(byTid(b, 'settings-notice').text()).toContain('已合并最新内容')
    expect(valueOf(b, 'library 名称')).toBe('U名')
    expect(valueOf(b, 'library 地址')).toBe('https://other.example.test/tfs')

    await click(b, 'library-save')
    expect(patchesOf(fake)[2]!.body).toEqual({
      revision: 9,
      name: 'U名',
      base_url: 'https://other.example.test/tfs',
      keep_pat: false,
    })
    expect(byTid(b, 'pat-origin-change').exists()).toBe(true)
  })

  it('replace 分支的 PAT 不足 8 字符：不发请求、提示最小长度，待确认与输入都保留', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      const body = c.body as { pat?: string }
      return body.pat ? json({ revision: 6 }) : err(409, 'pat_origin_change', 'origin 已变化')
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test')
    await click(b, 'library-save')
    const before = patchesOf(fake).length
    await pwd(b).setValue('1234567')
    await click(b, 'origin-replace')
    expect(byTid(b, 'library-local-error').text()).toContain('PAT 至少 8 个字符')
    expect(patchesOf(fake)).toHaveLength(before)
    expect(byTid(b, 'pat-origin-change').exists()).toBe(true)
    expect(pwdValue(b)).toBe('1234567')
  })
})

describe('store_unavailable 之后的只读与恢复', () => {
  it('首次加载即为 readonly_error：只读错误态可见，新建/保存/PAT/清理入口全部停用', async () => {
    const fake = createFake()
    fake.state.settings = makeSettings({ store_state: 'readonly_error', store_error: '磁盘只读' })
    const b = await open(fake)
    expect(byTid(b, 'store-error').exists()).toBe(true)
    expect(isDisabled(b, 'library-add')).toBe(true)
    expect(isDisabled(b, 'project-add')).toBe(true)
    await click(b, 'library-row-lib:a')
    expect(isDisabled(b, 'library-save')).toBe(true)
    expect(isDisabled(b, 'pat-save')).toBe(true)
    expect(isDisabled(b, 'pat-delete')).toBe(true)
    await selectTab(b, '凭据')
    expect(
      b.wrapper.get('[data-testid="cred-ado_pat:lib:gone"] button').attributes('disabled'),
    ).toBeDefined()
  })

  it('503 store_unavailable 后刷新确认为只读：写入口停用，且不再发出写请求', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      fake.state.settings = makeSettings({ store_state: 'readonly_error', store_error: '损坏' })
      return err(503, 'store_unavailable', '存储不可用')
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(isDisabled(b, 'library-save')).toBe(true)
    expect(isDisabled(b, 'pat-save')).toBe(true)
    expect(byTid(b, 'store-error').exists()).toBe(true)
    const sent = patchesOf(fake).length
    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(sent)
  })

  it('疑似缺陷：503 后刷新确认为只读，之后存储经 settings.changed 恢复为 ok，应恢复可写（用户可再次保存）', async () => {
    const fake = createFake()
    let first = true
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH' || !first) return undefined
      first = false
      fake.state.settings = makeSettings({ store_state: 'readonly_error', store_error: '损坏' })
      return err(503, 'store_unavailable', '存储不可用')
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(isDisabled(b, 'library-save')).toBe(true)

    fake.state.settings = makeSettings({ revision: 6 })
    b.sock.emit(env('settings.changed', { revision: 6 }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()

    expect(byTid(b, 'store-error').exists()).toBe(false)
    expect(isDisabled(b, 'library-save')).toBe(false)
    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(2)
  })

  it('疑似缺陷：503 后刷新失败（overview 500），存储随后经 settings.changed 确认 ok，应恢复可写', async () => {
    const fake = createFake()
    let broken = false
    fake.handlers.push((c) => {
      if (c.method === 'PATCH' && !broken) {
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

    broken = false
    b.sock.emit(env('settings.changed', { revision: 6 }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()
    expect(isDisabled(b, 'library-save')).toBe(false)
  })
})

describe('warnings 展示', () => {
  it('library 新建响应含多条 warnings：warn 级别、列出全部、无成功文案，凭据列表随即刷新', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'POST' && c.path === '/api/ado/libraries'
        ? json({ revision: 6, id: 'lib:new', warnings: ['警告一', '警告二'] })
        : undefined,
    )
    const b = await open(fake)
    const credsBefore = fake.to('GET', '/api/credentials').length
    await click(b, 'library-add')
    await typeInto(b, 'library 名称', '新库')
    await typeInto(b, 'library 地址', 'https://n.example.test')
    await click(b, 'library-create')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(warnItems(b)).toEqual(['警告一', '警告二'])
    expect(byTid(b, 'settings-notice').text()).not.toContain('已新建 library')
    expect(fake.to('GET', '/api/credentials').length).toBeGreaterThan(credsBefore)
  })

  it('library 保存（PATCH）单条 warning：warn 列表仅一项，成功文案不出现', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH' ? json({ revision: 6, warnings: ['地址将使用明文 HTTP'] }) : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(warnItems(b)).toEqual(['地址将使用明文 HTTP'])
    expect(byTid(b, 'settings-notice').text()).not.toContain('已保存 library')
  })

  it('保存 PAT（PUT）响应含 warnings：显示警告而非“PAT 已保存”，且 PAT 输入仍清空', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PUT' && c.path.endsWith('/pat')
        ? json({ revision: 6, warnings: ['Keychain 写入较慢'] })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:b')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'pat-save')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(warnItems(b)).toEqual(['Keychain 写入较慢'])
    expect(byTid(b, 'settings-notice').text()).not.toContain('PAT 已保存')
    expect(pwdValue(b)).toBe('')
  })

  it('删除 PAT（DELETE）响应含 warnings：显示警告', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'DELETE' && c.path.endsWith('/pat')
        ? json({ revision: 6, warnings: ['旧凭据条目保留为待删除'] })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await click(b, 'pat-delete')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(warnItems(b)).toEqual(['旧凭据条目保留为待删除'])
    expect(byTid(b, 'settings-notice').text()).not.toContain('PAT 已删除')
  })

  it('project 新建响应含 warnings：warn 列表渲染，不显示“已新建 project”', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'POST' && c.path === '/api/ado/projects'
        ? json({ revision: 6, warnings: ['远端大小写与输入不一致'] })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'project-add')
    await typeInto(b, 'collection', 'Col2')
    await typeInto(b, 'project 名称', 'P2')
    await click(b, 'project-save')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(warnItems(b)).toEqual(['远端大小写与输入不一致'])
    expect(byTid(b, 'settings-notice').text()).not.toContain('已新建 project')
  })

  it('project 保存（PATCH）响应含 warnings：显示警告而非“已保存 project”', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH' && c.path.startsWith('/api/ado/projects/')
        ? json({ revision: 6, warnings: ['collection 已变更，旧任务引用未更新'] })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await typeInto(b, 'collection', 'MyCol')
    await click(b, 'project-save')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(warnItems(b)).toEqual(['collection 已变更，旧任务引用未更新'])
    expect(byTid(b, 'settings-notice').text()).not.toContain('已保存 project')
  })

  it('清理凭据（DELETE）响应含 warnings：显示警告，且凭据行随刷新消失', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method !== 'DELETE' || !c.path.startsWith('/api/credentials/')) return undefined
      fake.state.creds = fake.state.creds.filter((x) => x.account !== 'ado_pat:lib:gone')
      return json({ revision: 6, warnings: ['Keychain 残留，需手动清理'] })
    })
    const b = await open(fake, '凭据')
    await b.wrapper.get('[data-testid="cred-ado_pat:lib:gone"] button').trigger('click')
    await flushPromises()
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(warnItems(b)).toEqual(['Keychain 残留，需手动清理'])
    expect(byTid(b, 'cred-ado_pat:lib:gone').exists()).toBe(false)
  })

  it('导入执行（execute）响应含 warnings：显示警告而非“导入完成”', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.path === '/api/settings/import/execute'
        ? json({ revision: 7, warnings: ['tasks.yaml 已迁移，旧文件保留'] })
        : undefined,
    )
    const b = await open(fake, '导入')
    await click(b, 'import-preview')
    await click(b, 'import-confirm')
    await click(b, 'import-execute')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(warnItems(b)).toEqual(['tasks.yaml 已迁移，旧文件保留'])
    expect(byTid(b, 'settings-notice').text()).not.toContain('导入完成')
  })

  it('导入预览（previewImport）返回的 warnings 不触发任何通知', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.path === '/api/settings/import/preview'
        ? json(makePreview({ warnings: ['预览警告一', '预览警告二'] }))
        : undefined,
    )
    const b = await open(fake, '导入')
    await click(b, 'import-preview')
    expect(byTid(b, 'settings-notice').exists()).toBe(false)
    expect(byTid(b, 'notice-warnings').exists()).toBe(false)
  })

  it('warnings 过滤：非字符串与空串被忽略，只列出有效文本', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH'
        ? json({ revision: 6, warnings: ['', 42, '有效一', null, '有效二'] })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(warnItems(b)).toEqual(['有效一', '有效二'])
  })

  it('warnings 为空数组或全部无效时按成功处理：显示成功文案且无警告列表', async () => {
    const fake = createFake()
    const bodies: unknown[] = [[], ['', 7]]
    fake.handlers.push((c) =>
      c.method === 'PATCH' ? json({ revision: 6, warnings: bodies.shift() }) : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('ok')
    expect(byTid(b, 'settings-notice').text()).toContain('已保存 library')
    expect(byTid(b, 'notice-warnings').exists()).toBe(false)

    await typeInto(b, 'library 名称', 'Y')
    await click(b, 'library-save')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('ok')
    expect(byTid(b, 'notice-warnings').exists()).toBe(false)
  })
})

describe('写操作 UX 边界', () => {
  it('写操作进行中切换到另一个写操作（删除 PAT）：提示“操作进行中”，且不发出第二个请求', async () => {
    const fake = createFake()
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    fake.handlers.push(async (c) => {
      if (c.method === 'PUT') {
        await gate
        return json({ revision: 6 })
      }
      return undefined
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await pwd(b).setValue(FAKE_PAT)
    const p1 = byTid(b, 'pat-save').trigger('click')
    const p2 = byTid(b, 'pat-delete').trigger('click')
    await Promise.all([p1, p2])
    await flushPromises()
    expect(byTid(b, 'settings-notice').text()).toContain('操作进行中，请稍候')
    expect(fake.calls.filter((c) => c.method === 'DELETE')).toHaveLength(0)
    release()
    await flushPromises()
    expect(puts(fake)).toHaveLength(1)
    expect(fake.calls.filter((c) => c.method === 'DELETE')).toHaveLength(0)
  })

  it('测试连接未填 PAT 时允许发起且请求体不含 pat 键（PAT 最小长度只约束输入的 PAT）', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.path.endsWith('/test')
        ? json({ ok: true, category: 'ok', http_status: 200, message: 'ok' })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, '测试用 collection', 'Col')
    await click(b, 'library-test')
    const t = fake.calls.find((c) => c.path.endsWith('/test'))!
    expect(t.body).toEqual({ collection: 'Col' })
    expect(byTid(b, 'test-result').exists()).toBe(true)
  })

  it('新建 library 未填 PAT：请求体不含 pat 键，成功后不出现 PAT 相关错误', async () => {
    const fake = createFake()
    const b = await open(fake)
    await click(b, 'library-add')
    await typeInto(b, 'library 名称', '无密库')
    await typeInto(b, 'library 地址', 'https://n.example.test')
    await click(b, 'library-create')
    const post = fake.to('POST', '/api/ado/libraries')
    expect(post).toHaveLength(1)
    expect(post[0]!.body).toEqual({
      revision: 5,
      name: '无密库',
      base_url: 'https://n.example.test',
    })
    expect(byTid(b, 'library-local-error').exists()).toBe(false)
  })
})
