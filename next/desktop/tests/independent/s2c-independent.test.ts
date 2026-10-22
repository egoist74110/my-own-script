// S2-C 独立测试（independent）：本地仓库页签、编辑会话与基线（UX 1/2）、只读错误态与 S1 规则回归。
// 本文件自带有状态假后端（不依赖 tests/unit/s2c-backend.ts）；只用假 fetch、假 socket，不连任何真实服务，
// 不读真实配置或 Keychain。PAT 用本文件自己的假值。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from '../unit/boot'
import { FakeSocket, env, hello, resetSeq } from '../unit/helpers'
import { createFake, err, json, makeAdo, type Call, type Fake } from '../unit/settings-fake'

type Ado = Fake['state']['ado']

const PAT = 'fake-pat-S2C-INDEP-0042'
const MARK = 'SECRET-MARK'

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
  await flushPromises()
}

/** 两个本地仓库：a 合规；b 为存量不合规（相对路径 + 警告，目录不存在）。revision 5。 */
function seedRepos(fake: Fake) {
  fake.state.ado = makeAdo({
    revision: 5,
    local_repos: [
      { id: 'repo:a', name: '主仓库', path: '/work/main', exists: true, warnings: [] },
      {
        id: 'repo:b',
        name: '旧仓库',
        path: 'relative/old',
        exists: false,
        warnings: ['存量仓库路径不符合新规则，请修改'],
      },
    ],
  })
}

interface RepoBackend {
  /** 到达服务器并被处理的本地仓库写请求（含被拒绝的）。 */
  attempts: Call[]
  conflicts: Call[]
  /** true 时所有本地仓库写请求返回 503 store_unavailable。 */
  unavailable: boolean
  /** 下一次成功写响应附带的 warnings（一次性）。 */
  nextWarnings: string[] | null
  process(c: Call): Response
  /** 另一个窗口改写服务器：revision +1，不发任何事件（由测试决定何时 emit settings.changed）。 */
  external(mutate: (ado: Ado) => void): number
}

function repoBackend(fake: Fake): RepoBackend {
  const be: RepoBackend = {
    attempts: [],
    conflicts: [],
    unavailable: false,
    nextWarnings: null,
    external(mutate) {
      const ado = structuredClone(fake.state.ado)
      mutate(ado)
      ado.revision += 1
      fake.state.ado = ado
      return ado.revision
    },
    process(c) {
      be.attempts.push(c)
      if (be.unavailable) {
        fake.state.settings.store_state = 'readonly_error'
        return err(503, 'store_unavailable', '存储不可用')
      }
      const cur = fake.state.ado
      const rev =
        c.method === 'DELETE'
          ? Number(c.query.revision)
          : (c.body as { revision?: unknown } | undefined)?.revision
      if (rev !== cur.revision) {
        be.conflicts.push(c)
        return err(409, 'revision_conflict', '配置已被其他写者更新', { revision: cur.revision })
      }
      const b = (c.body ?? {}) as { name?: string; path?: string }
      const id = c.path.split('/')[4] ? decodeURIComponent(c.path.split('/')[4]!) : undefined
      if (c.method !== 'DELETE') {
        if (
          b.path !== undefined &&
          (!/^(\/|[A-Za-z]:[\\/])/.test(b.path) || b.path.split(/[\\/]/).includes('..'))
        )
          return err(422, 'validation_error', '路径校验未通过')
        if (b.name !== undefined && cur.local_repos.some((r) => r.name === b.name && r.id !== id))
          return err(422, 'validation_error', '仓库名称已存在')
      }
      const ado = structuredClone(cur)
      let newId: string | undefined
      if (c.method === 'POST') {
        newId = `repo:new-${ado.local_repos.length + 1}`
        ado.local_repos.push({
          id: newId,
          name: b.name!,
          path: b.path!,
          exists: true,
          warnings: [],
        })
      } else if (c.method === 'PATCH') {
        const r = ado.local_repos.find((x) => x.id === id)
        if (!r) return err(404, 'not_found', '不存在')
        if (b.name !== undefined) r.name = b.name
        if (b.path !== undefined) {
          r.path = b.path
          r.exists = true
          r.warnings = []
        }
      } else if (c.method === 'DELETE') {
        if (!ado.local_repos.some((x) => x.id === id)) return err(404, 'not_found', '不存在')
        ado.local_repos = ado.local_repos.filter((x) => x.id !== id)
      }
      ado.revision += 1
      fake.state.ado = ado
      const warnings = be.nextWarnings
      be.nextWarnings = null
      return json({
        revision: ado.revision,
        ...(newId ? { id: newId } : {}),
        ...(warnings ? { warnings } : {}),
      })
    },
  }
  fake.handlers.push((c) =>
    c.path.startsWith('/api/ado/local-repos') && c.method !== 'GET' ? be.process(c) : undefined,
  )
  return be
}

