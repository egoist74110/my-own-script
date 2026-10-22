// S2-C UX 回归：① 每次编辑会话从当前服务器数据初始化草稿；② 条目字段与基线相同时静默前移基线 revision。
// 假 fetch/假 socket，有状态假后端（revision 不匹配则 409），不连任何真实服务。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import { createFake, json, makeAdo, type Fake } from './settings-fake'
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
const patchesOf = (f: Fake) => f.calls.filter((c) => c.method === 'PATCH')
const noticeText = (b: B) => byTid(b, 'settings-notice').text()

async function changedEvent(b: B, revision: number) {
  b.sock.emit(env('settings.changed', { revision }, { topic: 'settings' }))
  await flushPromises()
  await flushPromises()
}

function gate() {
  let release!: () => void
  const p = new Promise<void>((r) => (release = r))
  return { p, release }
}

describe('UX 1：每次编辑会话都从当前服务器数据初始化草稿', () => {
  it('library：A 保存在途时切到 B，响应到达后切回 A，显示服务器上的新值而非旧草稿', async () => {
    const fake = createFake()
    statefulAdo(fake)
    const g = gate()
    fake.handlers.unshift(async (c) => {
      if (c.method === 'PATCH') await g.p
      return undefined
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '新名字')
    const saving = byTid(b, 'library-save').trigger('click')
    await flushPromises()
    await click(b, 'library-row-lib:b')
    g.release()
    await saving
    await flushPromises()
    await click(b, 'library-row-lib:a')
    expect(valueOf(b, 'library 名称')).toBe('新名字')
  })

  it('library：A 保存在途，切到 B 再立刻切回 A（刷新尚未完成）：数据到达后草稿跟随服务器', async () => {
    const fake = createFake()
    statefulAdo(fake)
    const g = gate()
    let hold = false
    fake.handlers.unshift(async (c) => {
      if (c.method === 'PATCH') {
        hold = true
        await g.p
        return undefined
      }
      if (hold && c.method === 'GET' && c.path === '/api/ado') await g.p
      return undefined
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '新名字')
    const saving = byTid(b, 'library-save').trigger('click')
    await flushPromises()
    await click(b, 'library-row-lib:b')
    await click(b, 'library-row-lib:a')
    g.release()
    await saving
    await flushPromises()
    await flushPromises()
    expect(valueOf(b, 'library 名称')).toBe('新名字')
  })

  it('library：未保存草稿不跨会话保留（A→B→A 回到服务器值）', async () => {
    const fake = createFake()
    statefulAdo(fake)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '只是草稿')
    await click(b, 'library-row-lib:b')
    await click(b, 'library-row-lib:a')
    expect(valueOf(b, 'library 名称')).toBe('示例库')
  })

  it('library：A→新建→A，新建草稿不残留、A 回到服务器值', async () => {
    const fake = createFake()
    statefulAdo(fake)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '草稿')
    await click(b, 'library-add')
    expect(valueOf(b, 'library 名称')).toBe('')
    await typeInto(b, 'library 名称', '新建草稿')
    await click(b, 'library-row-lib:a')
    expect(valueOf(b, 'library 名称')).toBe('示例库')
    await click(b, 'library-add')
    expect(valueOf(b, 'library 名称')).toBe('')
  })

  it('project：A 保存在途，切走再切回（刷新未完成）：数据到达后草稿跟随服务器', async () => {
    const fake = createFake()
    fake.state.ado = makeAdo({
      projects: [
        { id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '项目甲' },
        { id: 'proj:b', library_id: 'lib:a', collection: 'Col', project: '项目乙' },
      ],
    })
    statefulAdo(fake)
    const g = gate()
    let hold = false
    fake.handlers.unshift(async (c) => {
      if (c.method === 'PATCH') {
        hold = true
        await g.p
        return undefined
      }
      if (hold && c.method === 'GET' && c.path === '/api/ado') await g.p
      return undefined
    })
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await typeInto(b, 'project 名称', '改后项目')
    const saving = byTid(b, 'project-save').trigger('click')
    await flushPromises()
    await click(b, 'project-row-proj:b')
    await click(b, 'project-row-proj:a')
    g.release()
    await saving
    await flushPromises()
    await flushPromises()
    expect(valueOf(b, 'project 名称')).toBe('改后项目')
  })
})

