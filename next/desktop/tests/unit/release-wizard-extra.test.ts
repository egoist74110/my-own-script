// 发布配置向导与编辑器的对抗性补测（补充 release-wizard.test.ts，不重复其中已有用例）。
// 覆盖：环境默认不勾的各种路径、编辑器重新识别后采用、去设置路由、来回导航草稿、保存部分失败与版本、
// 发现接口加载/错误/重试、分支搜索与重复、目标改名与逗号环境名。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { boot, json } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

type ReleaseView = components['schemas']['ReleaseView']
type RepoFound = components['schemas']['DiscoverRepoResponse']
type Base = (r: Request) => Promise<Response>

interface Call {
  method: string
  path: string
  query: Record<string, string>
  body: unknown
}
interface TargetBody {
  id?: string
  name: string
  release_id: string | null
  build_id: string | null
  release_stage_ids: string[]
  release_stage_names: string[]
}
interface CfgBody {
  name: string
  project_id: string | null
  repo_id: string | null
  repo_name: string | null
  local_repo_path: string
  revision: number
  branches: Array<{ build_branch: string; merges: Array<{ source: string; target: string }> }>
  targets: TargetBody[]
}

// ───────────── 假数据（与 release-wizard.test.ts 同源，贴近真实 CG_Vue_Front） ─────────────

const BRANCHES = [
  'main',
  'develop',
  'release/1.0',
  'release/1.1',
  'hotfix/a',
  'hotfix/b',
  'feature/login',
  'feature/pay',
  'feature/search',
  'feature/vip',
  'feature/event',
  'feature/ui',
  'test',
  'staging',
]
const ENV_NAMES = [
  '开发环境',
  '测试环境',
  '预发环境',
  'UAT',
  '灰度环境',
  '演示环境',
  '备用环境',
  '正式环境',
]
const envs = ENV_NAMES.map((name, i) => ({ id: String(i + 1), name }))

const releases = [
  { id: '21', name: '前台发布', build_definition_ids: ['11'], environments: envs },
  { id: '22', name: '后台发布', build_definition_ids: ['12'], environments: envs },
  { id: '23', name: 'H5 发布', build_definition_ids: ['13'], environments: envs },
]
const suggested = releases.map((r, i) => ({
  id: null,
  name: r.name,
  enabled: true,
  build_kind: 'pipeline' as const,
  build_id: String(11 + i),
  build_name: `构建 ${r.name}`,
  release_id: r.id,
  release_name: r.name,
  release_stage_ids: envs.map((e) => e.id),
  release_stage_names: envs.map((e) => e.name),
}))

const FOUND: RepoFound = {
  local_repo_path: '/repos/front',
  remote_url: 'https://ado.example/DefaultCollection/Front/_git/CG_Vue_Front',
  project_id: 'proj:front',
  project_label: 'DefaultCollection/Front',
  repo_id: 'repo-front',
  repo_name: 'CG_Vue_Front',
  default_branch: 'main',
  suggested_name: 'CG_Vue_Front',
  existing_config_id: null,
  reason: null,
}

function existingConfig(): ReleaseView {
  return {
    id: 'cfg-exist',
    name: '已有配置',
    sort_order: 0,
    project_id: 'proj:front',
    repo_id: 'repo-front',
    repo_name: 'CG_Vue_Front',
    local_repo_path: '/repos/front',
    agent_queue_id: '5',
    agent_queue_name: '默认队列',
    branches: [
      { id: 'b-main', build_branch: 'main', update_branches: [], merges: [], push_branches: [] },
    ],
    warnings: [],
    targets: [
      {
        id: 'tg-1',
        name: '前台发布',
        enabled: true,
        build_kind: 'pipeline',
        build_id: '11',
        build_name: '构建 前台发布',
        release_id: '21',
        release_name: '前台发布',
        release_stage_ids: ['2'],
        release_stage_names: ['测试环境'],
      },
    ],
    commands: [
      {
        id: 'cmd-1',
        name: '发测试',
        enabled: true,
        sort_order: 0,
        branch_id: 'b-main',
        tg_command: '',
        tg_desc: '',
        target_ids: ['tg-1'],
        active_run_id: null,
        last_run: null,
      },
    ],
  }
}

const errBody = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ detail: { code, message } }), {
    status,
    headers: { 'content-type': 'application/json' },
  })

interface ServerOpts {
  repo?: (path: string) => RepoFound | Response
  queues?: Array<{ id: string; name: string }>
  onWrite?: (c: Call) => Response | null
}