interface Gate {
  hit: boolean
  held: Call | null
  go: () => void
}

/** 第一个命中的写请求在服务器端即时生效，但响应挂起到 go() 才返回（响应晚到）。 */
function holdWrite(fake: Fake, be: RepoBackend, match: (c: Call) => boolean): Gate {
  const g: Gate = {
    hit: false,
    held: null,
    go: () => {
      throw new Error('请求尚未挂起')
    },
  }
  fake.handlers.unshift(async (c) => {
    if (g.hit || !match(c)) return undefined
    g.hit = true
    g.held = c
    const r = be.process(c)
    await new Promise<void>((res) => {
      g.go = () => res()
    })
    return r
  })
  return g
}

/** 第一个 GET /api/ado 挂起；释放时返回释放那一刻的服务器数据（模拟刷新尚未完成）。 */
function holdAdoGet(fake: Fake): Gate {
  const g: Gate = {
    hit: false,
    held: null,
    go: () => {
      throw new Error('请求尚未挂起')
    },
  }
  fake.handlers.unshift(async (c) => {
    if (g.hit || c.method !== 'GET' || c.path !== '/api/ado') return undefined
    g.hit = true
    g.held = c
    await new Promise<void>((res) => {
      g.go = () => res()
    })
    return json(fake.state.ado)
  })
  return g
}

async function openTab(fake: Fake, prefix: string) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await settle()
  const t = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith(prefix))!
  await t.trigger('mousedown')
  await settle()
  return b
}
type B = Awaited<ReturnType<typeof openTab>>

const tid = (b: B, id: string) => b.wrapper.find(`[data-testid="${id}"]`)
async function click(b: B, id: string) {
  await b.wrapper.get(`[data-testid="${id}"]`).trigger('click')
  await settle()
}
const field = (b: B, label: string) =>
  b.wrapper
    .findAll('label.text-input')
    .find((l) => l.get('.sr-only').text() === label)!
    .get('input')
async function fill(b: B, label: string, v: string) {
  await field(b, label).setValue(v)
  await settle()
}
const valueOf = (b: B, label: string) => (field(b, label).element as HTMLInputElement).value
const isDisabled = (b: B, id: string) => tid(b, id).attributes('disabled') !== undefined
function emitChanged(b: B, revision: number) {
  b.sock.emit(env('settings.changed', { revision }, { topic: 'settings' }))
}
const reqs = (fake: Fake, method: string, prefix: string) =>
  fake.calls.filter((c) => c.method === method && c.path.startsWith(prefix))
const bodyOf = (c: Call) => (c.body ?? {}) as Record<string, unknown>
const keysOf = (c: Call) => Object.keys(bodyOf(c)).sort()
const noise = (...xs: string[]) => xs.join('\n')

function consoleSpies() {
  return (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => {}),
  )
}
function storageText(): string {
  const parts: string[] = []
  for (const s of [localStorage, sessionStorage]) {
    for (let i = 0; i < s.length; i++) {
      const k = s.key(i)!
      parts.push(k, s.getItem(k) ?? '')
    }
  }
  return parts.join('\n')
}

