// S1-G 独立测试（independent=true）：编辑会话（CR-S1B-005：跨条目/跨会话的写响应与回调不得作用于组件）
// 与 CR-S1B-003 剩余（503 故障标记：只有故障之后发起并完成、store_state=ok 的 overview 才解除禁写）。
// 只用假 fetch（tests/unit/settings-fake.ts）与假 socket；不连任何真实服务。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from '../unit/boot'
import { FakeSocket, hello, resetSeq } from '../unit/helpers'
import {
  FAKE_PAT,
  createFake,
  err,
  json,
  makeAdo,
  makeSettings,
  type Call,
  type Fake,
} from '../unit/settings-fake'

const LA = '/api/ado/libraries/lib%3Aa'
const LB = '/api/ado/libraries/lib%3Ab'
const PA = '/api/ado/projects/proj%3Aa'
const PB = '/api/ado/projects/proj%3Ab'

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

const settle = async () => {
  await flushPromises()
  await flushPromises()
}

async function open(fake: Fake) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await settle()
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
const isDisabled = (b: B, id: string) => byTid(b, id).attributes('disabled') !== undefined
const selected = (b: B, id: string) => byTid(b, id).attributes('data-selected')

const calls = (f: Fake, method: string) => f.calls.filter((c) => c.method === method)
const body = (c: Call) => (c.body ?? {}) as Record<string, unknown>
const gets = (f: Fake, path: string) => f.calls.filter((c) => c.method === 'GET' && c.path === path)

/** 挂起第一个命中的请求，由测试决定何时、以何种响应返回。 */
interface Hold {
  hit: boolean
  release: (r: Response) => void
}
function hold(fake: Fake, match: (c: Call) => boolean): Hold {
  const g: Hold = {
    hit: false,
    release: () => {
      throw new Error('请求尚未挂起')
    },
  }
  fake.handlers.push((c) => {
    if (g.hit || !match(c)) return undefined
    g.hit = true
    return new Promise<Response>((resolve) => {
      g.release = resolve
    })
  })
  return g
}

/** 只让 PATCH 带 keep_pat/pat 以外的字段时报 origin 变更（与 S1-G 自测一致）。 */
const originChange = (c: Call) =>
  c.method === 'PATCH' && !body(c).keep_pat && !body(c).pat
    ? err(409, 'pat_origin_change', 'origin 已变化')
    : undefined

/** 与 makeAdo 相同但 lib:a 名称/地址与 revision 可指定。 */
function adoWith(revision: number, patch: { name?: string; base_url?: string } = {}) {
  const ado = makeAdo({ revision })
  Object.assign(ado.libraries[0]!, patch)
  return ado
}

/** 两个 library 各带一个 project，便于在条目间切换。 */
function twoLibs(fake: Fake) {
  fake.state.ado = makeAdo({
    projects: [
      { id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '项目甲' },
      { id: 'proj:b', library_id: 'lib:b', collection: 'ColB', project: '项目乙' },
    ],
  })
}

type Spies = ReturnType<typeof spyConsole>
function spyConsole() {
  return (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => {}),
  )
}
function expectNoPatLeak(fake: Fake, spies: Spies) {
  expect(document.body.innerHTML).not.toContain(FAKE_PAT)
  for (const c of fake.calls) {
    expect(c.path).not.toContain(FAKE_PAT)
    expect(Object.values(c.query).join(' ')).not.toContain(FAKE_PAT)
  }
  const logged = spies.flatMap((s) => s.mock.calls).map((a) => a.map(String).join(' '))
  expect(logged.join('\n')).not.toContain(FAKE_PAT)
}