/** 假后端：与 release-wizard.test.ts 的口径一致，记录所有写请求。 */
function makeServer(opts: ServerOpts = {}) {
  const calls: Call[] = []
  let revision = 5
  const existing = existingConfig()
  let createdCfg: ReleaseView | null = null
  const localRepos = [
    { id: 'lr-front', name: 'CG_Vue_Front', path: '/repos/front', exists: true },
    { id: 'lr-pin', name: 'PinBall', path: '/repos/pinball', exists: true },
  ]

  const fetchImpl: Base = async (input) => {
    const url = new URL(input.url)
    const txt = input.method === 'GET' ? '' : await input.clone().text()
    const call: Call = {
      method: input.method,
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      body: txt ? JSON.parse(txt) : null,
    }
    calls.push(call)
    const p = url.pathname
    if (p === '/health')
      return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
    if (p === '/api/tasks') return json({ items: [], revision })
    if (p === '/api/runs') return json({ items: [], cursor: null })
    if (p === '/api/ado')
      return json({
        active_library_id: null,
        active_project_id: null,
        libraries: [],
        local_repos: localRepos.map((r) => ({ ...r, warnings: [] })),
        projects: [],
        revision: 1,
      })
    if (p === '/api/release-configs' && input.method === 'GET')
      return json({ items: [existing, ...(createdCfg ? [createdCfg] : [])], revision })
    if (p === '/api/release-configs/cfg-exist' && input.method === 'GET')
      return json({ item: existing, revision })
    if (p === '/api/release-configs/new-cfg' && input.method === 'GET')
      return json({ item: createdCfg, revision })
    if (p === '/api/release-configs/discover/repo') {
      const path = (call.body as { local_repo_path: string }).local_repo_path
      const r = opts.repo ? opts.repo(path) : { ...FOUND, local_repo_path: path }
      return r instanceof Response ? r : json(r)
    }
    if (p === '/api/release-configs/discover/branches')
      return json({ branches: BRANCHES, default_branch: 'main' })
    if (p === '/api/release-configs/discover/targets')
      return json({
        builds: [
          { id: '11', name: '构建 前台发布', kind: 'pipeline' },
          { id: '12', name: '构建 后台发布', kind: 'pipeline' },
          { id: '13', name: '构建 H5 发布', kind: 'pipeline' },
        ],
        releases,
        suggested_targets: suggested,
      })
    if (p === '/api/release-configs/discover/queues')
      return json({
        queues: opts.queues ?? [
          { id: '5', name: '默认队列' },
          { id: '6', name: '备用队列' },
        ],
      })
    if (input.method !== 'GET') {
      const custom = opts.onWrite?.(call)
      if (custom) return custom
      revision += 1
      if (p === '/api/release-configs' && input.method === 'POST') {
        const body = call.body as {
          name: string
          branches: Array<{ build_branch: string }>
          targets: Array<Record<string, unknown>>
        }
        createdCfg = {
          id: 'new-cfg',
          name: body.name,
          sort_order: 0,
          project_id: 'proj:front',
          repo_id: 'repo-front',
          repo_name: 'CG_Vue_Front',
          local_repo_path: '/repos/front',
          branches: body.branches.map((b, i) => ({
            ...b,
            id: `nb-${i}`,
            update_branches: [],
            merges: [],
            push_branches: [],
          })),
          warnings: [],
          targets: body.targets.map((t, i) => ({ ...t, id: `nt-${i}` })) as ReleaseView['targets'],
          commands: [],
        } as ReleaseView
        return json({ id: 'new-cfg', revision })
      }
      if (/\/commands$/.test(p)) return json({ item: { id: `c-${calls.length}` }, revision })
      return json({ revision, id: 'x' })
    }
    return json({})
  }
  return { calls, fetchImpl }
}

/**
 * 请求拦截层：按路径（可选方法）挂规则。respond 返回 Response 则直接应答（不进假后端）；
 * map 改写假后端的成功 JSON。seen 记录所有命中规则的请求（包括被 respond 直接应答的）。
 */
interface Rule {
  path: string
  method?: string
  respond?: (req: Request, hit: number) => Response | null | Promise<Response | null>
  map?: (body: unknown, hit: number) => unknown
}
function rig(base: Base, rules: Rule[]) {
  const seen: Array<{ path: string; method: string; hit: number }> = []
  const hits = new Map<Rule, number>()
  const fetchImpl = async (req: Request): Promise<Response> => {
    const url = new URL(req.url)
    const rule = rules.find(
      (r) => r.path === url.pathname && (!r.method || r.method === req.method),
    )
    if (!rule) return base(req)
    const hit = hits.get(rule) ?? 0
    hits.set(rule, hit + 1)
    seen.push({ path: url.pathname, method: req.method, hit })
    const early = rule.respond ? await rule.respond(req, hit) : null
    if (early) return early
    const res = await base(req)
    if (!rule.map || !res.ok) return res
    return json(rule.map(await res.json(), hit))
  }
  return { fetchImpl: fetchImpl as unknown as typeof fetch, seen }
}

/** 挂起某个请求直到调用 open()，用于验证加载中的禁用与提示。 */
function gate(path: string, method = 'GET') {
  let open!: () => void
  const p = new Promise<void>((r) => (open = r))
  const rule: Rule = {
    path,
    method,
    respond: async () => {
      await p
      return null
    },
  }
  return { rule, open }
}

const mounted: Array<Awaited<ReturnType<typeof boot>>> = []

async function start(fetchImpl: Base | typeof fetch) {
  const b = await boot({ path: '/tasks', fetchImpl: fetchImpl as typeof fetch })
  mounted.push(b)
  b.sock.emit(hello())
  await settle()
  return b
}

async function settle() {
  for (let i = 0; i < 4; i++) await flushPromises()
}

async function waitFor(pred: () => boolean, label: string) {
  for (let i = 0; i < 80; i++) {
    if (pred()) return
    await settle()
    await new Promise((r) => setTimeout(r, 0))
  }
  throw new Error(`等待超时：${label}`)
}

