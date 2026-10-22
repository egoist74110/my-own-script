// S1-G：设置页审计第二轮收尾回归（CR-S1B-005、CR-S1B-003 剩余）。假 fetch/假 socket，不连任何真实服务。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { FAKE_PAT, createFake, err, json, makeAdo, type Fake } from './settings-fake'

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
const isDisabled = (b: B, id: string) => byTid(b, id).attributes('disabled') !== undefined

/** 两个 library 都带 project，便于切换；返回可手动放行的 PATCH 闸门。 */
function twoLibs(fake: Fake) {
  fake.state.ado = makeAdo({
    projects: [
      { id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '项目甲' },
      { id: 'proj:b', library_id: 'lib:b', collection: 'ColB', project: '项目乙' },
    ],
  })
}
function delayedPatch(fake: Fake, first: () => Response) {
  const pending: { release: () => void }[] = []
  let n = 0
  fake.handlers.push((c) => {
    if (c.method !== 'PATCH') return undefined
    n++
    if (n > 1) return json({ revision: 20 + n })
    return new Promise<Response>((resolve) => {
      pending.push({ release: () => resolve(first()) })
    })
  })
  return pending
}

describe('CR-S1B-005：跨条目延迟响应不得污染切换后的条目', () => {
  it('A 保存地址期间切到 B，A 延迟返回 pat_origin_change：B 无确认框；确认请求（若出现）永不发往 B', async () => {
    const fake = createFake()
    const gate = delayedPatch(fake, () => err(409, 'pat_origin_change', 'origin 已变化'))
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    void byTid(b, 'library-save').trigger('click')
    await flushPromises()
    expect(patchesOf(fake)).toHaveLength(1)

    await click(b, 'library-row-lib:b')
    gate[0]!.release()
    await flushPromises()
    await flushPromises()

    // B 不出现 A 的确认框，输入未被锁定
    expect(byTid(b, 'pat-origin-change').exists()).toBe(false)
    expect(field(b, 'library 地址').attributes('disabled')).toBeUndefined()
    expect(valueOf(b, 'library 地址')).toBe('http://plain.example.test')

    // B 的合法草稿：请求体只含 B 的改动，目标是 B
    await typeInto(b, 'library 名称', 'B 改名')
    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(2)
    expect(patchesOf(fake)[1]!.path).toBe('/api/ado/libraries/lib%3Ab')
    expect(patchesOf(fake)[1]!.body).toEqual({ revision: 5, name: 'B 改名', keep_pat: false })
  })

  it('A 保存被冻结（pending）后再切到 B 又切回 A：旧会话的确认对象已清除', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH' && !(c.body as { keep_pat?: boolean }).keep_pat
        ? err(409, 'pat_origin_change', 'origin 已变化')
        : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    expect(byTid(b, 'pat-origin-change').exists()).toBe(true)
    await click(b, 'library-row-lib:b')
    expect(byTid(b, 'pat-origin-change').exists()).toBe(false)
  })

  it('A 的确认请求在途时切到 B：确认请求发往 A（冻结 id），其成功不推进 B 的基线', async () => {
    const fake = createFake()
    let release!: () => void
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      const body = c.body as { keep_pat?: boolean; pat?: string }
      if (!body.keep_pat && !body.pat) return err(409, 'pat_origin_change', 'origin 已变化')
      return new Promise<Response>((resolve) => {
        release = () => resolve(json({ revision: 6 }))
      })
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    void byTid(b, 'origin-keep').trigger('click')
    await flushPromises()
    expect(patchesOf(fake)[1]!.path).toBe('/api/ado/libraries/lib%3Aa')

    await click(b, 'library-row-lib:b')
    release()
    await flushPromises()
    await flushPromises()
    // 响应落地后 B 的 PAT 输入可正常使用（busy 期间被全局禁用，落地后不得被 A 的收尾清空）
    await b.wrapper.get('input[type=password]').setValue(FAKE_PAT)
    expect((b.wrapper.get('input[type=password]').element as HTMLInputElement).value).toBe(FAKE_PAT)

    // B 的基线仍是 revision 5（未被 A 的 revision 6 推进）
    await typeInto(b, 'library 名称', 'B 改名')
    await click(b, 'library-save')
    expect(patchesOf(fake)[2]!.body).toMatchObject({ revision: 5, name: 'B 改名' })
  })

  it('A 保存延迟成功：B 的基线/草稿不受影响，B 的改动照常发出（带 B 的基线 revision）', async () => {
    const fake = createFake()
    const gate = delayedPatch(fake, () => json({ revision: 6 }))
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', '同名')
    void byTid(b, 'library-save').trigger('click')
    await flushPromises()
    await click(b, 'library-row-lib:b')
    await typeInto(b, 'library 名称', '同名') // 与 A 刚保存的值相同：基线被污染时会被误判为「未改」
    gate[0]!.release()
    await flushPromises()
    await flushPromises()
    expect(valueOf(b, 'library 名称')).toBe('同名')
    await click(b, 'library-save')
    expect(patchesOf(fake)).toHaveLength(2)
    const last = patchesOf(fake)[1]!
    expect(last.path).toBe('/api/ado/libraries/lib%3Ab')
    expect(last.body).toMatchObject({ revision: 5, name: '同名' })
  })

  it('A 延迟 409 revision_conflict：不把 A 的服务器值合并进 B 的草稿', async () => {
    const fake = createFake()
    const gate = delayedPatch(fake, () => err(409, 'revision_conflict', '冲突', { revision: 9 }))
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'A 改名')
    void byTid(b, 'library-save').trigger('click')
    await flushPromises()
    await click(b, 'library-row-lib:b')
    gate[0]!.release()
    await flushPromises()
    await flushPromises()
    expect(valueOf(b, 'library 名称')).toBe('无凭据库')
    expect(valueOf(b, 'library 地址')).toBe('http://plain.example.test')
  })

  it('ProjectPanel：A 保存延迟成功后，B 的基线/草稿不受影响', async () => {
    const fake = createFake()
    twoLibs(fake)
    const gate = delayedPatch(fake, () => json({ revision: 6 }))
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await typeInto(b, 'project 名称', '同名')
    void byTid(b, 'project-save').trigger('click')
    await flushPromises()
    await click(b, 'project-row-proj:b')
    await typeInto(b, 'project 名称', '同名')
    gate[0]!.release()
    await flushPromises()
    await flushPromises()
    expect(valueOf(b, 'project 名称')).toBe('同名')
    await click(b, 'project-save')
    expect(patchesOf(fake)).toHaveLength(2)
    const last = patchesOf(fake)[1]!
    expect(last.path).toBe('/api/ado/projects/proj%3Ab')
    expect(last.body).toMatchObject({ revision: 5, project: '同名' })
  })

  it('ProjectPanel：A 延迟 409 revision_conflict 不合并进 B 的草稿', async () => {
    const fake = createFake()
    twoLibs(fake)
    const gate = delayedPatch(fake, () => err(409, 'revision_conflict', '冲突', { revision: 9 }))
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await typeInto(b, 'project 名称', 'A 新名')
    void byTid(b, 'project-save').trigger('click')
    await flushPromises()
    await click(b, 'project-row-proj:b')
    gate[0]!.release()
    await flushPromises()
    await flushPromises()
    expect(valueOf(b, 'project 名称')).toBe('项目乙')
  })
})

describe('CR-S1B-003 剩余：离线期间的 store_unavailable 不得以旧缓存解除禁写', () => {
  it('断线后写请求返回 503：写入口禁用、绕过禁用的 act() 拒绝且不发请求', async () => {
    const fake = createFake()
    const h: { sock?: FakeSocket } = {}
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      h.sock?.drop() // 先断线（查询不可执行）再返回 503
      return err(503, 'store_unavailable', '存储不可用')
    })
    const b = await open(fake)
    h.sock = b.sock
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    const getsBefore = fake.to('GET', '/api/settings').length
    await click(b, 'library-save')
    expect(fake.to('GET', '/api/settings').length).toBe(getsBefore) // 离线：刷新未执行
    expect(isDisabled(b, 'library-save')).toBe(true)
    expect(isDisabled(b, 'library-add')).toBe(true)

    const el = byTid(b, 'library-save').element as HTMLButtonElement
    el.removeAttribute('disabled')
    el.click()
    await flushPromises()
    expect(patchesOf(fake)).toHaveLength(1)
    expect(byTid(b, 'settings-notice').text()).toContain('不可写')
  })
})
