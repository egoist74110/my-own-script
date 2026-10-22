// S2-E1（CR-S2C-001）：刷新落定时，用户已改的字段若服务器上也与基线不同，不得 adopt/前移基线，
// 使下一次保存得到 409 并走合并提示。假 fetch/假 socket，有状态假后端。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import { createFake, makeAdo, type Fake } from './settings-fake'
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

async function open(fake: Fake, tab: string) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  const t = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith(tab))!
  await t.trigger('mousedown')
  await flushPromises()
  return b
}
type B = Awaited<ReturnType<typeof open>>
async function click(b: B, id: string) {
  await b.wrapper.get(`[data-testid="${id}"]`).trigger('click')
  await flushPromises()
}
const field = (b: B, label: string) =>
  b.wrapper
    .findAll('label.text-input')
    .find((l) => l.get('.sr-only').text() === label)!
    .get('input')

/** 先让 GET /api/ado 在途（settings.changed 触发刷新并挂起），返回放行函数。 */
function holdRefresh(fake: Fake) {
  let on = false
  let release!: () => void
  const p = new Promise<void>((r) => (release = r))
  fake.handlers.unshift(async (c) => {
    if (on && c.method === 'GET' && c.path === '/api/ado') await p
    return undefined
  })
  return {
    start: async (b: B) => {
      on = true
      b.sock.emit(env('settings.changed', { revision: 99 }, { topic: 'settings' }))
      await flushPromises()
    },
    release: async () => {
      release()
      await flushPromises()
      await flushPromises()
    },
  }
}

const patches = (f: Fake) => f.calls.filter((c) => c.method === 'PATCH')

describe('CR-S2C-001：刷新落定不得吞掉同字段的外部修改', () => {
  it('library：刷新期间开始编辑并改名称，刷新返回他人改了同一字段 -> 保存带旧 revision，得 409 并出现合并提示', async () => {
    const fake = createFake()
    const be = statefulAdo(fake)
    const b = await open(fake, 'ADO 连接')
    const h = holdRefresh(fake)
    await h.start(b)
    await click(b, 'library-row-lib:a')
    await field(b, 'library 名称').setValue('我的名称')
    be.external((a) => {
      a.libraries[0]!.name = '他人新名称'
    })
    await h.release()
    await click(b, 'library-save')
    expect(patches(fake)[0]!.body).toMatchObject({ revision: 5, name: '我的名称' })
    expect(be.conflicts).toHaveLength(1)
    expect(b.wrapper.get('[data-testid="settings-notice"]').text()).toContain('已合并最新内容')
    expect((field(b, 'library 名称').element as HTMLInputElement).value).toBe('我的名称')
  })

  it('project：同上（project 名称）', async () => {
    const fake = createFake()
    const be = statefulAdo(fake)
    const b = await open(fake, 'ADO 连接')
    const h = holdRefresh(fake)
    await h.start(b)
    await click(b, 'project-row-proj:a')
    await field(b, 'project 名称').setValue('我的项目')
    be.external((a) => {
      a.projects[0]!.project = '他人项目'
    })
    await h.release()
    await click(b, 'project-save')
    expect(patches(fake)[0]!.body).toMatchObject({ revision: 5, project: '我的项目' })
    expect(be.conflicts).toHaveLength(1)
    expect(b.wrapper.get('[data-testid="settings-notice"]').text()).toContain('已合并最新内容')
  })

  it('本地仓库：同上（仓库名称）', async () => {
    const fake = createFake()
    fake.state.ado = makeAdo({
      local_repos: [
        { id: 'repo:1', name: '旧名称', path: '/work/main', exists: true, warnings: [] },
      ],
    })
    const be = statefulAdo(fake)
    const b = await open(fake, '本地仓库')
    const h = holdRefresh(fake)
    await h.start(b)
    await click(b, 'repo-row-repo:1')
    await field(b, '仓库名称').setValue('我的名称')
    be.external((a) => {
      a.local_repos[0]!.name = '他人新名称'
    })
    await h.release()
    await click(b, 'repo-save')
    expect(patches(fake)[0]!.body).toMatchObject({ revision: 5, name: '我的名称' })
    expect(be.conflicts).toHaveLength(1)
    expect(b.wrapper.get('[data-testid="settings-notice"]').text()).toContain('已合并最新内容')
  })

  it('护栏：用户改的是 name，他人只改了另一个字段（路径）-> 仍 adopt：路径跟随服务器，保存带新 revision 无 409', async () => {
    const fake = createFake()
    fake.state.ado = makeAdo({
      local_repos: [
        { id: 'repo:1', name: '旧名称', path: '/work/main', exists: true, warnings: [] },
      ],
    })
    const be = statefulAdo(fake)
    const b = await open(fake, '本地仓库')
    const h = holdRefresh(fake)
    await h.start(b)
    await click(b, 'repo-row-repo:1')
    await field(b, '仓库名称').setValue('我的名称')
    be.external((a) => {
      a.local_repos[0]!.path = '/ext/path'
    })
    await h.release()
    expect((field(b, '仓库路径').element as HTMLInputElement).value).toBe('/ext/path')
    await click(b, 'repo-save')
    expect(be.conflicts).toHaveLength(0)
    expect(patches(fake)[0]!.body).toEqual({ revision: 6, name: '我的名称' })
  })
})