// ---------------------------------------------------------------------------
describe('本地仓库：呈现、可达性与键盘（合同 1）', () => {
  it('页签带数量；行显示名称、路径、存在与否、存量警告', async () => {
    const fake = createFake()
    seedRepos(fake)
    const b = await openTab(fake, '本地仓库')
    const tab = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith('本地仓库'))!
    expect(tab.text()).toContain('2')
    expect(tid(b, 'repo-row-repo:a').text()).toContain('主仓库')
    expect(tid(b, 'repo-row-repo:a').text()).toContain('/work/main')
    expect(tid(b, 'repo-exists-repo:a').text()).toBe('存在')
    expect(tid(b, 'repo-exists-repo:b').text()).toBe('目录不存在')
    expect(tid(b, 'repo-warn-repo:b').text()).toContain('存量仓库路径不符合新规则')
    expect(tid(b, 'repo-warn-repo:a').text()).toBe('')
  })

  it('行可聚焦（tabindex=0）；Enter 打开详情并标记选中', async () => {
    const fake = createFake()
    seedRepos(fake)
    const b = await openTab(fake, '本地仓库')
    expect(tid(b, 'repo-row-repo:a').attributes('tabindex')).toBe('0')
    expect(tid(b, 'repo-detail').exists()).toBe(false)
    await tid(b, 'repo-row-repo:a').trigger('keydown', { key: 'Enter' })
    await settle()
    expect(tid(b, 'repo-detail').exists()).toBe(true)
    expect(valueOf(b, '仓库名称')).toBe('主仓库')
    expect(tid(b, 'repo-row-repo:a').attributes('aria-selected')).toBe('true')
  })

  it('存量警告在详情里也以列表形式出现', async () => {
    const fake = createFake()
    seedRepos(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:b')
    expect(tid(b, 'repo-warnings').text()).toContain('存量仓库路径不符合新规则')
  })

  it('控件是原生 button；输入有可访问名称；没有文件选择控件', async () => {
    const fake = createFake()
    seedRepos(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-add')
    expect(tid(b, 'repo-add').element.tagName).toBe('BUTTON')
    expect(tid(b, 'repo-save').element.tagName).toBe('BUTTON')
    expect(field(b, '仓库名称').element).toBeTruthy()
    expect(field(b, '仓库路径').attributes('type') ?? 'text').toBe('text')
    expect(b.wrapper.find('input[type=file]').exists()).toBe(false)
    await click(b, 'repo-row-repo:a')
    expect(tid(b, 'repo-delete').element.tagName).toBe('BUTTON')
  })
})

// ---------------------------------------------------------------------------
describe('本地仓库：本地校验不发请求、错误不回显（合同 1）', () => {
  const BAD_PATHS: Array<[string, string]> = [
    ['相对路径', `${MARK}/rel`],
    ['./ 开头', `./${MARK}`],
    ['.. 段（正斜杠）', `/${MARK}/../x`],
    ['.. 段（反斜杠，盘符）', `C:\\${MARK}\\..\\x`],
    ['控制字符 BEL', `/${MARK}\u0007x`],
    ['控制字符 DEL', `/${MARK}\u007fx`],
    ['超长（1025 字符）', `/${MARK}${'a'.repeat(1025 - 1 - MARK.length)}`],
    ['空白路径', '   '],
  ]

  it.each(BAD_PATHS)('路径非法（%s）：不发 POST/PATCH，错误不回显输入', async (_n, p) => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-add')
    await fill(b, '仓库名称', '新仓库')
    await fill(b, '仓库路径', p)
    await click(b, 'repo-save')
    expect(reqs(fake, 'POST', '/api/ado/local-repos')).toHaveLength(0)
    expect(be.attempts).toHaveLength(0)
    expect(tid(b, 'repo-local-error').exists()).toBe(true)
    expect(tid(b, 'repo-local-error').text()).not.toContain(MARK)
    expect(tid(b, 'settings-notice').exists()).toBe(false)
  })

  it.each([
    ['空名（空白）', '   ', '/work/new'],
    ['超长名（101 字符）', 'n'.repeat(101), '/work/new'],
  ])('名称非法（%s）：不发请求', async (_n, name, path) => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-add')
    await fill(b, '仓库名称', name)
    await fill(b, '仓库路径', path)
    await click(b, 'repo-save')
    expect(be.attempts).toHaveLength(0)
    expect(tid(b, 'repo-local-error').exists()).toBe(true)
  })

  it('修改已有条目时同样不发 PATCH（路径非法）', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库路径', `/${MARK}/../escape`)
    await click(b, 'repo-save')
    expect(be.attempts).toHaveLength(0)
    expect(tid(b, 'repo-local-error').text()).not.toContain(MARK)
  })

  it.each([
    ['带 .. 子串但不是段', '/a/..b'],
    ['段内点号', '/a/b..c'],
    ['Windows 绝对路径', 'C:\\work\\repo'],
    ['含空格的绝对路径', '/Users/me/My Repo'],
  ])('合规路径不被误拒（%s）：发出 POST', async (_n, p) => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-add')
    await fill(b, '仓库名称', '合规仓库')
    await fill(b, '仓库路径', p)
    await click(b, 'repo-save')
    expect(be.attempts).toHaveLength(1)
    expect(tid(b, 'repo-local-error').exists()).toBe(false)
  })
})