const q = <T extends Element>(sel: string) => document.querySelector(sel) as T | null
const qa = <T extends Element>(sel: string) => Array.from(document.querySelectorAll(sel)) as T[]
const text = (sel: string) => q(sel)?.textContent ?? ''
const btn = (sel: string) => q<HTMLButtonElement>(sel)!

async function click(sel: string) {
  const el = q<HTMLElement>(sel)
  if (!el) throw new Error(`找不到 ${sel}`)
  el.click()
  await settle()
}
async function clickBtnIn(container: string, label: string) {
  const el = qa<HTMLButtonElement>(`${container} button`).find((x) =>
    x.textContent?.includes(label),
  )
  if (!el) throw new Error(`${container} 里没有按钮“${label}”`)
  el.click()
  await settle()
}
async function check(sel: string, on = true) {
  const el = q<HTMLInputElement>(sel)
  if (!el) throw new Error(`找不到 ${sel}`)
  el.checked = on
  el.dispatchEvent(new Event('change', { bubbles: true }))
  await settle()
}
async function setValue(sel: string, value: string) {
  const el = q<HTMLInputElement>(sel)
  if (!el) throw new Error(`找不到输入框 ${sel}`)
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  await settle()
}
/** 按 sr-only 标签文字找输入框；scope 可限定在某个容器里（同名标签多处出现时用）。 */
async function typeByLabel(label: string, value: string, scope = '') {
  const pool = qa<HTMLLabelElement>(`${scope} label.text-input`.trim())
  const l = pool.find((x) => x.querySelector('.sr-only')?.textContent === label)
  const el = l?.querySelector('input')
  if (!el) throw new Error(`找不到输入框 ${label}`)
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  await settle()
}

const checkedEnvs = () =>
  qa<HTMLInputElement>('[data-testid^="adder-env-"]').filter((e) => e.checked)
const drafts = () => qa<HTMLLIElement>('li[data-testid^="wizard-draft-"]')
const draftName = (i: number) =>
  q<HTMLInputElement>(`li[data-testid="wizard-draft-${i}"] input[type="text"]`)!.value
const curStep = () => q('[data-testid^="wizard-step-"]')?.getAttribute('data-testid') ?? ''

async function goNext() {
  if (btn('[data-testid="wizard-next"]').disabled)
    throw new Error(`下一步被禁用（当前 ${curStep()}）`)
  await click('[data-testid="wizard-next"]')
}
async function goBack(n = 1) {
  for (let i = 0; i < n; i++) await click('[data-testid="wizard-back"]')
}
async function openWizard(b: Awaited<ReturnType<typeof start>>) {
  await b.wrapper.get('[data-testid="new-task-btn"]').trigger('click')
  await settle()
}
async function openEdit(b: Awaited<ReturnType<typeof start>>) {
  await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
  await settle()
}
/** 表单式添加一个目标：选构建定义（其唯一的 Release 自动选中）、勾环境、可选改名，再点“添加这个目标”。 */
async function addTarget(rel: string, envIds: string[], name?: string) {
  const bsel = q<HTMLSelectElement>('[data-testid="adder-build"]')
  if (!bsel) throw new Error('找不到目标添加表单')
  bsel.value = String(11 + (Number(rel) - 21))
  bsel.dispatchEvent(new Event('change', { bubbles: true }))
  await settle()
  for (const e of envIds) await check(`[data-testid="adder-env-${e}"]`)
  if (name !== undefined) await setValue('[data-testid="adder-name"] input', name)
  await click('[data-testid="adder-add-btn"]')
}

async function pickFront() {
  await click('[data-testid="wizard-local-repo-lr-front"]')
}
/** 选仓库并走到“发布目标”步。 */
async function toTargets() {
  await pickFront()
  await goNext()
  await goNext()
}

const cfgPost = (s: ReturnType<typeof makeServer>) =>
  s.calls.find((c) => c.method === 'POST' && c.path === '/api/release-configs')!.body as CfgBody
const cmdPosts = (s: ReturnType<typeof makeServer>) =>
  s.calls.filter((c) => c.method === 'POST' && /\/commands$/.test(c.path))

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  document.body.innerHTML = ''
})
afterEach(async () => {
  for (const b of mounted.splice(0)) await b.done()
  document.body.innerHTML = ''
})

// ═════════════════════════════ 向导：环境默认不勾 ═════════════════════════════