describe('CR-S1B-005 library：A 的写请求在途时切换，响应与回调不得作用于切换后的条目', () => {
  it('L1 A 保存延迟成功：A→B→A 后，旧成功响应不推进切回的 A 的基线（再保存仍以切回时 revision 5 发出）', async () => {
    const fake = createFake()
    const g = hold(fake, (c) => c.method === 'PATCH' && c.path === LA)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'A新名')
    await click(b, 'library-save')
    expect(g.hit).toBe(true)
    await click(b, 'library-row-lib:b')
    await click(b, 'library-row-lib:a')
    expect(valueOf(b, 'library 名称')).toBe('示例库')

    fake.state.ado = adoWith(6, { name: 'A新名' })
    g.release(json({ revision: 6 }))
    await settle()
    // 旧响应不改写切回后的草稿
    expect(valueOf(b, 'library 名称')).toBe('示例库')

    await typeInto(b, 'library 名称', 'A再改')
    await click(b, 'library-save')
    expect(calls(fake, 'PATCH').at(-1)!.path).toBe(LA)
    expect(calls(fake, 'PATCH').at(-1)!.body).toEqual({
      revision: 5,
      name: 'A再改',
      keep_pat: false,
    })
  })

  it('L2 A 的 pat_origin_change 延迟返回：A→B→A 之后无确认框、地址不锁定、草稿不被冻结', async () => {
    const fake = createFake()
    const g = hold(fake, (c) => c.method === 'PATCH' && c.path === LA)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    await click(b, 'library-row-lib:b')
    await click(b, 'library-row-lib:a')
    g.release(err(409, 'pat_origin_change', 'origin 已变化'))
    await settle()
    expect(byTid(b, 'pat-origin-change').exists()).toBe(false)
    expect(field(b, 'library 地址').attributes('disabled')).toBeUndefined()
    expect(valueOf(b, 'library 地址')).toBe('https://ado.example.test/tfs')
    expect(isDisabled(b, 'library-save')).toBe(false)
  })

  it('L3 A 已冻结的 origin 确认：A→B→A 后确认框消失，回到 A 的地址为原值且可重新保存', async () => {
    const fake = createFake()
    fake.handlers.push(originChange)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    expect(byTid(b, 'pat-origin-change').exists()).toBe(true)
    await click(b, 'library-row-lib:b')
    expect(byTid(b, 'pat-origin-change').exists()).toBe(false)
    await click(b, 'library-row-lib:a')
    expect(byTid(b, 'pat-origin-change').exists()).toBe(false)
    expect(valueOf(b, 'library 地址')).toBe('https://ado.example.test/tfs')
    expect(byTid(b, 'origin-keep').exists()).toBe(false)
    expect(isDisabled(b, 'library-save')).toBe(false)
  })

  it('L4 A 的「保留已存 PAT」确认请求在途时切到 B：请求体与路径都属于 A（冻结 id），响应不推进 B 的基线', async () => {
    const fake = createFake()
    fake.handlers.push(originChange)
    const g = hold(fake, (c) => c.method === 'PATCH' && body(c).keep_pat === true)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    await click(b, 'origin-keep')
    expect(g.hit).toBe(true)
    const keep = calls(fake, 'PATCH').at(-1)!
    expect(keep.path).toBe(LA)
    expect(keep.body).toEqual({
      base_url: 'https://other.example.test/tfs',
      keep_pat: true,
      revision: 5,
    })

    await click(b, 'library-row-lib:b')
    fake.state.ado = adoWith(6)
    g.release(json({ revision: 6 }))
    await settle()
    expect(valueOf(b, 'library 名称')).toBe('无凭据库')
    expect(valueOf(b, 'library 地址')).toBe('http://plain.example.test')

    await typeInto(b, 'library 名称', 'B改')
    await click(b, 'library-save')
    expect(calls(fake, 'PATCH').at(-1)!.path).toBe(LB)
    expect(calls(fake, 'PATCH').at(-1)!.body).toEqual({ revision: 5, name: 'B改', keep_pat: false })
  })

  it('L5 A 的「替换 PAT」确认请求在途时切到 B：PAT 只出现在该请求体中；切换后 B 的 PAT 输入为空，且 PAT 不进入 DOM/URL/console', async () => {
    const fake = createFake()
    fake.handlers.push(originChange)
    const spies = spyConsole()
    const g = hold(fake, (c) => c.method === 'PATCH' && body(c).pat !== undefined)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 地址', 'https://other.example.test/tfs')
    await click(b, 'library-save')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'origin-replace')
    expect(g.hit).toBe(true)
    await click(b, 'library-row-lib:b')
    g.release(json({ revision: 6 }))
    await settle()

    expect(calls(fake, 'PATCH').at(-1)!.body).toEqual({
      base_url: 'https://other.example.test/tfs',
      pat: FAKE_PAT,
      keep_pat: false,
      revision: 5,
    })
    expect((pwd(b).element as HTMLInputElement).value).toBe('')
    expectNoPatLeak(fake, spies)
  })

  it('L6 A 的 PUT /pat 在途时切到 B：PAT 保存成功不推进 B 的基线（B 保存仍以 revision 5 发出，冲突时按合并处理）', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH' && c.path === LB && body(c).revision !== 6
        ? err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 6 })
        : undefined,
    )
    const g = hold(fake, (c) => c.method === 'PUT' && c.path === `${LA}/pat`)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'pat-save')
    expect(g.hit).toBe(true)
    await click(b, 'library-row-lib:b')
    fake.state.ado = adoWith(6)
    g.release(json({ revision: 6 }))
    await settle()
    expect(calls(fake, 'PUT')[0]!.body).toEqual({ revision: 5, pat: FAKE_PAT })

    await typeInto(b, 'library 名称', 'B改')
    await click(b, 'library-save')
    expect(calls(fake, 'PATCH').at(-1)!.body).toEqual({ revision: 5, name: 'B改', keep_pat: false })
    expect(byTid(b, 'settings-notice').text()).toContain('已合并最新内容')
    expect(valueOf(b, 'library 名称')).toBe('B改')

    await click(b, 'library-save')
    expect(calls(fake, 'PATCH').at(-1)!.body).toEqual({ revision: 6, name: 'B改', keep_pat: false })
  })

  it('L7 A 的 DELETE /pat 在途时切到 B：删除成功不推进 B 的基线，B 的草稿与 revision 5 保持', async () => {
    const fake = createFake()
    fake.handlers.push((c) =>
      c.method === 'PATCH' && c.path === LB && body(c).revision !== 6
        ? err(409, 'revision_conflict', '配置已被其他写者更新', { revision: 6 })
        : undefined,
    )
    const g = hold(fake, (c) => c.method === 'DELETE' && c.path === `${LA}/pat`)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await click(b, 'pat-delete')
    expect(g.hit).toBe(true)
    await click(b, 'library-row-lib:b')
    fake.state.ado = adoWith(6)
    g.release(json({ revision: 6 }))
    await settle()
    expect(calls(fake, 'DELETE')[0]!.query).toEqual({ revision: '5' })

    await typeInto(b, 'library 名称', 'B改')
    await click(b, 'library-save')
    expect(calls(fake, 'PATCH').at(-1)!.body).toEqual({ revision: 5, name: 'B改', keep_pat: false })
    expect(valueOf(b, 'library 名称')).toBe('B改')
  })

  it('L8 A 的保存延迟返回 revision_conflict：A→B→A 后不合并旧 A 的服务器值，回到的 A 草稿为切回时的值', async () => {
    const fake = createFake()
    const g = hold(fake, (c) => c.method === 'PATCH' && c.path === LA)
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'A改')
    await click(b, 'library-save')
    await click(b, 'library-row-lib:b')
    await click(b, 'library-row-lib:a')

    fake.state.ado = adoWith(9, { name: '外部名' })
    g.release(err(409, 'revision_conflict', '冲突', { revision: 9 }))
    await settle()
    expect(valueOf(b, 'library 名称')).toBe('示例库')
    expect(byTid(b, 'settings-notice').text()).not.toContain('已合并最新内容')
  })

  it('L9 新建 library 的 POST 在途时切到 B：响应返回的新 id 不得强制选中，面板仍为 B，PAT 输入已清空且不泄露', async () => {
    const fake = createFake()
    const spies = spyConsole()
    const g = hold(fake, (c) => c.method === 'POST' && c.path === '/api/ado/libraries')
    const b = await open(fake)
    await click(b, 'library-add')
    await typeInto(b, 'library 名称', 'N库')
    await typeInto(b, 'library 地址', 'https://n.example.test/tfs')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'library-create')
    expect(g.hit).toBe(true)
    await click(b, 'library-row-lib:b')

    fake.state.ado = makeAdo({
      revision: 6,
      libraries: [
        ...fake.state.ado.libraries,
        {
          id: 'lib:new',
          name: 'N库',
          base_url: 'https://n.example.test/tfs',
          credential: { present: true, source: 'manual', state: 'present' },
        },
      ],
    })
    g.release(json({ id: 'lib:new', revision: 6 }))
    await settle()

    expect(byTid(b, 'library-new').exists()).toBe(false)
    expect(byTid(b, 'library-detail').get('h2').text()).toBe('无凭据库')
    expect(selected(b, 'library-row-lib:b')).toBe('true')
    expect(selected(b, 'library-row-lib:new')).not.toBe('true')
    expect((pwd(b).element as HTMLInputElement).value).toBe('')
    expectNoPatLeak(fake, spies)
  })

  it('L10 新建 library 的 POST 在途时切到 A：响应返回的新 id 不得把面板带到新建项，A 的草稿不被覆盖；新建入口在在途期间保持禁用', async () => {
    const fake = createFake()
    const g = hold(fake, (c) => c.method === 'POST' && c.path === '/api/ado/libraries')
    const b = await open(fake)
    await click(b, 'library-add')
    await typeInto(b, 'library 名称', 'N库')
    await typeInto(b, 'library 地址', 'https://n.example.test/tfs')
    await click(b, 'library-create')
    expect(g.hit).toBe(true)
    await click(b, 'library-row-lib:a')
    expect(isDisabled(b, 'library-add')).toBe(true)
    await typeInto(b, 'library 名称', 'A草稿')
    fake.state.ado = makeAdo({
      revision: 6,
      libraries: [
        ...fake.state.ado.libraries,
        {
          id: 'lib:new',
          name: 'N库',
          base_url: 'https://n.example.test/tfs',
          credential: { present: false, source: 'unknown', state: 'missing' },
        },
      ],
    })
    g.release(json({ id: 'lib:new', revision: 6 }))
    await settle()
    expect(byTid(b, 'library-new').exists()).toBe(false)
    expect(byTid(b, 'library-detail').get('h2').text()).toBe('示例库')
    expect(valueOf(b, 'library 名称')).toBe('A草稿')
  })
})