// ---------------------------------------------------------------------------
describe('本地仓库：写请求形状、删除确认、服务端错误与警告（合同 1、2）', () => {
  it('新建：POST 体为 {revision, name, path}（已 trim）；成功后选中新条目并提示', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-add')
    await fill(b, '仓库名称', '  新仓库 ')
    await fill(b, '仓库路径', '/work/new ')
    await click(b, 'repo-save')
    const post = reqs(fake, 'POST', '/api/ado/local-repos')
    expect(post).toHaveLength(1)
    expect(post[0]!.body).toEqual({ revision: 5, name: '新仓库', path: '/work/new' })
    expect(tid(b, 'repo-detail').exists()).toBe(true)
    expect(valueOf(b, '仓库名称')).toBe('新仓库')
    expect(tid(b, 'settings-notice').text()).toContain('已新建本地仓库')
  })

  it('修改：PATCH 只含变更字段 + 基线 revision；成功提示', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库路径', '/work/main-moved')
    await click(b, 'repo-save')
    const patch = reqs(fake, 'PATCH', '/api/ado/local-repos/')
    expect(patch).toHaveLength(1)
    expect(keysOf(patch[0]!)).toEqual(['path', 'revision'])
    expect(bodyOf(patch[0]!).revision).toBe(5)
    expect(tid(b, 'settings-notice').text()).toContain('已保存本地仓库')
    expect(tid(b, 'repo-row-repo:a').text()).toContain('/work/main-moved')
  })

  it('没有任何变化时保存不发请求', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await click(b, 'repo-save')
    expect(reqs(fake, 'PATCH', '/api/ado/local-repos/')).toHaveLength(0)
  })

  it('删除：先二次确认；取消不发请求；确认后 DELETE 在 query 带 revision 并关闭检查器', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await click(b, 'repo-delete')
    expect(tid(b, 'repo-delete-confirm').exists()).toBe(true)
    expect(reqs(fake, 'DELETE', '/api/ado/local-repos/')).toHaveLength(0)
    await click(b, 'repo-delete-cancel')
    expect(tid(b, 'repo-delete-confirm').exists()).toBe(false)
    expect(reqs(fake, 'DELETE', '/api/ado/local-repos/')).toHaveLength(0)
    await click(b, 'repo-delete')
    await click(b, 'repo-delete-confirm')
    const del = reqs(fake, 'DELETE', '/api/ado/local-repos/')
    expect(del).toHaveLength(1)
    expect(del[0]!.path).toBe('/api/ado/local-repos/repo%3Aa')
    expect(del[0]!.query).toEqual({ revision: '5' })
    expect(tid(b, 'repo-row-repo:a').exists()).toBe(false)
    expect(tid(b, 'repo-detail').exists()).toBe(false)
  })

  it('服务端 422：按 settings-notice 显示固定文案，不回显输入', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-add')
    await fill(b, '仓库名称', '主仓库')
    await fill(b, '仓库路径', `/${MARK}/ok`)
    await click(b, 'repo-save')
    const n = tid(b, 'settings-notice')
    expect(n.exists()).toBe(true)
    expect(n.attributes('data-kind')).toBe('error')
    expect(n.text()).toContain('仓库名称已存在')
    expect(n.text()).not.toContain(MARK)
    expect(document.body.innerHTML).not.toContain(MARK)
  })

  it('写响应含 warnings：显示警告而非成功文案', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    be.nextWarnings = ['路径仍有待修正']
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库路径', '/work/warned')
    await click(b, 'repo-save')
    const n = tid(b, 'settings-notice')
    expect(n.attributes('data-kind')).toBe('warn')
    expect(tid(b, 'notice-warnings').text()).toContain('路径仍有待修正')
    expect(n.text()).not.toContain('已保存本地仓库')
  })

  it('存量不合规条目：改为合规路径后警告消失', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:b')
    await fill(b, '仓库路径', '/work/fixed')
    await click(b, 'repo-save')
    expect(tid(b, 'repo-warn-repo:b').text()).toBe('')
  })
})