describe('向导 · 环境永不默认勾选', () => {
  it('关闭向导再打开：上一次勾过的环境不会带到新向导里', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    expect(text('[data-testid="wizard-targets-count"]')).toContain('已加入 1 个目标')
    await click('[data-testid="wizard-cancel"]')
    expect(q('[data-testid="release-wizard"]')).toBeNull()

    await openWizard(b)
    await toTargets()
    expect(checkedEnvs()).toHaveLength(0)
    expect(text('[data-testid="wizard-targets-count"]')).toContain('已加入 0 个目标')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
  })

  it('返回到仓库步重新识别同一仓库后：目标步的环境全部清空', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await goBack(2) // 目标 → 分支 → 仓库
    expect(curStep()).toBe('wizard-step-repo')
    await pickFront()
    await goNext()
    if (!q<HTMLInputElement>('[data-testid="branch-pick-main"]')!.checked)
      await check('[data-testid="branch-pick-main"]')
    await goNext()
    expect(curStep()).toBe('wizard-step-targets')
    expect(checkedEnvs()).toHaveLength(0)
    expect(text('[data-testid="wizard-targets-count"]')).toContain('已加入 0 个目标')
  })

  it('改名之后环境仍然全部不勾，且没有任何目标被加入', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await toTargets()
    // 选了构建定义、改了名字，但一个环境都没勾：不会有目标，也不能添加
    const bsel = q<HTMLSelectElement>('[data-testid="adder-build"]')!
    bsel.value = '11'
    bsel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    await setValue('[data-testid="adder-name"] input', '改名后的目标')
    expect(btn('[data-testid="adder-add-btn"]').disabled).toBe(true)
    expect(checkedEnvs()).toHaveLength(0)
    expect(text('[data-testid="wizard-targets-count"]')).toContain('已加入 0 个目标')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
  })

  it('来回切换后取消勾选：保存的 payload 只含仍勾着环境的目标，没勾的不会进入', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await goNext() // → 队列
    await goBack() // → 目标
    await click('[data-testid="wizard-remove-target-0"]') // 删掉已加入的 21
    await addTarget('22', ['2'])
    expect(text('[data-testid="wizard-targets-count"]')).toContain('已加入 1 个目标')
    await goNext() // → 队列
    await goNext() // → 命令
    await goNext() // → 确认
    await click('[data-testid="wizard-save"]')

    const body = cfgPost(server)
    expect(body.targets).toHaveLength(1)
    expect(body.targets[0]!.release_id).toBe('22')
    expect(body.targets[0]!.release_stage_ids).toEqual(['2'])
    expect(cmdPosts(server).map((c) => (c.body as { name: string }).name)).toEqual([
      'main → 后台发布',
    ])
  })

  it('FINDING：高级“手动添加目标”只填构建定义 ID、没填任何环境，仍会进入保存的 payload', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await toTargets()
    await click('[data-testid="wizard-advanced-targets"] [data-testid="fold-toggle"]')
    await click('[data-testid="wizard-add-manual-target"]')
    await typeByLabel('目标名称', '手动A', '[data-testid="wizard-advanced-targets"]')
    await typeByLabel('构建定义 ID', '11', '[data-testid="wizard-advanced-targets"]')
    // 规则：目标必须有构建定义、Release 定义和至少一个环境；没填环境时“下一步”禁用并提示
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    expect(text('[data-testid="wizard-blocked-hint"]')).toContain('环境')
    await typeByLabel('Release 定义 ID', '21', '[data-testid="wizard-advanced-targets"]')
    await typeByLabel('环境 ID', '1', '[data-testid="wizard-advanced-targets"]')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(false)
    await goNext()
    await goNext()
    await goNext()
    await click('[data-testid="wizard-save"]')

    const body = cfgPost(server)
    // 期望：没有环境的目标不应被保存（与“至少勾选一个目标的环境才能继续”的提示一致）
    expect(body.targets.every((t) => t.release_stage_ids.length > 0)).toBe(true)
  })
})

// ═════════════════════════════ 编辑器：从 ADO 添加与重新识别 ═════════════════════════════