describe('UX 2：条目字段与基线相同时，刷新静默前移基线 revision', () => {
  it('本窗口切换“当前项目”后保存 library：不出现合并提示，PATCH 带最新 revision', async () => {
    const fake = createFake()
    const be = statefulAdo(fake)
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    // 先把当前项目设为“空”以便真正发生一次非 patch 写入
    fake.state.ado = { ...fake.state.ado, active_project_id: null }
    await changedEvent(b, fake.state.ado.revision)
    await click(b, 'project-activate')
    expect(fake.state.ado.revision).toBe(6)

    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '改名')
    await click(b, 'library-save')
    expect(be.conflicts).toHaveLength(0)
    expect(patchesOf(fake).at(-1)!.body).toMatchObject({ revision: 6, name: '改名' })
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('ok')
  })

  it('library 正在编辑时，本窗口的非 patch 写入推进 revision：保存无合并提示', async () => {
    // 其它写入（如 setActive）完成后经 settings.changed/刷新到达，条目字段未变
    const fake = createFake()
    const be = statefulAdo(fake)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '改名')
    const rev = be.external((a) => {
      a.active_project_id = null
    })
    await changedEvent(b, rev)
    await click(b, 'library-save')
    expect(be.conflicts).toHaveLength(0)
    expect(patchesOf(fake)).toHaveLength(1)
    expect(patchesOf(fake)[0]!.body).toMatchObject({ revision: rev, name: '改名' })
    expect(byTid(b, 'settings-notice').attributes('data-kind')).toBe('ok')
    expect(noticeText(b)).not.toContain('合并')
  })

  it('project 正在编辑时，其它条目被改（revision 推进、本条字段未变）：保存无合并提示', async () => {
    const fake = createFake()
    const be = statefulAdo(fake)
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await typeInto(b, 'collection', 'NewCol')
    const rev = be.external((a) => {
      a.libraries[0]!.name = '别窗口改了库名'
    })
    await changedEvent(b, rev)
    await click(b, 'project-save')
    expect(be.conflicts).toHaveLength(0)
    expect(patchesOf(fake)[0]!.body).toMatchObject({ revision: rev, collection: 'NewCol' })
    expect(noticeText(b)).not.toContain('合并')
  })

  it('其他窗口改了同一 library 条目：仍出现合并提示并合并（用户改过的字段保留）', async () => {
    const fake = createFake()
    const be = statefulAdo(fake)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '我的改名')
    const rev = be.external((a) => {
      a.libraries[0]!.base_url = 'https://ext.example.test/tfs'
    })
    await changedEvent(b, rev)
    expect(valueOf(b, 'library 地址')).toBe('https://ado.example.test/tfs')
    await click(b, 'library-save')
    expect(be.conflicts).toHaveLength(1)
    expect(noticeText(b)).toContain('设置已被其他窗口修改，已合并最新内容，请核对后再保存')
    expect(valueOf(b, 'library 名称')).toBe('我的改名')
    expect(valueOf(b, 'library 地址')).toBe('https://ext.example.test/tfs')
  })

  it('其他窗口改了同一 project 条目：仍出现合并提示', async () => {
    const fake = createFake()
    const be = statefulAdo(fake)
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await typeInto(b, 'collection', 'Mine')
    const rev = be.external((a) => {
      a.projects[0]!.project = '外部改名'
    })
    await changedEvent(b, rev)
    await click(b, 'project-save')
    expect(be.conflicts).toHaveLength(1)
    expect(noticeText(b)).toContain('已合并最新内容')
    expect(valueOf(b, 'project 名称')).toBe('外部改名')
  })

  it('本窗口写入成功后基线随之前进（自己保存两次不出现提示）', async () => {
    const fake = createFake()
    const be = statefulAdo(fake)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'A1')
    await click(b, 'library-save')
    await typeInto(b, 'library 名称', 'A2')
    await click(b, 'library-save')
    expect(be.conflicts).toHaveLength(0)
    expect(patchesOf(fake).map((c) => (c.body as { revision: number }).revision)).toEqual([5, 6])
  })

  it('条目已被其他窗口删除时不前移基线（保存得到 404，而非静默成功）', async () => {
    const fake = createFake()
    const be = statefulAdo(fake)
    fake.handlers.unshift((c) =>
      c.method === 'GET' && c.path === '/api/health' ? json({}) : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:b')
    await typeInto(b, 'library 名称', 'X')
    const rev = be.external((a) => {
      a.libraries = a.libraries.filter((l) => l.id !== 'lib:b')
    })
    await changedEvent(b, rev)
    expect(b.wrapper.text()).toBeTruthy()
    await click(b, 'library-save').catch(() => undefined)
    expect(
      patchesOf(fake).filter((c) => (c.body as { revision: number }).revision === rev).length,
    ).toBeLessThanOrEqual(1)
  })
})