// ---------------------------------------------------------------------------
describe('本地仓库：只读错误态与禁写（合同 1、S1 规则）', () => {
  it('启动时 store 为只读错误态：新建/保存/删除全部禁用', async () => {
    const fake = createFake()
    seedRepos(fake)
    fake.state.settings.store_state = 'readonly_error'
    const b = await openTab(fake, '本地仓库')
    expect(tid(b, 'store-error').exists()).toBe(true)
    expect(isDisabled(b, 'repo-add')).toBe(true)
    await click(b, 'repo-row-repo:a')
    expect(isDisabled(b, 'repo-save')).toBe(true)
    expect(isDisabled(b, 'repo-delete')).toBe(true)
  })

  it('503 store_unavailable 后：store 仍只读时写入口全部禁用，且不再发出写请求', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    be.unavailable = true
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库路径', '/work/x')
    await click(b, 'repo-save')
    expect(be.attempts).toHaveLength(1)
    expect(isDisabled(b, 'repo-add')).toBe(true)
    expect(isDisabled(b, 'repo-save')).toBe(true)
    expect(isDisabled(b, 'repo-delete')).toBe(true)
    await click(b, 'repo-save')
    await click(b, 'repo-add')
    expect(be.attempts).toHaveLength(1)
  })

  it('刷新 overview 失败时保持禁写，即便 store 此前为 ok', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    let failOverview = false
    fake.handlers.unshift((c) =>
      failOverview && c.method === 'GET' && c.path === '/api/settings'
        ? err(500, 'unknown', '内部错误')
        : undefined,
    )
    be.unavailable = true
    const b = await openTab(fake, '本地仓库')
    failOverview = true
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库路径', '/work/x')
    await click(b, 'repo-save')
    expect(isDisabled(b, 'repo-add')).toBe(true)
    expect(isDisabled(b, 'repo-save')).toBe(true)
    // 故障解除前（overview 未成功刷新为 ok）即使服务器恢复也不得放开
    be.unavailable = false
    await click(b, 'repo-add')
    expect(be.attempts).toHaveLength(1)
  })

  it('只有故障之后成功完成且 store_state=ok 的 overview 才重新可写', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    be.unavailable = true
    fake.state.settings.store_state = 'readonly_error'
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库路径', '/work/x')
    await click(b, 'repo-save')
    expect(isDisabled(b, 'repo-add')).toBe(true)
    be.unavailable = false
    fake.state.settings.store_state = 'ok'
    emitChanged(b, 5)
    await settle()
    expect(isDisabled(b, 'repo-add')).toBe(false)
    expect(isDisabled(b, 'repo-save')).toBe(false)
  })
})