describe('编辑器 · 重新识别与采用', () => {
  it('识别结果与当前关联不同：采用后保存的 payload 带上新的 project/repo，本地路径保持不变', async () => {
    const server = makeServer({
      repo: (path) => ({
        ...FOUND,
        local_repo_path: path,
        project_id: 'proj:new',
        project_label: 'DefaultCollection/New',
        repo_id: 'repo-new',
        repo_name: 'CG_New',
      }),
    })
    const b = await start(server.fetchImpl)
    await openEdit(b)
    await click('[data-testid="rediscover-btn"]')
    expect(text('[data-testid="rediscover-result"]')).toContain('关联不同')
    await click('[data-testid="adopt-discovery-btn"]')
    expect(text('[data-testid="repo-info"]')).toContain('CG_New')

    await click('[data-testid="save-task-btn"]')
    const patch = server.calls.find((c) => c.method === 'PATCH')!.body as CfgBody
    expect(patch.project_id).toBe('proj:new')
    expect(patch.repo_id).toBe('repo-new')
    expect(patch.repo_name).toBe('CG_New')
    expect(patch.local_repo_path).toBe('/repos/front')
  })

  it('采用新仓库后，“从 ADO 添加目标”用新的项目与仓库去读取', async () => {
    const server = makeServer({
      repo: (path) => ({
        ...FOUND,
        local_repo_path: path,
        project_id: 'proj:new',
        repo_id: 'repo-new',
        repo_name: 'CG_New',
      }),
    })
    const b = await start(server.fetchImpl)
    await openEdit(b)
    await click('[data-testid="rediscover-btn"]')
    await click('[data-testid="adopt-discovery-btn"]')
    await click('[data-testid="add-remote-targets-btn"]')
    const last = server.calls
      .filter((c) => c.path === '/api/release-configs/discover/targets')
      .at(-1)!
    expect(last.query).toEqual({ project_id: 'proj:new', repo_id: 'repo-new' })
  })

  it('识别没有匹配 ADO 项目时：只提示去设置，不出现“采用识别结果”', async () => {
    const server = makeServer({
      repo: (path) => ({
        local_repo_path: path,
        remote_url: 'https://ado.example/DefaultCollection/Other/_git/x',
        project_id: null,
        project_label: null,
        repo_id: null,
        repo_name: null,
        default_branch: null,
        suggested_name: null,
        existing_config_id: null,
        reason: 'project_not_matched',
      }),
    })
    const b = await start(server.fetchImpl)
    await openEdit(b)
    await click('[data-testid="rediscover-btn"]')
    expect(q('[data-testid="rediscover-nomatch"]')).not.toBeNull()
    expect(q('[data-testid="adopt-discovery-btn"]')).toBeNull()
  })

  it('FINDING：采用了另一个仓库后，之前在旧仓库里勾过的环境不应残留到新的“从 ADO 添加目标”里', async () => {
    const server = makeServer({
      repo: (path) => ({
        ...FOUND,
        local_repo_path: path,
        project_id: 'proj:new',
        repo_id: 'repo-new',
        repo_name: 'CG_New',
      }),
    })
    const b = await start(server.fetchImpl)
    await openEdit(b)
    await click('[data-testid="add-remote-targets-btn"]')
    // 在旧仓库里选了构建并勾了环境，但没点添加
    const bsel = q<HTMLSelectElement>('[data-testid="adder-build"]')!
    bsel.value = '12'
    bsel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    await check('[data-testid="adder-env-1"]')
    expect(checkedEnvs()).toHaveLength(1)
    await click('[data-testid="add-remote-targets-btn"]') // 收起
    await click('[data-testid="rediscover-btn"]')
    await click('[data-testid="adopt-discovery-btn"]')
    await click('[data-testid="add-remote-targets-btn"]') // 重新展开
    expect(checkedEnvs()).toHaveLength(0)
    expect(q<HTMLSelectElement>('[data-testid="adder-build"]')!.value).toBe('')
  })

  it('重新识别失败且是 pat_missing：给“去设置”，点击后离开编辑器并跳到设置页', async () => {
    const server = makeServer({ repo: () => errBody(409, 'pat_missing', 'raw') })
    const b = await start(server.fetchImpl)
    await openEdit(b)
    await click('[data-testid="rediscover-btn"]')
    expect(text('[data-testid="rediscover-error"]')).toContain('PAT')
    await clickBtnIn('[data-testid="rediscover-error"]', '去设置')
    await waitFor(() => b.router.currentRoute.value.path === '/settings', '跳转到设置页')
    expect(b.router.currentRoute.value.path).toBe('/settings')
    expect(q('[data-testid="task-edit-sheet"]')).toBeNull()
  })

  it('重新识别中：按钮禁用并显示“识别中”，完成后恢复', async () => {
    const g = gate('/api/release-configs/discover/repo', 'POST')
    const server = makeServer()
    const b = await start(rig(server.fetchImpl, [g.rule]).fetchImpl)
    await openEdit(b)
    await click('[data-testid="rediscover-btn"]')
    expect(btn('[data-testid="rediscover-btn"]').disabled).toBe(true)
    expect(text('[data-testid="rediscover-btn"]')).toContain('识别中')
    g.open()
    await waitFor(() => !!q('[data-testid="rediscover-result"]'), '重新识别结果')
    expect(btn('[data-testid="rediscover-btn"]').disabled).toBe(false)
  })

  it('远端分支读取失败：显示错误，点“重试”后能拿到分支列表', async () => {
    const server = makeServer()
    const r = rig(server.fetchImpl, [
      {
        path: '/api/release-configs/discover/branches',
        respond: (_req, hit) => (hit === 0 ? errBody(502, 'ado_unreachable', 'x') : null),
      },
    ])
    const b = await start(r.fetchImpl)
    await openEdit(b)
    await click('[data-testid="add-remote-branches-btn"]')
    expect(text('[data-testid="remote-branches-error"]')).toContain('连不上 ADO')
    await clickBtnIn('[data-testid="remote-branches-error"]', '重试')
    await waitFor(() => !!q('[data-testid="branch-pick-develop"]'), '远端分支列表')
    expect(r.seen.filter((s) => s.path === '/api/release-configs/discover/branches')).toHaveLength(
      2,
    )
  })

  it('FINDING：目标名称被就地清空后，保存按钮仍可点，且会静默存成“目标”（界面写的是“未命名”）', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openEdit(b)
    await setValue('[data-testid="target-edit-0"] input[type="text"]', '')
    // 期望：目标名为空时不能保存（或至少不静默改名）
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(true)
  })

  it('FINDING：编辑器“手动添加目标”后不填任何内容就保存，空目标会原样进入 PATCH payload', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openEdit(b)
    await click('[data-testid="edit-advanced"] [data-testid="fold-toggle"]')
    await click('[data-testid="add-target-btn"]')
    // 空目标不能保存：保存禁用并提示，且不会发出 PATCH
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(true)
    expect(text('[data-testid="target-problem-1"]')).toContain('构建定义')
    await click('[data-testid="save-task-btn"]')
    expect(server.calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('手动分支与远端同名（首尾有空格）：标记重复并禁止保存，不产生重复 ReleaseBranch', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openEdit(b)
    await click('[data-testid="add-branch-btn"]')
    await typeByLabel('分支 2 构建分支', '  main  ')
    expect(q('[data-testid="branch-dup-0"]')).not.toBeNull()
    expect(q('[data-testid="branch-dup-1"]')).not.toBeNull()
    expect(q('[data-testid="branches-invalid"]')).not.toBeNull()
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(true)
  })
})

// ═════════════════════════════ 向导：去设置路由 ═════════════════════════════