describe('CR-S1B-005 project：同类场景', () => {
  it('P1 A 的保存延迟返回 revision_conflict：A→B→A 后 A 的草稿为切回时的值，不合并旧响应', async () => {
    const fake = createFake()
    twoLibs(fake)
    const g = hold(fake, (c) => c.method === 'PATCH' && c.path === PA)
    const b = await open(fake)
    await click(b, 'project-row-proj:a')
    await typeInto(b, 'project 名称', 'A改')
    await click(b, 'project-save')
    await click(b, 'project-row-proj:b')
    await click(b, 'project-row-proj:a')
    fake.state.ado = makeAdo({
      revision: 9,
      projects: [{ id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '外部项' }],
    })
    g.release(err(409, 'revision_conflict', '冲突', { revision: 9 }))
    await settle()
    expect(valueOf(b, 'project 名称')).toBe('项目甲')
    expect(byTid(b, 'settings-notice').text()).not.toContain('已合并最新内容')
  })

  it('P2 新建 project 的 POST 在途时切到 proj:b：响应的新 id 不得强制选中新建项', async () => {
    const fake = createFake()
    twoLibs(fake)
    const g = hold(fake, (c) => c.method === 'POST' && c.path === '/api/ado/projects')
    const b = await open(fake)
    await click(b, 'project-add')
    await typeInto(b, 'collection', 'ColN')
    await typeInto(b, 'project 名称', 'N项目')
    await click(b, 'project-save')
    expect(g.hit).toBe(true)
    await click(b, 'project-row-proj:b')
    fake.state.ado = makeAdo({
      revision: 6,
      projects: [
        ...fake.state.ado.projects,
        { id: 'proj:new', library_id: 'lib:a', collection: 'ColN', project: 'N项目' },
      ],
    })
    g.release(json({ id: 'proj:new', revision: 6 }))
    await settle()
    expect(byTid(b, 'project-new').exists()).toBe(false)
    expect(byTid(b, 'project-detail').get('h2').text()).toBe('项目乙')
    expect(selected(b, 'project-row-proj:b')).toBe('true')
  })

  it('P3 setActive 的 PUT /active 在途时 proj:b→proj:a→proj:b：切回后 B 的基线仍为 revision 5', async () => {
    const fake = createFake()
    twoLibs(fake)
    const g = hold(fake, (c) => c.method === 'PUT' && c.path === '/api/ado/active')
    const b = await open(fake)
    await click(b, 'project-row-proj:b')
    await click(b, 'project-activate')
    expect(g.hit).toBe(true)
    expect(calls(fake, 'PUT').at(-1)!.body).toEqual({
      revision: 5,
      library_id: 'lib:b',
      project_id: 'proj:b',
    })
    await click(b, 'project-row-proj:a')
    await click(b, 'project-row-proj:b')
    fake.state.ado = makeAdo({ ...fake.state.ado, revision: 6 })
    g.release(json({ revision: 6 }))
    await settle()

    await typeInto(b, 'project 名称', '乙改')
    await click(b, 'project-save')
    expect(calls(fake, 'PATCH').at(-1)!.path).toBe(PB)
    expect(calls(fake, 'PATCH').at(-1)!.body).toEqual({ revision: 5, project: '乙改' })
  })

  it('P4 远端项目获取在途时切换条目，再回到新建：旧的远端列表不得出现在新的新建会话中', async () => {
    const fake = createFake()
    twoLibs(fake)
    const g = hold(fake, (c) => c.method === 'GET' && c.path.endsWith('/remote-projects'))
    const b = await open(fake)
    await click(b, 'project-add')
    await typeInto(b, 'collection', 'ColR')
    await click(b, 'remote-fetch')
    expect(g.hit).toBe(true)
    await click(b, 'project-row-proj:b')
    g.release(json([{ name: '远端甲' }]))
    await settle()
    await click(b, 'project-add')
    expect(byTid(b, 'remote-list').exists()).toBe(false)
    expect(valueOf(b, 'collection')).toBe('')
  })
})