// ---------------------------------------------------------------------------
describe('编辑会话与基线：A→B→A、在途响应、刷新中会话（UX 1，合同 2）', () => {
  it('本地仓库 A→B→A：未保存草稿不跨会话保留（回到服务器值）', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库名称', 'DRAFT')
    await click(b, 'repo-row-repo:b')
    await click(b, 'repo-row-repo:a')
    expect(valueOf(b, '仓库名称')).toBe('主仓库')
    expect(valueOf(b, '仓库路径')).toBe('/work/main')
  })

  it('A→新建（有草稿）→A：新建草稿不残留在 A 中', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-add')
    await fill(b, '仓库名称', '草稿名')
    await click(b, 'repo-row-repo:a')
    expect(valueOf(b, '仓库名称')).toBe('主仓库')
  })

  it('再次点击「新建」应开始新的编辑会话：上一次未提交的新建草稿被清空', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-add')
    await fill(b, '仓库名称', '未提交草稿')
    await click(b, 'repo-add')
    expect(valueOf(b, '仓库名称')).toBe('')
  })

  it('A 保存在途时切到 B 再切回 A：响应晚到后 A 显示服务器新值，B 草稿不受影响', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    const g = holdWrite(fake, be, (c) => c.method === 'PATCH' && c.path.endsWith('repo%3Aa'))
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库名称', 'X名')
    await click(b, 'repo-save')
    expect(g.hit).toBe(true)
    await click(b, 'repo-row-repo:b')
    expect(valueOf(b, '仓库名称')).toBe('旧仓库')
    await click(b, 'repo-row-repo:a')
    g.go()
    await settle()
    expect(valueOf(b, '仓库名称')).toBe('X名')
    expect(tid(b, 'settings-notice').text()).toContain('已保存本地仓库')
    await click(b, 'repo-row-repo:b')
    expect(valueOf(b, '仓库名称')).toBe('旧仓库')
    expect(valueOf(b, '仓库路径')).toBe('relative/old')
    expect(reqs(fake, 'PATCH', '/api/ado/local-repos/repo%3Ab')).toHaveLength(0)
  })

  it('A 保存得 409 的响应在切到 B 之后才到达：B 草稿不变，不向 B 发请求', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库名称', 'Y名')
    // 另一个窗口先改了 A 的路径：本窗口的 PATCH（基线 rev 5）到达即 409
    be.external((ado) => {
      ado.local_repos[0]!.path = '/work/elsewhere'
    })
    const g = holdWrite(fake, be, (c) => c.method === 'PATCH' && c.path.endsWith('repo%3Aa'))
    await click(b, 'repo-save')
    expect(g.hit).toBe(true)
    await click(b, 'repo-row-repo:b')
    g.go()
    await settle()
    expect(valueOf(b, '仓库名称')).toBe('旧仓库')
    expect(valueOf(b, '仓库路径')).toBe('relative/old')
    expect(reqs(fake, 'PATCH', '/api/ado/local-repos/repo%3Ab')).toHaveLength(0)
  })

  it('开始会话时数据正在刷新：草稿在刷新落定后跟随服务器（未改动字段）', async () => {
    const fake = createFake()
    seedRepos(fake)
    repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    const g = holdAdoGet(fake)
    fake.state.ado.local_repos[0]!.name = '主仓库（改）'
    fake.state.ado.revision = 6
    emitChanged(b, 6)
    await settle()
    expect(g.hit).toBe(true)
    await click(b, 'repo-row-repo:a')
    expect(valueOf(b, '仓库名称')).toBe('主仓库')
    g.go()
    await settle()
    expect(valueOf(b, '仓库名称')).toBe('主仓库（改）')
  })

  it('开始会话时有写入在途：写入完成并刷新后草稿跟随服务器（未改动字段）', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:b')
    const g = holdWrite(fake, be, (c) => c.method === 'DELETE' && c.path.endsWith('repo%3Ab'))
    await click(b, 'repo-delete')
    await click(b, 'repo-delete-confirm')
    expect(g.hit).toBe(true)
    // 服务器上 A 在删除响应到达前已被另一窗口改名（本窗口缓存仍是旧值）
    fake.state.ado.local_repos[0]!.name = '主仓库（改）'
    fake.state.ado.revision += 1
    await click(b, 'repo-row-repo:a')
    expect(valueOf(b, '仓库名称')).toBe('主仓库')
    g.go()
    await settle()
    expect(valueOf(b, '仓库名称')).toBe('主仓库（改）')
  })

  it('删除在途时切到 B：删除完成后 B 的检查器保持打开，不被关闭', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    const g = holdWrite(fake, be, (c) => c.method === 'DELETE' && c.path.endsWith('repo%3Aa'))
    await click(b, 'repo-delete')
    await click(b, 'repo-delete-confirm')
    expect(g.hit).toBe(true)
    await click(b, 'repo-row-repo:b')
    g.go()
    await settle()
    expect(tid(b, 'repo-row-repo:a').exists()).toBe(false)
    expect(tid(b, 'repo-detail').exists()).toBe(true)
    expect(valueOf(b, '仓库名称')).toBe('旧仓库')
  })

  it('新建在途时切到 A：创建成功的响应不把选中切到新条目', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    const g = holdWrite(fake, be, (c) => c.method === 'POST')
    await click(b, 'repo-add')
    await fill(b, '仓库名称', '新在途')
    await fill(b, '仓库路径', '/work/new-inflight')
    await click(b, 'repo-save')
    expect(g.hit).toBe(true)
    await click(b, 'repo-row-repo:a')
    g.go()
    await settle()
    expect(tid(b, 'repo-row-repo:new-3').exists()).toBe(true)
    expect(valueOf(b, '仓库名称')).toBe('主仓库')
  })

  it('删除其他窗口删掉的正在编辑条目：检查器收起，不自动发出任何请求', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库名称', 'MINE')
    be.external((ado) => {
      ado.local_repos = ado.local_repos.filter((r) => r.id !== 'repo:a')
    })
    emitChanged(b, 6)
    await settle()
    expect(tid(b, 'repo-row-repo:a').exists()).toBe(false)
    expect(tid(b, 'repo-detail').exists()).toBe(false)
    expect(tid(b, 'repo-inspector-empty').exists()).toBe(true)
    expect(be.attempts).toHaveLength(0)
  })
})