describe('向导 · 去设置', () => {
  it('pat_missing：点“去设置”后关闭向导并跳到 /settings', async () => {
    const server = makeServer({ repo: () => errBody(409, 'pat_missing', 'raw') })
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await pickFront()
    await clickBtnIn('[data-testid="wizard-discover-error"]', '去设置')
    await waitFor(() => b.router.currentRoute.value.path === '/settings', '跳转到设置页')
    expect(b.router.currentRoute.value.path).toBe('/settings')
    expect(q('[data-testid="release-wizard"]')).toBeNull()
  })

  it('ADO 项目未匹配：点“去设置”后关闭向导并跳到 /settings', async () => {
    const server = makeServer({
      repo: (path) => ({
        local_repo_path: path,
        remote_url: 'https://ado.example/DefaultCollection/Other/_git/x',
        project_id: null,
        project_label: null,
        repo_id: null,
        repo_name: null,
        default_branch: null,
        suggested_name: null,
        existing_config_id: null,
        reason: 'project_not_matched',
      }),
    })
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await pickFront()
    await click('[data-testid="wizard-goto-settings"]')
    await waitFor(() => b.router.currentRoute.value.path === '/settings', '跳转到设置页')
    expect(b.router.currentRoute.value.path).toBe('/settings')
    expect(q('[data-testid="release-wizard"]')).toBeNull()
  })
})

// ═════════════════════════════ 来回导航：草稿随选择变化 ═════════════════════════════

describe('向导 · 来回导航后的命令草稿', () => {
  it('取消勾选分支后，引用它的命令草稿消失，剩下的草稿不变', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await pickFront()
    await goNext()
    await check('[data-testid="branch-pick-develop"]')
    await goNext()
    await addTarget('21', ['1'])
    await goNext()
    await goNext()
    expect(drafts()).toHaveLength(2)

    await goBack(3) // 命令 → 队列 → 目标 → 分支
    expect(curStep()).toBe('wizard-step-branches')
    await check('[data-testid="branch-pick-develop"]', false)
    await goNext()
    await goNext()
    await goNext()
    expect(curStep()).toBe('wizard-step-commands')
    expect(drafts()).toHaveLength(1)
    expect(draftName(0)).toBe('main → 前台发布')
  })

  it('目标被移除（取消最后一个环境）后，引用它的命令草稿消失', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await addTarget('22', ['2'])
    await goNext()
    await goNext()
    expect(drafts()).toHaveLength(2)

    await goBack(2) // 命令 → 队列 → 目标
    await click('[data-testid="wizard-remove-target-1"]') // 删掉已加入的 22
    await goNext()
    await goNext()
    expect(drafts()).toHaveLength(1)
    expect(draftName(0)).toBe('main → 前台发布')
  })

  it('改过名的草稿保留；没改名的草稿跟着目标改名更新', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await addTarget('22', ['2'])
    await goNext()
    await goNext()
    await setValue('li[data-testid="wizard-draft-0"] input[type="text"]', 'MY-CMD')

    await goBack(2) // 命令 → 队列 → 目标
    await setValue('[data-testid="wizard-added-target-1"] input', '后台测试')
    await goNext()
    await goNext()
    expect(draftName(0)).toBe('MY-CMD')
    expect(draftName(1)).toBe('main → 后台测试')
  })
})

// ═════════════════════════════ 保存：部分失败与版本 ═════════════════════════════