describe('CR-S1B-003 剩余：503 故障标记与解除条件', () => {
  it('F1 503 后刷新返回 store_state=ok：故障之后完成的 overview 解除禁写', async () => {
    const fake = createFake()
    let n = 0
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      n++
      return n === 1 ? err(503, 'store_unavailable', '存储不可用') : undefined
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(gets(fake, '/api/settings').length).toBeGreaterThan(0)
    expect(byTid(b, 'store-error').exists()).toBe(false)
    expect(isDisabled(b, 'library-save')).toBe(false)
    await click(b, 'library-save')
    expect(calls(fake, 'PATCH')).toHaveLength(2)
  })

  it('F2 503 后刷新返回 readonly_error：写入口与 PAT 入口全部保持禁用，强行点击也不发请求', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method === 'PATCH') return err(503, 'store_unavailable', '存储不可用')
      if (c.method === 'GET' && c.path === '/api/settings')
        return json(makeSettings({ store_state: 'readonly_error', store_error: '损坏' }))
      return undefined
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(isDisabled(b, 'library-save')).toBe(true)
    expect(isDisabled(b, 'pat-save')).toBe(true)
    const sent = calls(fake, 'PATCH').length
    ;(byTid(b, 'library-save').element as HTMLButtonElement).removeAttribute('disabled')
    await click(b, 'library-save')
    expect(calls(fake, 'PATCH')).toHaveLength(sent)
  })

  it('F3 503 后刷新请求失败（GET 500）：仍禁写，不以旧缓存解除', async () => {
    const fake = createFake()
    fake.handlers.push((c) => {
      if (c.method === 'PATCH') return err(503, 'store_unavailable', '存储不可用')
      if (c.method === 'GET' && c.path === '/api/settings') return err(500, 'internal', '失败')
      return undefined
    })
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
    expect(isDisabled(b, 'library-save')).toBe(true)
    expect(isDisabled(b, 'library-add')).toBe(true)
  })

  it('F4 PAT 保存收到 503 后：PAT 输入被清空，且 PAT 不出现在 DOM、请求 URL/查询或 console 中', async () => {
    const fake = createFake()
    const spies = spyConsole()
    fake.handlers.push((c) =>
      c.method === 'PUT' ? err(503, 'store_unavailable', '存储不可用') : undefined,
    )
    const b = await open(fake)
    await click(b, 'library-row-lib:a')
    await pwd(b).setValue(FAKE_PAT)
    await click(b, 'pat-save')
    expect(calls(fake, 'PUT')).toHaveLength(1)
    expect((pwd(b).element as HTMLInputElement).value).toBe('')
    expectNoPatLeak(fake, spies)
  })
})