describe('编辑会话与基线：刷新、冲突合并、连续保存（UX 2，合同 2、3）', () => {
  it('编辑中多次 settings.changed（其它条目变化）：未保存草稿不被覆盖，保存不 409', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库名称', 'MINE')
    for (const i of [1, 2, 3]) {
      const rev = be.external((ado) => {
        ado.local_repos[1]!.path = `/work/b${i}`
      })
      emitChanged(b, rev)
      await settle()
    }
    expect(valueOf(b, '仓库名称')).toBe('MINE')
    await click(b, 'repo-save')
    expect(be.conflicts).toHaveLength(0)
    const patch = reqs(fake, 'PATCH', '/api/ado/local-repos/repo%3Aa')
    expect(patch).toHaveLength(1)
    expect(bodyOf(patch[0]!).revision).toBe(8)
    expect(tid(b, 'settings-notice').text()).not.toContain('已合并')
    expect(tid(b, 'settings-notice').text()).toContain('已保存本地仓库')
  })

  it('同一条目被其他窗口改了路径：保存 409 后合并；用户改的名称保留，未改的路径取服务器新值', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库名称', 'MINE')
    be.external((ado) => {
      ado.local_repos[0]!.path = '/work/main-2'
    })
    emitChanged(b, 6)
    await settle()
    await click(b, 'repo-save')
    expect(be.conflicts).toHaveLength(1)
    expect(bodyOf(be.conflicts[0]!).revision).toBe(5)
    expect(tid(b, 'settings-notice').get('span').text()).toBe(
      '设置已被其他窗口修改，已合并最新内容，请核对后再保存',
    )
    expect(valueOf(b, '仓库名称')).toBe('MINE')
    expect(valueOf(b, '仓库路径')).toBe('/work/main-2')
    await click(b, 'repo-save')
    const patch = reqs(fake, 'PATCH', '/api/ado/local-repos/repo%3Aa')
    expect(patch).toHaveLength(2)
    expect(keysOf(patch[1]!)).toEqual(['name', 'revision'])
    expect(bodyOf(patch[1]!).revision).toBe(6)
    expect(tid(b, 'settings-notice').text()).toContain('已保存本地仓库')
  })

  it('同一条目被其他窗口“原样”保存（字段相同只推进 revision）：保存不出现合并提示', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    be.external(() => {})
    emitChanged(b, 6)
    await settle()
    await fill(b, '仓库路径', '/work/x')
    await click(b, 'repo-save')
    expect(be.conflicts).toHaveLength(0)
    expect(reqs(fake, 'PATCH', '/api/ado/local-repos/repo%3Aa')[0]!.body).toEqual({
      path: '/work/x',
      revision: 6,
    })
    expect(tid(b, 'settings-notice').text()).not.toContain('已合并')
  })

  it('连续两次保存：第二次带上一次响应的 revision，只发剩余变化，不 409', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库名称', 'N1')
    await click(b, 'repo-save')
    await fill(b, '仓库路径', '/work/n2')
    await click(b, 'repo-save')
    const patch = reqs(fake, 'PATCH', '/api/ado/local-repos/repo%3Aa')
    expect(patch).toHaveLength(2)
    expect(bodyOf(patch[0]!).revision).toBe(5)
    expect(keysOf(patch[1]!)).toEqual(['path', 'revision'])
    expect(bodyOf(patch[1]!).revision).toBe(6)
    expect(be.conflicts).toHaveLength(0)
  })

  it('保存在途时再次点击保存：不重复发送；响应后再保存只发剩余变化', async () => {
    const fake = createFake()
    seedRepos(fake)
    const be = repoBackend(fake)
    const b = await openTab(fake, '本地仓库')
    await click(b, 'repo-row-repo:a')
    await fill(b, '仓库名称', 'P1')
    const g = holdWrite(fake, be, (c) => c.method === 'PATCH')
    await click(b, 'repo-save')
    expect(g.hit).toBe(true)
    await click(b, 'repo-save')
    expect(reqs(fake, 'PATCH', '/api/ado/local-repos/')).toHaveLength(1)
    g.go()
    await settle()
    await fill(b, '仓库路径', '/work/p2')
    await click(b, 'repo-save')
    const patch = reqs(fake, 'PATCH', '/api/ado/local-repos/repo%3Aa')
    expect(patch).toHaveLength(2)
    expect(keysOf(patch[1]!)).toEqual(['path', 'revision'])
    expect(bodyOf(patch[1]!).revision).toBe(6)
  })
})