describe('向导 · 保存的版本与重试', () => {
  it('配置创建冲突后重试：配置请求使用刷新后的最新 revision', async () => {
    let conflicted = false
    const server = makeServer({
      onWrite: (c) => {
        if (c.method === 'POST' && c.path === '/api/release-configs' && !conflicted) {
          conflicted = true
          return errBody(409, 'revision_conflict', 'x')
        }
        return null
      },
    })
    const r = rig(server.fetchImpl, [
      {
        path: '/api/release-configs',
        method: 'GET',
        map: (body) => (conflicted ? { ...(body as object), revision: 40 } : body),
      },
    ])
    const b = await start(r.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await goNext()
    await goNext()
    await goNext()
    await click('[data-testid="wizard-save"]')
    expect(text('[data-testid="wizard-save-error"]')).toContain('已重新读取最新内容')
    await click('[data-testid="wizard-save"]')

    const posts = server.calls.filter(
      (c) => c.method === 'POST' && c.path === '/api/release-configs',
    )
    expect(posts).toHaveLength(2)
    expect((posts[1]!.body as { revision: number }).revision).toBe(40)
    expect(q('[data-testid="release-wizard"]')).toBeNull()
  })

  it('命令中途失败后重试：补建的命令使用最新 revision，不重复建已成功的命令', async () => {
    let failed = 0
    const server = makeServer({
      onWrite: (c) => {
        if (/\/commands$/.test(c.path) && (c.body as { name: string }).name.startsWith('develop')) {
          failed += 1
          if (failed === 1) return errBody(422, 'validation_error', 'TG 指令已存在')
        }
        return null
      },
    })
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await pickFront()
    await goNext()
    await check('[data-testid="branch-pick-develop"]')
    await goNext()
    await addTarget('21', ['1'])
    await goNext()
    await goNext()
    await goNext()
    await click('[data-testid="wizard-save"]')
    await click('[data-testid="wizard-save"]')

    const cmds = cmdPosts(server)
    expect(cmds.map((c) => (c.body as { name: string }).name)).toEqual([
      'main → 前台发布',
      'develop → 前台发布',
      'develop → 前台发布',
    ])
    const [mainCmd, devFail, devRetry] = cmds.map((c) => (c.body as { revision: number }).revision)
    expect(devFail).toBe(devRetry)
    expect(devRetry!).toBeGreaterThan(mainCmd!)
    expect(
      server.calls.filter((c) => c.method === 'POST' && c.path === '/api/release-configs'),
    ).toHaveLength(1)
  })
})

// ═════════════════════════════ 发现接口：加载、错误、重试 ═════════════════════════════

describe('向导 · 发现接口的加载与错误', () => {
  it('识别中：识别按钮与仓库按钮禁用，完成后恢复', async () => {
    const g = gate('/api/release-configs/discover/repo', 'POST')
    const server = makeServer()
    const b = await start(rig(server.fetchImpl, [g.rule]).fetchImpl)
    await openWizard(b)
    await click('[data-testid="wizard-local-repo-lr-front"]')
    expect(btn('[data-testid="wizard-discover-btn"]').disabled).toBe(true)
    expect(text('[data-testid="wizard-discover-btn"]')).toContain('识别中')
    expect(btn('[data-testid="wizard-local-repo-lr-front"]').disabled).toBe(true)
    g.open()
    await waitFor(() => !!q('[data-testid="wizard-repo-result"]'), '识别结果')
    expect(btn('[data-testid="wizard-discover-btn"]').disabled).toBe(false)
    expect(btn('[data-testid="wizard-local-repo-lr-front"]').disabled).toBe(false)
  })

  it('分支读取中：显示加载提示且下一步禁用；读完默认只勾 main', async () => {
    const g = gate('/api/release-configs/discover/branches')
    const server = makeServer()
    const b = await start(rig(server.fetchImpl, [g.rule]).fetchImpl)
    await openWizard(b)
    await pickFront()
    await goNext()
    expect(q('[data-testid="wizard-branches-loading"]')).not.toBeNull()
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    g.open()
    await waitFor(() => !!q('[data-testid="branch-pick-main"]'), '分支列表')
    expect(q<HTMLInputElement>('[data-testid="branch-pick-main"]')!.checked).toBe(true)
    expect(
      qa<HTMLInputElement>('[data-testid^="branch-pick-"]').filter((e) => e.checked),
    ).toHaveLength(1)
  })

  it('分支读取失败：显示错误，点“重试”后恢复并只多请求一次', async () => {
    const server = makeServer()
    const r = rig(server.fetchImpl, [
      {
        path: '/api/release-configs/discover/branches',
        respond: (_req, hit) => (hit === 0 ? errBody(502, 'ado_unreachable', 'x') : null),
      },
    ])
    const b = await start(r.fetchImpl)
    await openWizard(b)
    await pickFront()
    await goNext()
    expect(text('[data-testid="wizard-branches-error"]')).toContain('连不上 ADO')
    await clickBtnIn('[data-testid="wizard-branches-error"]', '重试')
    await waitFor(() => !!q('[data-testid="branch-pick-main"]'), '分支列表恢复')
    expect(r.seen.filter((s) => s.path === '/api/release-configs/discover/branches')).toHaveLength(
      2,
    )
  })

  it('发布目标读取中：显示加载提示且下一步禁用', async () => {
    const g = gate('/api/release-configs/discover/targets')
    const server = makeServer()
    const b = await start(rig(server.fetchImpl, [g.rule]).fetchImpl)
    await openWizard(b)
    await pickFront()
    await goNext()
    await goNext()
    expect(q('[data-testid="wizard-targets-loading"]')).not.toBeNull()
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    g.open()
    await waitFor(() => !!q('[data-testid="adder-build"]'), '目标分组')
  })

  it('发布目标读取失败：点“重试”后能显示分组', async () => {
    const server = makeServer()
    const r = rig(server.fetchImpl, [
      {
        path: '/api/release-configs/discover/targets',
        respond: (_req, hit) => (hit === 0 ? errBody(502, 'ado_unreachable', 'x') : null),
      },
    ])
    const b = await start(r.fetchImpl)
    await openWizard(b)
    await toTargets()
    expect(q('[data-testid="wizard-targets-error"]')).not.toBeNull()
    await clickBtnIn('[data-testid="wizard-targets-error"]', '重试')
    await waitFor(() => !!q('[data-testid="adder-build"]'), '目标分组恢复')
  })

  it('Agent 队列读取失败：显示错误，点“重试”后出现下拉', async () => {
    const server = makeServer()
    const r = rig(server.fetchImpl, [
      {
        path: '/api/release-configs/discover/queues',
        respond: (_req, hit) => (hit === 0 ? errBody(502, 'ado_unreachable', 'x') : null),
      },
    ])
    const b = await start(r.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await goNext()
    expect(q('[data-testid="queue-error"]')).not.toBeNull()
    await click('[data-testid="queue-retry"]')
    await waitFor(() => !!q('[data-testid="queue-select-input"]'), '队列下拉')
  })

  it('识别同一仓库后回到分支步，默认分支 main 仍被自动勾选（不丢默认值）', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await pickFront()
    await goNext()
    expect(q<HTMLInputElement>('[data-testid="branch-pick-main"]')!.checked).toBe(true)
    await goBack(2)
    await pickFront()
    await goNext()
    // 期望：默认分支仍自动勾选（与“默认只勾选默认分支”的说明一致）
    expect(q<HTMLInputElement>('[data-testid="branch-pick-main"]')?.checked).toBe(true)
  })
})

// ═════════════════════════════ 分支：搜索与重复 ═════════════════════════════

describe('向导 · 分支搜索与重复', () => {
  it('搜索不区分大小写地过滤；已勾选的分支在清空搜索后仍然勾着', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await pickFront()
    await goNext()
    await check('[data-testid="branch-pick-feature/login"]')
    await typeByLabel('搜索分支', 'FEATURE')
    expect(qa('[data-testid^="branch-pick-"]')).toHaveLength(6)
    expect(text('.bp-count')).toContain('当前筛出 6 个')
    await typeByLabel('搜索分支', 'hotfix')
    expect(qa('[data-testid^="branch-pick-"]')).toHaveLength(2)
    await typeByLabel('搜索分支', 'zzz-none')
    expect(text('[data-testid="branch-picker"]')).toContain('没有匹配的分支')
    await typeByLabel('搜索分支', '')
    expect(qa('[data-testid^="branch-pick-"]')).toHaveLength(14)
    expect(q<HTMLInputElement>('[data-testid="branch-pick-feature/login"]')!.checked).toBe(true)
  })

  it('手动添加的分支：首尾空格、重复输入都不会产生重复分支，保存的 payload 分支互不相同', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await pickFront()
    await goNext()
    await typeByLabel('手动输入分支名', ' develop ')
    await click('[data-testid="wizard-add-extra-branch"]')
    await typeByLabel('手动输入分支名', 'hotfix/x')
    await click('[data-testid="wizard-add-extra-branch"]')
    await typeByLabel('手动输入分支名', '  hotfix/x  ')
    await click('[data-testid="wizard-add-extra-branch"]')
    expect(
      qa('li[data-testid^="wizard-branch-"]').map((x) => (x as HTMLElement).dataset.testid),
    ).toEqual(['wizard-branch-main', 'wizard-branch-develop', 'wizard-branch-hotfix/x'])
    await goNext()
    await addTarget('21', ['1'])
    await goNext()
    await goNext()
    await goNext()
    await click('[data-testid="wizard-save"]')
    const branches = cfgPost(server).branches.map((x) => x.build_branch)
    expect(branches).toEqual(['main', 'develop', 'hotfix/x'])
    expect(new Set(branches).size).toBe(branches.length)
  })
})