describe('CR-S1B-003 剩余：离线（socket.drop）后的禁写与重连恢复', () => {
  /** A 上的 PATCH 先断线再返回 503：返回时查询已不可执行（离线）。 */
  async function dropThen503(fake: Fake, b: B) {
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH') return undefined
      b.sock.drop()
      return err(503, 'store_unavailable', '存储不可用')
    })
    await click(b, 'library-row-lib:a')
    await typeInto(b, 'library 名称', 'X')
    await click(b, 'library-save')
  }
  /** 等待退避后的重连 socket 出现（真实定时器，退避首次 500ms）。 */
  async function waitReconnect(): Promise<FakeSocket> {
    await vi.waitFor(() => expect(FakeSocket.instances.length).toBeGreaterThan(1), {
      timeout: 3000,
    })
    return FakeSocket.last()
  }

  it('O1 离线 503 后禁写；重连 hello 后 overview 在途仍禁写；一次 ok 的 overview 完成后才恢复', async () => {
    const fake = createFake()
    const b = await open(fake)
    await dropThen503(fake, b)
    expect(isDisabled(b, 'library-save')).toBe(true)
    expect(isDisabled(b, 'library-add')).toBe(true)

    const s2 = await waitReconnect()
    expect(s2).not.toBe(b.sock)
    const g = hold(fake, (c) => c.method === 'GET' && c.path === '/api/settings')
    s2.open()
    s2.emit(hello())
    await settle()
    expect(g.hit).toBe(true)
    expect(isDisabled(b, 'library-save')).toBe(true)

    g.release(json(makeSettings()))
    await settle()
    expect(isDisabled(b, 'library-save')).toBe(false)
  })

  it('O2 离线 503 后重连，重连后的 overview 返回 readonly_error：仍禁写', async () => {
    const fake = createFake()
    const b = await open(fake)
    await dropThen503(fake, b)
    const s2 = await waitReconnect()
    fake.handlers.push((c) =>
      c.method === 'GET' && c.path === '/api/settings'
        ? json(makeSettings({ store_state: 'readonly_error', store_error: '损坏' }))
        : undefined,
    )
    s2.open()
    s2.emit(hello())
    await settle()
    expect(isDisabled(b, 'library-save')).toBe(true)
    expect(byTid(b, 'store-error').exists()).toBe(true)
  })

  it('O3 离线 503 后重连，重连后的 overview 请求失败（500）：仍禁写', async () => {
    const fake = createFake()
    const b = await open(fake)
    await dropThen503(fake, b)
    const s2 = await waitReconnect()
    fake.handlers.push((c) =>
      c.method === 'GET' && c.path === '/api/settings' ? err(500, 'internal', '失败') : undefined,
    )
    s2.open()
    s2.emit(hello())
    await settle()
    expect(isDisabled(b, 'library-save')).toBe(true)
  })

  it('O4 离线 503 后重连 socket 已出现但未完成 hello：不发 overview 请求，仍禁写', async () => {
    const fake = createFake()
    const b = await open(fake)
    await dropThen503(fake, b)
    const before = gets(fake, '/api/settings').length
    await waitReconnect()
    await settle()
    expect(gets(fake, '/api/settings')).toHaveLength(before)
    expect(isDisabled(b, 'library-save')).toBe(true)
  })
})
