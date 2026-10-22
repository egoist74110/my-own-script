// S2-C：设置页「本地仓库」页签。假 fetch/假 socket，有状态假后端，不连任何真实服务。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import { createFake, err, json, makeAdo, makeSettings, type Fake } from './settings-fake'
import { statefulAdo } from './s2c-backend'

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

const REPOS = [
  { id: 'repo:1', name: '主仓库', path: '/work/main', exists: true, warnings: [] },
  {
    id: 'repo:2',
    name: '旧仓库',
    path: 'relative/old',
    exists: false,
    warnings: ['存量仓库路径不符合新规则，请修改'],
  },
]

function seeded() {
  const fake = createFake()
  fake.state.ado = makeAdo({ local_repos: structuredClone(REPOS) })
  const be = statefulAdo(fake)
  return { fake, be }
}

async function open(fake: Fake) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  const t = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith('本地仓库'))!
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
const calls = (f: Fake, m: string) =>
  f.calls.filter((c) => c.method === m && c.path.startsWith('/api/ado/local-repos'))
const isDisabled = (b: B, id: string) => byTid(b, id).attributes('disabled') !== undefined

describe('本地仓库页签', () => {
  it('列表显示名称、路径、存在与否与存量不合规警告；页签带数量', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    const tab = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith('本地仓库'))!
    expect(tab.text()).toContain('2')
    const t = byTid(b, 'repo-table').text()
    expect(t).toContain('主仓库')
    expect(t).toContain('/work/main')
    expect(byTid(b, 'repo-exists-repo:1').text()).toBe('存在')
    expect(byTid(b, 'repo-exists-repo:2').text()).toBe('目录不存在')
    expect(byTid(b, 'repo-warn-repo:1').text()).toBe('')
    expect(byTid(b, 'repo-warn-repo:2').text()).toContain('不符合新规则')
    await click(b, 'repo-row-repo:2')
    expect(byTid(b, 'repo-warnings').text()).toContain('不符合新规则')
  })

  it('空列表给出提示', async () => {
    const fake = createFake()
    const b = await open(fake)
    expect(byTid(b, 'repo-table').text()).toContain('还没有本地仓库')
  })

  it('新建：POST 带 revision/name/path，成功后选中新条目并提示', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-add')
    await typeInto(b, '仓库名称', '  新仓库 ')
    await typeInto(b, '仓库路径', ' /work/new ')
    await click(b, 'repo-save')
    const posts = calls(fake, 'POST')
    expect(posts).toHaveLength(1)
    expect(posts[0]!.body).toEqual({ revision: 5, name: '新仓库', path: '/work/new' })
    expect(byTid(b, 'settings-notice').text()).toContain('已新建本地仓库')
    expect(byTid(b, 'repo-detail').exists()).toBe(true)
    expect(byTid(b, 'repo-table').text()).toContain('/work/new')
  })

  it.each([
    ['相对路径', 'rel/path'],
    ['含 .. 段', '/a/../b'],
    ['含控制字符', '/a/b\u0007c'],
    ['过长', '/' + 'x'.repeat(1030)],
  ])('本地校验（%s）：不发请求，提示不回显输入', async (_n, bad) => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-add')
    await typeInto(b, '仓库名称', 'n')
    await typeInto(b, '仓库路径', bad)
    await click(b, 'repo-save')
    expect(calls(fake, 'POST')).toHaveLength(0)
    const text = byTid(b, 'repo-local-error').text()
    expect(text).toBeTruthy()
    expect(text).not.toContain(bad.slice(0, 8) === '/' + 'x'.repeat(7) ? 'xxxxxxx' : bad)
  })

  it('名称为空：不发请求', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-add')
    await typeInto(b, '仓库路径', '/ok')
    await click(b, 'repo-save')
    expect(calls(fake, 'POST')).toHaveLength(0)
    expect(byTid(b, 'repo-local-error').text()).toContain('名称')
  })

  it('服务端 422：按 S1 方式显示固定文案，不回显输入', async () => {
    const { fake } = seeded()
    fake.handlers.unshift((c) =>
      c.method === 'POST' && c.path === '/api/ado/local-repos'
        ? err(422, 'validation_error', '请求校验失败')
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'repo-add')
    await typeInto(b, '仓库名称', 'SECRET-NAME')
    await typeInto(b, '仓库路径', '/secret/path')
    await click(b, 'repo-save')
    const n = byTid(b, 'settings-notice')
    expect(n.attributes('data-kind')).toBe('error')
    expect(n.text()).toBe('请求校验失败关闭提示')
    expect(n.text()).not.toContain('SECRET')
    // 失败后输入保留，便于修改
    expect(valueOf(b, '仓库名称')).toBe('SECRET-NAME')
  })

  it('修改：只发变更字段 + 基线 revision；成功后基线前进（再保存不 409）', async () => {
    const { fake, be } = seeded()
    const b = await open(fake)
    await click(b, 'repo-row-repo:1')
    await typeInto(b, '仓库路径', '/work/moved')
    await click(b, 'repo-save')
    expect(calls(fake, 'PATCH')[0]!.body).toEqual({ revision: 5, path: '/work/moved' })
    await typeInto(b, '仓库名称', '改名')
    await click(b, 'repo-save')
    expect(calls(fake, 'PATCH')[1]!.body).toEqual({ revision: 6, name: '改名' })
    expect(be.conflicts).toHaveLength(0)
  })

  it('修改：没有变化不发请求', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-row-repo:1')
    await click(b, 'repo-save')
    expect(calls(fake, 'PATCH')).toHaveLength(0)
  })

  it('修存量不合规条目：路径改为合规后警告消失', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-row-repo:2')
    await typeInto(b, '仓库路径', '/work/fixed')
    await click(b, 'repo-save')
    expect(byTid(b, 'repo-warn-repo:2').text()).toBe('')
  })

  it('存量不合规的路径不阻止只改名称：只发 name；改路径时仍按新规则校验', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-row-repo:2')
    await typeInto(b, '仓库名称', '换名')
    await click(b, 'repo-save')
    expect(calls(fake, 'PATCH')[0]!.body).toEqual({ revision: 5, name: '换名' })
    await typeInto(b, '仓库路径', 'still/relative')
    await click(b, 'repo-save')
    expect(calls(fake, 'PATCH')).toHaveLength(1)
    expect(byTid(b, 'repo-local-error').text()).toContain('绝对路径')
  })

  it('其他窗口改了同一仓库：409 后合并，用户改的字段保留', async () => {
    const { fake, be } = seeded()
    const b = await open(fake)
    await click(b, 'repo-row-repo:1')
    await typeInto(b, '仓库名称', '我的名字')
    const rev = be.external((a) => {
      a.local_repos[0]!.path = '/ext/path'
    })
    b.sock.emit(env('settings.changed', { revision: rev }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()
    await click(b, 'repo-save')
    expect(be.conflicts).toHaveLength(1)
    expect(byTid(b, 'settings-notice').text()).toContain('已合并最新内容')
    expect(valueOf(b, '仓库名称')).toBe('我的名字')
    expect(valueOf(b, '仓库路径')).toBe('/ext/path')
    await click(b, 'repo-save')
    expect(calls(fake, 'PATCH')[1]!.body).toEqual({ revision: rev, name: '我的名字' })
  })

  it('其他条目被改（本条字段未变）：基线静默前移，无合并提示', async () => {
    const { fake, be } = seeded()
    const b = await open(fake)
    await click(b, 'repo-row-repo:1')
    await typeInto(b, '仓库名称', '我的名字')
    const rev = be.external((a) => {
      a.local_repos[1]!.name = '别处改的'
    })
    b.sock.emit(env('settings.changed', { revision: rev }, { topic: 'settings' }))
    await flushPromises()
    await flushPromises()
    await click(b, 'repo-save')
    expect(be.conflicts).toHaveLength(0)
    expect(calls(fake, 'PATCH')[0]!.body).toEqual({ revision: rev, name: '我的名字' })
  })

  it('A→B→A：草稿不跨会话保留', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-row-repo:1')
    await typeInto(b, '仓库名称', '草稿')
    await click(b, 'repo-row-repo:2')
    expect(valueOf(b, '仓库名称')).toBe('旧仓库')
    await click(b, 'repo-row-repo:1')
    expect(valueOf(b, '仓库名称')).toBe('主仓库')
    await click(b, 'repo-add')
    expect(valueOf(b, '仓库名称')).toBe('')
  })

  it('删除需二次确认；取消不发请求；确认后 DELETE 带 revision 并关闭检查器', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-row-repo:1')
    await click(b, 'repo-delete')
    expect(calls(fake, 'DELETE')).toHaveLength(0)
    await click(b, 'repo-delete-cancel')
    expect(calls(fake, 'DELETE')).toHaveLength(0)
    await click(b, 'repo-delete')
    await click(b, 'repo-delete-confirm')
    const d = calls(fake, 'DELETE')
    expect(d).toHaveLength(1)
    expect(d[0]!.path).toBe('/api/ado/local-repos/repo%3A1')
    expect(d[0]!.query).toEqual({ revision: '5' })
    expect(byTid(b, 'repo-detail').exists()).toBe(false)
    expect(byTid(b, 'repo-table').text()).not.toContain('主仓库')
  })

  it('写响应带 warnings：显示警告而非成功文案', async () => {
    const { fake } = seeded()
    fake.handlers.unshift((c) =>
      c.method === 'PATCH' && c.path.startsWith('/api/ado/local-repos')
        ? json({ revision: 6, warnings: ['某某警告'] })
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'repo-row-repo:1')
    await typeInto(b, '仓库名称', 'x')
    await click(b, 'repo-save')
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('warn')
    expect(byTid(b, 'notice-warnings').text()).toContain('某某警告')
  })

  it('store_unavailable 之后禁写（新建/保存/删除均停用）', async () => {
    const { fake } = seeded()
    fake.handlers.unshift((c) => {
      if (c.method !== 'PATCH') return undefined
      fake.state.settings = makeSettings({ store_state: 'readonly_error', store_error: 'x' })
      return err(503, 'store_unavailable', '存储不可用')
    })
    const b = await open(fake)
    await click(b, 'repo-row-repo:1')
    await typeInto(b, '仓库名称', 'x')
    await click(b, 'repo-save')
    expect(isDisabled(b, 'repo-save')).toBe(true)
    expect(isDisabled(b, 'repo-add')).toBe(true)
    expect(isDisabled(b, 'repo-delete')).toBe(true)
    const el = byTid(b, 'repo-save').element as HTMLButtonElement
    el.removeAttribute('disabled')
    el.click()
    await flushPromises()
    expect(calls(fake, 'PATCH')).toHaveLength(1)
  })

  it('键盘：行可聚焦，Enter 打开详情', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    const row = byTid(b, 'repo-row-repo:1')
    expect(row.attributes('tabindex')).toBe('0')
    await row.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(byTid(b, 'repo-detail').exists()).toBe(true)
    expect(valueOf(b, '仓库路径')).toBe('/work/main')
  })

  it('路径输入是纯文本框，没有文件选择控件', async () => {
    const { fake } = seeded()
    const b = await open(fake)
    await click(b, 'repo-add')
    expect(b.wrapper.find('input[type=file]').exists()).toBe(false)
    expect(field(b, '仓库路径').attributes('type')).toBe('text')
  })
})