// ═════════════════════════════ 目标：改名与逗号环境名 ═════════════════════════════

describe('向导 · 目标改名与环境名', () => {
  it('目标名称清空：添加表单里不能添加，已加入列表里不能继续；改回名称后命令默认名与保存名一致（不再静默回落）', async () => {
    const server = makeServer()
    const b = await start(server.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await setValue('[data-testid="wizard-added-target-0"] input', '')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    expect(text('[data-testid="wizard-blocked-hint"]')).toContain('没有名称')
    await setValue('[data-testid="wizard-added-target-0"] input', '前台发布')
    await goNext()
    await goNext()
    expect(draftName(0)).toBe('main → 前台发布')
    await goNext()
    await click('[data-testid="wizard-save"]')
    expect(cfgPost(server).targets[0]!.name).toBe('前台发布')
    expect(cmdPosts(server)[0]!.body).toMatchObject({ name: 'main → 前台发布' })
  })

  it('环境名含逗号：确认页显示与保存值一致（逗号被替换成空格，只成一个环境）', async () => {
    const server = makeServer()
    const r = rig(server.fetchImpl, [
      {
        path: '/api/release-configs/discover/targets',
        map: (body) => {
          const t = body as {
            releases: Array<{ environments: Array<{ id: string; name: string }> }>
          }
          t.releases[0]!.environments[3]!.name = 'UAT,A组'
          return t
        },
      },
    ])
    const b = await start(r.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['4'])
    await goNext()
    await goNext()
    await goNext()
    const sum = text('[data-testid="wizard-summary"]')
    expect(sum).toContain('UAT A组')
    expect(sum).not.toContain('UAT,A组')
    await click('[data-testid="wizard-save"]')
    const t = cfgPost(server).targets[0]!
    expect(t.release_stage_names).toEqual(['UAT A组'])
    expect(t.release_stage_ids).toEqual(['4'])
  })

  it('FINDING：环境名只含分隔符（如单独一个逗号）时，保存的环境名数量与环境 ID 对不上', async () => {
    const server = makeServer()
    const r = rig(server.fetchImpl, [
      {
        path: '/api/release-configs/discover/targets',
        map: (body) => {
          const t = body as {
            releases: Array<{ environments: Array<{ id: string; name: string }> }>
          }
          t.releases[0]!.environments[3]!.name = ','
          return t
        },
      },
    ])
    const b = await start(r.fetchImpl)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['4'])
    await goNext()
    await goNext()
    await goNext()
    await click('[data-testid="wizard-save"]')
    const t = cfgPost(server).targets[0]!
    // 期望：每个环境 ID 都有对应名称（不能出现 ID 与名称数量不一致）
    expect(t.release_stage_names.length).toBe(t.release_stage_ids.length)
  })
})