// ---------------------------------------------------------------------------
describe('其他条目的编辑会话（library / project，UX 1）', () => {
  it('library 再次点击「新建」应开始新的编辑会话：未提交草稿被清空', async () => {
    const fake = createFake()
    const b = await openTab(fake, 'ADO 连接')
    await click(b, 'library-add')
    await fill(b, 'library 名称', '未提交草稿')
    await click(b, 'library-add')
    expect(valueOf(b, 'library 名称')).toBe('')
  })

  it('library A→B→A：未保存草稿不跨会话保留', async () => {
    const fake = createFake()
    const b = await openTab(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await fill(b, 'library 名称', 'DRAFT')
    await click(b, 'library-row-lib:b')
    await click(b, 'library-row-lib:a')
    expect(valueOf(b, 'library 名称')).toBe('示例库')
  })

  it('project A→B→A：未保存草稿不跨会话保留', async () => {
    const fake = createFake()
    fake.state.ado = makeAdo({
      projects: [
        { id: 'proj:a', library_id: 'lib:a', collection: 'Col', project: '项目甲' },
        { id: 'proj:b', library_id: 'lib:a', collection: 'Col', project: '项目乙' },
      ],
    })
    const b = await openTab(fake, 'ADO 连接')
    await click(b, 'project-row-proj:a')
    await fill(b, 'project 名称', 'DRAFT')
    await click(b, 'project-row-proj:b')
    await click(b, 'project-row-proj:a')
    expect(valueOf(b, 'project 名称')).toBe('项目甲')
  })
})

// ---------------------------------------------------------------------------
describe('S1 规则回归：PAT 不回显不进存储、origin 确认冻结、PAT 长度（合同 4）', () => {
  it('PAT 保存后：输入框清空；PAT 不出现在 DOM、localStorage、sessionStorage、console 或请求 URL/query 中', async () => {
    const fake = createFake()
    const spies = consoleSpies()
    const b = await openTab(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await b.wrapper.get('input[type=password]').setValue(PAT)
    await click(b, 'pat-save')
    const put = fake.calls.filter((c) => c.method === 'PUT' && c.path.endsWith('/pat'))
    expect(put).toHaveLength(1)
    expect(bodyOf(put[0]!).pat).toBe(PAT)
    expect((b.wrapper.get('input[type=password]').element as HTMLInputElement).value).toBe('')
    expect(document.body.innerHTML).not.toContain(PAT)
    expect(storageText()).not.toContain(PAT)
    const logged = spies.flatMap((s) => s.mock.calls).map((a) => a.map(String).join(' '))
    expect(noise(...logged)).not.toContain(PAT)
    for (const c of fake.calls) {
      expect(c.path).not.toContain(PAT)
      expect(Object.values(c.query).join(' ')).not.toContain(PAT)
    }
  })

  it('PAT 少于 8 字符：不发请求，提示固定文案，输入保留', async () => {
    const fake = createFake()
    const b = await openTab(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await b.wrapper.get('input[type=password]').setValue('short')
    await click(b, 'pat-save')
    expect(fake.calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
    expect(tid(b, 'library-local-error').text()).toContain('PAT 至少 8 个字符')
    expect((b.wrapper.get('input[type=password]').element as HTMLInputElement).value).toBe('short')
  })

  /** 库 lib:a 的 PATCH：地址 origin 变化且未带 keep_pat/pat 时返回 pat_origin_change；否则按 revision 应用。 */
  function libraryPatch(fake: Fake) {
    fake.handlers.push((c) => {
      if (c.method !== 'PATCH' || c.path !== '/api/ado/libraries/lib%3Aa') return undefined
      const b = (c.body ?? {}) as {
        base_url?: string
        name?: string
        keep_pat?: boolean
        pat?: string
        revision: number
      }
      const lib = fake.state.ado.libraries[0]!
      if (
        b.base_url &&
        new URL(b.base_url).origin !== new URL(lib.base_url).origin &&
        !b.keep_pat &&
        !b.pat
      )
        return err(409, 'pat_origin_change', 'PAT 将发往新地址')
      if (b.revision !== fake.state.ado.revision)
        return err(409, 'revision_conflict', '配置已被其他写者更新', {
          revision: fake.state.ado.revision,
        })
      const ado = structuredClone(fake.state.ado)
      if (b.base_url) ado.libraries[0]!.base_url = b.base_url
      if (b.name) ado.libraries[0]!.name = b.name
      ado.revision += 1
      fake.state.ado = ado
      return json({ revision: ado.revision })
    })
  }

  it('地址改为新 origin：待确认，确认只提交冻结的请求体（keep_pat），确认期间地址输入禁用', async () => {
    const fake = createFake()
    libraryPatch(fake)
    const b = await openTab(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await fill(b, 'library 地址', 'https://new.example.test/tfs')
    await click(b, 'library-save')
    expect(tid(b, 'pat-origin-change').exists()).toBe(true)
    expect(tid(b, 'pat-origin-change').text()).toContain('new.example.test')
    expect(field(b, 'library 地址').attributes('disabled')).toBeDefined()
    await click(b, 'origin-keep')
    const patch = fake.calls.filter((c) => c.method === 'PATCH')
    expect(patch).toHaveLength(2)
    expect(patch[1]!.body).toEqual({
      base_url: 'https://new.example.test/tfs',
      keep_pat: true,
      revision: 5,
    })
    expect(tid(b, 'pat-origin-change').exists()).toBe(false)
  })

  it('待确认期间切换到另一个 library：待确认对象被清除，不能再确认到原条目', async () => {
    const fake = createFake()
    libraryPatch(fake)
    const b = await openTab(fake, 'ADO 连接')
    await click(b, 'library-row-lib:a')
    await fill(b, 'library 地址', 'https://new.example.test/tfs')
    await click(b, 'library-save')
    expect(tid(b, 'pat-origin-change').exists()).toBe(true)
    await click(b, 'library-row-lib:b')
    expect(tid(b, 'pat-origin-change').exists()).toBe(false)
    expect(fake.calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
  })
})
