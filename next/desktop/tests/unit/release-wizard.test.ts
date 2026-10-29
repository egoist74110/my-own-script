// 新建发布配置向导（只选不填）与编辑器的“从 ADO 添加”：mock 四个发现接口，覆盖完整流程与各种边界
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tauri-apps/plugin-dialog', () => ({ open: vi.fn(async () => '/repos/front') }))
import type { components } from '@/api/schema'
import { boot, json } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

type ReleaseView = components['schemas']['ReleaseView']
type RepoFound = components['schemas']['DiscoverRepoResponse']

// ───────────────────────── 假数据：贴近真实（CG_Vue_Front：14 分支、3 个 Release、每个 8 个环境含正式环境） ─────────────────────────

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
const PROD_ID = '8'

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
  // 后端默认建议里环境全选，前端必须自己默认不勾
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

interface Call {
  method: string
  path: string
  query: Record<string, string>
  body: unknown
}

const errBody = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ detail: { code, message } }), {
    status,
    headers: { 'content-type': 'application/json' },
  })

interface ServerOpts {
  /** 自定义 repo 识别结果；返回 Response 则当错误处理。 */
  repo?: (path: string) => RepoFound | Response
  queues?: Array<{ id: string; name: string }>
  /** 写请求钩子：返回 Response 覆盖默认成功。 */
  onWrite?: (c: Call) => Response | null
  localRepos?: Array<{ id: string; name: string; path: string; exists: boolean }>
  /** 改写已有配置的内容。 */
  tweakExisting?: (c: ReleaseView) => void
  /** 新建后服务端读回的配置里 id 的前缀（分支/目标）。 */
}

function makeServer(opts: ServerOpts = {}) {
  const calls: Call[] = []
  let revision = 5
  const existing = existingConfig()
  opts.tweakExisting?.(existing)
  /** 向导建出来的配置：POST 之后按提交内容生成，供读回。 */
  let createdCfg: ReleaseView | null = null
  const localRepos = opts.localRepos ?? [
    { id: 'lr-front', name: 'CG_Vue_Front', path: '/repos/front', exists: true },
    { id: 'lr-pin', name: 'PinBall', path: '/repos/pinball', exists: true },
  ]

  const fetchImpl = async (input: Request) => {
    const url = new URL(input.url)
    const text = input.method === 'GET' ? '' : await input.clone().text()
    const call: Call = {
      method: input.method,
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      body: text ? JSON.parse(text) : null,
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
      const r = opts.repo
        ? opts.repo((call.body as { local_repo_path: string }).local_repo_path)
        : { ...FOUND, local_repo_path: (call.body as { local_repo_path: string }).local_repo_path }
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
          // 没有被任何 Release 引用的构建定义：列出但不可选
          { id: '235', name: 'CG_Vue_Front_Admin', kind: 'build' },
          { id: '236', name: 'CG_Vue_Front_Tenant', kind: 'pipeline' },
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
  return { calls, fetchImpl: fetchImpl as unknown as typeof fetch }
}

async function bootTasks(server: ReturnType<typeof makeServer>) {
  const b = await boot({ path: '/tasks', fetchImpl: server.fetchImpl })
  b.sock.emit(hello())
  await settle()
  return b
}

async function settle() {
  for (let i = 0; i < 4; i++) await flushPromises()
}

const q = <T extends Element>(sel: string) => document.querySelector(sel) as T | null
const qa = <T extends Element>(sel: string) => Array.from(document.querySelectorAll(sel)) as T[]

async function click(sel: string) {
  const el = q<HTMLElement>(sel)
  if (!el) throw new Error(`找不到 ${sel}`)
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
async function typeInto(sel: string, value: string) {
  const el = q<HTMLInputElement>(sel)
  if (!el) throw new Error(`找不到 ${sel}`)
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  await settle()
}
async function selectVal(sel: string, value: string) {
  const el = q<HTMLSelectElement>(sel)
  if (!el) throw new Error(`找不到 ${sel}`)
  el.value = value
  el.dispatchEvent(new Event('change', { bubbles: true }))
  await settle()
}
async function typeByLabel(label: string, value: string) {
  const l = qa<HTMLLabelElement>('label.text-input').find(
    (x) => x.querySelector('.sr-only')?.textContent === label,
  )
  const el = l?.querySelector('input')
  if (!el) throw new Error(`找不到输入框 ${label}`)
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  await settle()
}
const text = (sel: string) => q(sel)?.textContent ?? ''
const btn = (sel: string) => q<HTMLButtonElement>(sel)!
const stepText = () => text('[data-testid="release-wizard"]')

async function openWizard(b: Awaited<ReturnType<typeof bootTasks>>) {
  await b.wrapper.get('[data-testid="new-task-btn"]').trigger('click')
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
  if (name !== undefined) await typeInto('[data-testid="adder-name"] input', name)
  await click('[data-testid="adder-add-btn"]')
}

async function pickFront() {
  await click('[data-testid="wizard-local-repo-lr-front"]')
}
/** 走到“发布目标”步，并勾上某个 Release 的某个环境。 */
async function toTargets() {
  await pickFront()
  await click('[data-testid="wizard-next"]') // → 分支
  await click('[data-testid="wizard-next"]') // → 目标
}

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  document.body.innerHTML = ''
})
afterEach(() => {
  document.body.innerHTML = ''
})

const discoverCalls = (s: ReturnType<typeof makeServer>, kind: string) =>
  s.calls.filter((c) => c.path === `/api/release-configs/discover/${kind}`)

describe('新建发布配置向导', () => {
  it('完整流程：选仓库 → 分支 → 目标 → 队列 → 命令 → 确认保存；发现接口按步骤懒加载', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openWizard(b)

    // 打开时不请求任何发现接口；列出设置里登记的本地仓库
    expect(q('[data-testid="release-wizard"]')).not.toBeNull()
    expect(server.calls.filter((c) => c.path.includes('/discover/'))).toHaveLength(0)
    expect(text('[data-testid="wizard-step-repo"]')).toContain('PinBall')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)

    // 1 选仓库：只调 repo 识别，显示项目、仓库、默认分支、远端
    await pickFront()
    expect(discoverCalls(server, 'repo')).toHaveLength(1)
    expect(discoverCalls(server, 'repo')[0]!.body).toEqual({ local_repo_path: '/repos/front' })
    expect(discoverCalls(server, 'branches')).toHaveLength(0)
    const result = text('[data-testid="wizard-repo-result"]')
    expect(result).toContain('DefaultCollection/Front')
    expect(result).toContain('CG_Vue_Front')
    expect(result).toContain('main')
    expect(result).toContain('https://ado.example/DefaultCollection/Front/_git/CG_Vue_Front')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(false)
    await click('[data-testid="wizard-next"]')

    // 2 分支：14 个分支，默认只勾 default_branch；目标和队列还没请求
    expect(discoverCalls(server, 'branches')).toHaveLength(1)
    expect(discoverCalls(server, 'targets')).toHaveLength(0)
    expect(discoverCalls(server, 'queues')).toHaveLength(0)
    expect(qa('[data-testid^="branch-pick-"]')).toHaveLength(14)
    expect(
      qa<HTMLInputElement>('[data-testid^="branch-pick-"]').filter((e) => e.checked),
    ).toHaveLength(1)
    expect(q<HTMLInputElement>('[data-testid="branch-pick-main"]')!.checked).toBe(true)
    await check('[data-testid="branch-pick-develop"]')
    expect(q('[data-testid="wizard-branch-develop"]')).not.toBeNull()
    // Git 规则默认收起，展开后给 develop 配一条规则
    expect(q('[data-testid="wizard-branch-develop"] .brf')).toBeNull()
    await click('[data-testid="wizard-rules-toggle-develop"]')
    await click('[data-testid="wbranch-develop-merge-add"]')
    await selectVal('[data-testid="wbranch-develop-merge-src-0"]', 'develop')
    await selectVal('[data-testid="wbranch-develop-merge-dst-0"]', 'main')
    await click('[data-testid="wizard-next"]')

    // 3 目标：表单式添加。先选构建定义（5 个里有 3 个有 Release），环境默认都不勾，下一步不可用
    expect(discoverCalls(server, 'targets')).toHaveLength(1)
    expect(qa('[data-testid="adder-build"] option:not([disabled])')).toHaveLength(3)
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    {
      const bsel = q<HTMLSelectElement>('[data-testid="adder-build"]')!
      bsel.value = '11'
      bsel.dispatchEvent(new Event('change', { bubbles: true }))
      await settle()
    }
    // 只有一个 Release 引用它：自动选中；8 个环境全部未勾，添加按钮不可用
    expect(q<HTMLSelectElement>('[data-testid="adder-release"]')!.value).toBe('21')
    expect(qa('[data-testid^="adder-env-"]')).toHaveLength(8)
    expect(qa<HTMLInputElement>('[data-testid^="adder-env-"]').some((e) => e.checked)).toBe(false)
    expect(btn('[data-testid="adder-add-btn"]').disabled).toBe(true)
    await addTarget('21', ['2', '3'])
    expect(text('[data-testid="wizard-step-targets"]')).toContain('构建定义：构建 前台发布')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(false)
    await click('[data-testid="wizard-next"]')

    // 4 队列：下拉，默认“不指定”，选“备用队列”
    expect(discoverCalls(server, 'queues')).toHaveLength(1)
    const sel = q<HTMLSelectElement>('[data-testid="queue-select-input"]')!
    expect(sel.value).toBe('')
    sel.value = '6'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    await click('[data-testid="wizard-next"]')

    // 5 命令：2 个分支 × 1 个目标 = 2 条，默认名“分支 → 目标”，TG 命令名留空
    expect(qa('[data-testid^="wizard-draft-include-"]')).toHaveLength(2)
    expect(
      qa<HTMLInputElement>('[data-testid^="wizard-draft-"] input[type="text"]').map((i) => i.value),
    ).toEqual(['main → 前台发布', '', 'develop → 前台发布', ''])
    expect(stepText()).not.toContain('nb-0')
    await click('[data-testid="wizard-next"]')

    // 6 确认：名称默认 suggested_name，汇总里能看到所选环境
    expect(q<HTMLInputElement>('[data-testid="wizard-step-confirm"] input')!.value).toBe(
      'CG_Vue_Front',
    )
    const sum = text('[data-testid="wizard-summary"]')
    expect(sum).toContain('测试环境')
    expect(sum).toContain('预发环境')
    expect(sum).not.toContain('正式环境')
    expect(sum).toContain('备用队列')
    expect(btn('[data-testid="wizard-save"]').textContent).toContain('2 条命令')
    await click('[data-testid="wizard-save"]')

    const post = server.calls.find((c) => c.method === 'POST' && c.path === '/api/release-configs')!
    expect(post.body).toMatchObject({
      name: 'CG_Vue_Front',
      local_repo_path: '/repos/front',
      project_id: 'proj:front',
      repo_id: 'repo-front',
      repo_name: 'CG_Vue_Front',
      agent_queue_id: '6',
      agent_queue_name: '备用队列',
      revision: 5,
    })
    const body = post.body as {
      branches: Array<Record<string, unknown>>
      targets: Array<Record<string, unknown>>
    }
    expect(body.branches.map((x) => x.build_branch)).toEqual(['main', 'develop'])
    expect(body.branches[0]).toMatchObject({ update_branches: [], merges: [], push_branches: [] })
    expect(body.branches[1]!.merges).toEqual([{ source: 'develop', target: 'main' }])
    expect(body.targets).toHaveLength(1)
    expect(body.targets[0]).toMatchObject({
      name: '前台发布',
      build_kind: 'pipeline',
      build_id: '11',
      release_id: '21',
      release_stage_ids: ['2', '3'],
      release_stage_names: ['测试环境', '预发环境'],
    })
    expect('id' in body.targets[0]!).toBe(false)

    const cmds = server.calls.filter((c) => c.method === 'POST' && /\/commands$/.test(c.path))
    expect(cmds).toHaveLength(2)
    expect(cmds[0]!.path).toBe('/api/release-configs/new-cfg/commands')
    expect(cmds[0]!.body).toMatchObject({
      name: 'main → 前台发布',
      branch_id: 'nb-0',
      target_ids: ['nt-0'],
      tg_command: '',
      enabled: true,
    })
    expect(cmds[1]!.body).toMatchObject({
      name: 'develop → 前台发布',
      branch_id: 'nb-1',
      target_ids: ['nt-0'],
    })
    // 版本沿着服务端返回递增，不复用旧版本
    const revs = [post, ...cmds].map((c) => (c.body as { revision: number }).revision)
    expect(new Set(revs).size).toBe(3)
    // 保存完成后向导关闭
    expect(q('[data-testid="release-wizard"]')).toBeNull()
    await b.done()
  })

  it('向导里连续添加：添加后构建/Release 选择保留，环境和名称重置，面板不收起', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    expect(q<HTMLSelectElement>('[data-testid="adder-build"]')!.value).toBe('11')
    expect(q<HTMLSelectElement>('[data-testid="adder-release"]')!.value).toBe('21')
    expect(qa<HTMLInputElement>('[data-testid^="adder-env-"]').some((e) => e.checked)).toBe(false)
    expect(q('[data-testid="target-adder"]')).not.toBeNull()
    await b.done()
  })

  it('这个仓库已有配置：提示并给“去编辑已有配置”，同时允许继续新建', async () => {
    const server = makeServer({
      repo: (path) => ({ ...FOUND, local_repo_path: path, existing_config_id: 'cfg-exist' }),
    })
    const b = await bootTasks(server)
    await openWizard(b)
    await pickFront()
    expect(text('[data-testid="wizard-existing-config"]')).toContain('这个仓库已有配置')
    // 仍可继续新建
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(false)
    await click('[data-testid="wizard-edit-existing-btn"]')
    // 向导关闭，打开已有配置的编辑器
    expect(q('[data-testid="release-wizard"]')).toBeNull()
    expect(q('[data-testid="task-edit-sheet"]')).not.toBeNull()
    expect(q<HTMLInputElement>('[data-testid="task-edit-sheet"] input')!.value).toBe('已有配置')
    await b.done()
  })

  it('ADO 项目未匹配：显示原因与去设置，下一步被挡住，展开“高级：手动填写”后可只用路径继续', async () => {
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
    const b = await bootTasks(server)
    await openWizard(b)
    // 高级区默认收起
    expect(
      q('[data-testid="wizard-advanced-repo"] [data-testid="fold-toggle"]')!.getAttribute(
        'aria-expanded',
      ),
    ).toBe('false')
    expect(
      q<HTMLElement>('[data-testid="wizard-advanced-repo"] [data-testid="fold-body"]')!.style
        .display,
    ).toBe('none')

    await pickFront()
    const warn = text('[data-testid="wizard-not-matched"]')
    expect(warn).toContain('没有匹配到 ADO 项目')
    expect(warn).toContain('设置')
    expect(q('[data-testid="wizard-goto-settings"]')).not.toBeNull()
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)

    await click('[data-testid="wizard-advanced-repo"] [data-testid="fold-toggle"]')
    expect(
      q('[data-testid="wizard-advanced-repo"] [data-testid="fold-toggle"]')!.getAttribute(
        'aria-expanded',
      ),
    ).toBe('true')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(false)
    // 没有 ADO 关联：分支步骤不请求远端，提示手动输入
    await click('[data-testid="wizard-next"]')
    expect(discoverCalls(server, 'branches')).toHaveLength(0)
    expect(q('[data-testid="wizard-branches-manual"]')).not.toBeNull()
    await typeInto('input[placeholder="release/1.0"]', 'main')
    await click('[data-testid="wizard-add-extra-branch"]')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(false)
    await b.done()
  })

  it('pat_missing：给中文可操作提示和“去设置”，不进入下一步', async () => {
    const server = makeServer({
      repo: () => errBody(409, 'pat_missing', 'raw english'),
    })
    const b = await bootTasks(server)
    await openWizard(b)
    await pickFront()
    const err = text('[data-testid="wizard-discover-error"]')
    expect(err).toContain('PAT')
    expect(err).toContain('设置')
    expect(err).not.toContain('raw english')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    await b.done()
  })

  it.each([
    ['not_git_repo', '不是 Git 仓库'],
    ['no_remote', '没有配置远端'],
    ['remote_not_ado', '不是 Azure DevOps'],
    ['ado_unreachable', '连不上 ADO'],
    ['ado_not_found', '找不到'],
  ])('识别错误 %s 给出中文提示', async (code, expected) => {
    const server = makeServer({
      repo: () => errBody(code === 'ado_not_found' ? 404 : 422, code, 'x'),
    })
    const b = await bootTasks(server)
    await openWizard(b)
    await pickFront()
    expect(text('[data-testid="wizard-discover-error"]')).toContain(expected)
    await b.done()
  })

  it('环境默认全部不勾选；没勾环境的目标不会被加入，勾了环境才成目标（目标可就地改名）', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openWizard(b)
    await toTargets()
    // 添加表单里还没选构建定义时没有环境可勾；选了之后 8 个环境一个都没勾（含“正式环境”）
    expect(qa('[data-testid^="adder-env-"]')).toHaveLength(0)
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    expect(text('[data-testid="wizard-targets-count"]')).toContain('已加入 0 个目标')
    {
      const bsel = q<HTMLSelectElement>('[data-testid="adder-build"]')!
      bsel.value = '12'
      bsel.dispatchEvent(new Event('change', { bubbles: true }))
      await settle()
    }
    const all = qa<HTMLInputElement>('[data-testid^="adder-env-"]')
    expect(all).toHaveLength(8)
    expect(all.filter((e) => e.checked)).toHaveLength(0)
    // 一个环境都没勾：不能添加，也不会有目标
    expect(btn('[data-testid="adder-add-btn"]').disabled).toBe(true)
    expect(text('[data-testid="adder-problem"]')).toContain('至少勾选一个环境')
    // 勾了正式环境再取消：仍然没有目标
    await check(`[data-testid="adder-env-${PROD_ID}"]`)
    await check(`[data-testid="adder-env-${PROD_ID}"]`, false)
    expect(text('[data-testid="wizard-targets-count"]')).toContain('已加入 0 个目标')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)

    // 勾一个环境添加成目标；在已加入列表里就地改名
    await addTarget('21', ['1'])
    expect(text('[data-testid="wizard-targets-count"]')).toContain('已加入 1 个目标')
    const nameInput = q<HTMLInputElement>('[data-testid="wizard-added-target-0"] input')!
    nameInput.value = '前台测试'
    nameInput.dispatchEvent(new Event('input', { bubbles: true }))
    await settle()
    await click('[data-testid="wizard-next"]') // → 队列
    await click('[data-testid="wizard-next"]') // → 命令
    expect(qa('[data-testid^="wizard-draft-include-"]')).toHaveLength(1)
    expect(q<HTMLInputElement>('[data-testid="wizard-draft-0"] input[type="text"]')!.value).toBe(
      'main → 前台测试',
    )
    await b.done()
  })

  it('没有 Release 定义关联时提示，并可在高级里手填目标', async () => {
    const server = makeServer()
    const orig = server.fetchImpl
    const wrapped = (async (r: Request) => {
      if (new URL(r.url).pathname === '/api/release-configs/discover/targets')
        return json({
          builds: [{ id: '11', name: 'CI', kind: 'build' }],
          releases: [],
          suggested_targets: [],
        })
      return orig(r)
    }) as unknown as typeof fetch
    const b = await boot({ path: '/tasks', fetchImpl: wrapped })
    b.sock.emit(hello())
    await settle()
    await openWizard(b)
    await toTargets()
    expect(text('[data-testid="adder-none"]')).toContain('没有关联 Release 的构建定义')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    await click('[data-testid="wizard-advanced-targets"] [data-testid="fold-toggle"]')
    await click('[data-testid="wizard-add-manual-target"]')
    await typeByLabel('构建定义 ID', '11')
    // 没有环境前不能继续，补齐构建、Release、环境后才行
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    await typeByLabel('Release 定义 ID', '21')
    await typeByLabel('环境 ID', '1')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(false)
    await b.done()
  })

  it('Agent 队列为空：提示可留空，且可以继续', async () => {
    const server = makeServer({ queues: [] })
    const b = await bootTasks(server)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await click('[data-testid="wizard-next"]')
    expect(text('[data-testid="queue-empty"]')).toContain('该项目没有可用队列，可留空')
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(false)
    await b.done()
  })

  it('命令草稿：每个分支 × 目标一条；取消勾选的不会创建，全部取消则不能继续', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openWizard(b)
    await pickFront()
    await click('[data-testid="wizard-next"]')
    await check('[data-testid="branch-pick-develop"]')
    await click('[data-testid="wizard-next"]')
    await addTarget('21', ['1'])
    await addTarget('22', ['2'])
    await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-next"]')
    // 2 分支 × 2 目标 = 4 条
    expect(qa('[data-testid^="wizard-draft-include-"]')).toHaveLength(4)
    // 取消 develop → 后台发布（第 4 条），给第 1 条填 TG 命令名
    await check('[data-testid="wizard-draft-include-3"]', false)
    const tg = qa<HTMLInputElement>('[data-testid="wizard-draft-0"] input[type="text"]')[1]!
    tg.value = 'pub_front'
    tg.dispatchEvent(new Event('input', { bubbles: true }))
    await settle()
    await click('[data-testid="wizard-next"]')
    expect(btn('[data-testid="wizard-save"]').textContent).toContain('3 条命令')
    await click('[data-testid="wizard-save"]')
    const cmds = server.calls.filter((c) => c.method === 'POST' && /\/commands$/.test(c.path))
    expect(cmds.map((c) => (c.body as { name: string }).name)).toEqual([
      'main → 前台发布',
      'main → 后台发布',
      'develop → 前台发布',
    ])
    expect((cmds[0]!.body as { tg_command: string }).tg_command).toBe('pub_front')
    await b.done()
  })

  it('命令草稿全部取消勾选：下一步不可用并提示至少保留一条', async () => {
    const server2 = makeServer()
    const b2 = await bootTasks(server2)
    await openWizard(b2)
    await toTargets()
    await addTarget('21', ['1'])
    await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-next"]')
    await check('[data-testid="wizard-draft-include-0"]', false)
    expect(btn('[data-testid="wizard-next"]').disabled).toBe(true)
    expect(q('[data-testid="wizard-drafts-none"]')).not.toBeNull()
    await b2.done()
  })

  it('保存部分失败：配置已建但命令失败时停在确认页并提示，重试只补建剩余命令、不重复建配置', async () => {
    let failCmd = 0
    const server = makeServer({
      onWrite: (c) => {
        if (/\/commands$/.test(c.path) && (c.body as { name: string }).name.startsWith('develop')) {
          failCmd += 1
          if (failCmd === 1) return errBody(422, 'validation_error', 'TG 指令已存在')
        }
        return null
      },
    })
    const b = await bootTasks(server)
    await openWizard(b)
    await pickFront()
    await click('[data-testid="wizard-next"]')
    await check('[data-testid="branch-pick-develop"]')
    await click('[data-testid="wizard-next"]')
    await addTarget('21', ['1'])
    await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-save"]')

    // 停在确认页，明确说明配置已建、还差几条
    expect(q('[data-testid="release-wizard"]')).not.toBeNull()
    const partial = text('[data-testid="wizard-partial-error"]')
    expect(partial).toContain('配置已创建')
    expect(partial).toContain('已创建 1 条')
    expect(partial).toContain('还差 1 条')
    expect(partial).toContain('TG 命令已被别的命令使用')
    expect(btn('[data-testid="wizard-save"]').textContent).toContain('重试创建剩余 1 条命令')
    // 配置已落库，前面的步骤不可再退（只能退到命令步）
    const cfgPosts = () =>
      server.calls.filter((c) => c.method === 'POST' && c.path === '/api/release-configs')
    expect(cfgPosts()).toHaveLength(1)

    await click('[data-testid="wizard-save"]')
    expect(cfgPosts()).toHaveLength(1)
    const okCmds = server.calls.filter((c) => c.method === 'POST' && /\/commands$/.test(c.path))
    // main 成功 1 次，develop 失败 1 次 + 重试成功 1 次，没有重复建 main
    expect(okCmds.map((c) => (c.body as { name: string }).name)).toEqual([
      'main → 前台发布',
      'develop → 前台发布',
      'develop → 前台发布',
    ])
    expect(q('[data-testid="release-wizard"]')).toBeNull()
    await b.done()
  })

  it('保存失败（配置没建成）：显示错误，仍在确认页，可以直接再点保存', async () => {
    let n = 0
    const server = makeServer({
      onWrite: (c) => {
        if (c.path === '/api/release-configs' && c.method === 'POST' && n++ === 0)
          return errBody(409, 'revision_conflict', 'x')
        return null
      },
    })
    const b = await bootTasks(server)
    await openWizard(b)
    await toTargets()
    await addTarget('21', ['1'])
    await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-save"]')
    expect(text('[data-testid="wizard-save-error"]')).toContain('已重新读取最新内容')
    expect(q('[data-testid="wizard-partial-error"]')).toBeNull()
    await click('[data-testid="wizard-save"]')
    expect(
      server.calls.filter((c) => c.method === 'POST' && c.path === '/api/release-configs'),
    ).toHaveLength(2)
    expect(q('[data-testid="release-wizard"]')).toBeNull()
    await b.done()
  })
})

describe('保存后按内容匹配服务端返回的分支与目标', () => {
  async function runWith(mutate: (item: ReleaseView) => void) {
    const server = makeServer()
    const orig = server.fetchImpl
    const wrapped = (async (r: Request) => {
      const res = await orig(r)
      if (new URL(r.url).pathname === '/api/release-configs/new-cfg' && r.method === 'GET') {
        const body = (await res.json()) as { item: ReleaseView; revision: number }
        mutate(body.item)
        return json(body)
      }
      return res
    }) as unknown as typeof fetch
    const b = await boot({ path: '/tasks', fetchImpl: wrapped })
    b.sock.emit(hello())
    await settle()
    await openWizard(b)
    await pickFront()
    await click('[data-testid="wizard-next"]')
    await check('[data-testid="branch-pick-develop"]')
    await click('[data-testid="wizard-next"]')
    await addTarget('21', ['1'])
    await addTarget('22', ['1'])
    for (let i = 0; i < 3; i++) await click('[data-testid="wizard-next"]')
    await click('[data-testid="wizard-save"]')
    return { server, b }
  }
  const cmdBodies = (s: ReturnType<typeof makeServer>) =>
    s.calls
      .filter((c) => c.method === 'POST' && /\/commands$/.test(c.path))
      .map((c) => c.body as { name: string; branch_id: string; target_ids: string[] })

  it('服务端返回的分支和目标顺序被打乱：命令仍关联到各自正确的 id', async () => {
    const { server, b } = await runWith((item) => {
      item.branches!.reverse()
      item.targets!.reverse()
    })
    const cmds = cmdBodies(server)
    expect(cmds).toHaveLength(4)
    const by = Object.fromEntries(cmds.map((c) => [c.name, c]))
    // 分支 main=nb-0、develop=nb-1；目标 前台=nt-0、后台=nt-1（按创建顺序编号）
    expect(by['main → 前台发布']).toMatchObject({ branch_id: 'nb-0', target_ids: ['nt-0'] })
    expect(by['main → 后台发布']).toMatchObject({ branch_id: 'nb-0', target_ids: ['nt-1'] })
    expect(by['develop → 前台发布']).toMatchObject({ branch_id: 'nb-1', target_ids: ['nt-0'] })
    expect(by['develop → 后台发布']).toMatchObject({ branch_id: 'nb-1', target_ids: ['nt-1'] })
    await b.done()
  })

  it('匹配不唯一：不猜，停在可重试状态，一条命令都不创建', async () => {
    const { server, b } = await runWith((item) => {
      item.branches!.push({ ...item.branches![0]!, id: 'dup' })
    })
    expect(cmdBodies(server)).toHaveLength(0)
    expect(text('[data-testid="wizard-partial-error"]')).toContain('匹配到 2 个')
    expect(btn('[data-testid="wizard-save"]').disabled).toBe(false)
    await b.done()
  })
})

describe('编辑已有配置：从 ADO 选择，不再手填 ID', () => {
  async function openEdit(b: Awaited<ReturnType<typeof bootTasks>>) {
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await settle()
  }

  it('高级（手动填写）默认收起，ID 类字段只在里面；打开编辑器不请求任何发现接口', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    expect(server.calls.filter((c) => c.path.includes('/discover/'))).toHaveLength(0)
    const fold = q('[data-testid="edit-advanced"]')!
    expect(fold.querySelector('[data-testid="fold-toggle"]')!.getAttribute('aria-expanded')).toBe(
      'false',
    )
    expect(fold.querySelector<HTMLElement>('[data-testid="fold-body"]')!.style.display).toBe('none')
    // 可见区没有 ID 输入框；ID 输入框都在折叠区里
    const idInputs = qa<HTMLLabelElement>('label.text-input').filter((l) =>
      /ID/.test(l.querySelector('.sr-only')?.textContent ?? ''),
    )
    expect(idInputs.length).toBeGreaterThan(0)
    for (const l of idInputs) expect(fold.contains(l)).toBe(true)
    // 仓库信息只读展示
    expect(text('[data-testid="repo-info"]')).toContain('CG_Vue_Front')
    expect(text('[data-testid="repo-info"]')).toContain('已关联')
    await b.done()
  })

  it('从 ADO 添加目标：表单式；环境默认不勾；同一构建+Release 的已有目标不会被隐藏；添加后面板自动收起并高亮新卡片标“未保存”、保存时新目标不带 id', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="add-remote-targets-btn"]')
    expect(discoverCalls(server, 'targets')).toHaveLength(1)
    expect(text('[data-testid="remote-targets-box"]')).not.toContain('已在配置里')
    expect(text('[data-testid="remote-targets-box"]')).not.toContain('不再列出')
    // 已有目标正在用的构建 11 仍然可选
    const bsel = q<HTMLSelectElement>('[data-testid="adder-build"]')!
    expect(bsel.querySelector('option[value="11"]')!.hasAttribute('disabled')).toBe(false)
    bsel.value = '12'
    bsel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    const all = qa<HTMLInputElement>('[data-testid^="adder-env-"]')
    expect(all).toHaveLength(8)
    expect(all.some((e) => e.checked)).toBe(false)
    expect(btn('[data-testid="adder-add-btn"]').disabled).toBe(true)

    await addTarget('22', ['1', '4'])
    // 添加成功后面板自动收起，新目标立即出现在下方列表，高亮并标“未保存”
    expect(q('[data-testid="remote-targets-box"]')).toBeNull()
    expect(q('[data-testid="target-edit-1"]')).not.toBeNull()
    expect(q('[data-testid="target-edit-1"]')!.getAttribute('data-added')).toBe('true')
    expect(text('[data-testid="target-unsaved-1"]')).toContain('未保存')
    expect(q('[data-testid="target-unsaved-0"]')).toBeNull()
    await click('[data-testid="save-task-btn"]')
    const patch = server.calls.find((c) => c.method === 'PATCH')!
    const targets = (patch.body as { targets: Array<Record<string, unknown>> }).targets
    expect(targets.map((t) => t.id)).toEqual(['tg-1', undefined])
    expect(targets[1]).toMatchObject({
      name: '后台发布',
      release_id: '22',
      build_id: '12',
      release_stage_ids: ['1', '4'],
      release_stage_names: ['开发环境', 'UAT'],
    })
    await b.done()
  })

  it('同一个（构建, Release）可以添加多个目标，只是环境不同；每次添加后面板收起，再点开继续添加', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    // 已有目标用的就是 构建 11 + Release 21（环境 2）；再加两个不同环境的目标
    await click('[data-testid="add-remote-targets-btn"]')
    await addTarget('21', ['1'])
    expect(q('[data-testid="remote-targets-box"]')).toBeNull()
    await click('[data-testid="add-remote-targets-btn"]')
    const bsel = q<HTMLSelectElement>('[data-testid="adder-build"]')!
    bsel.value = '11'
    bsel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    await check('[data-testid="adder-env-8"]')
    // 同名已存在，默认名自动加环境名
    expect(q<HTMLInputElement>('[data-testid="adder-name"] input')!.value).toBe(
      '前台发布 · 正式环境',
    )
    await click('[data-testid="adder-add-btn"]')
    await click('[data-testid="save-task-btn"]')
    const targets = (
      server.calls.find((c) => c.method === 'PATCH')!.body as {
        targets: Array<Record<string, unknown>>
      }
    ).targets
    expect(targets).toHaveLength(3)
    expect(targets.map((t) => t.release_stage_ids)).toEqual([['2'], ['1'], ['8']])
    expect(targets.slice(1).every((t) => t.build_id === '11' && t.release_id === '21')).toBe(true)
    expect(new Set(targets.map((t) => t.name)).size).toBe(3)
    await b.done()
  })

  it('重名与完全相同：重名提示并禁止添加；构建+Release+环境集合都相同提示“已存在相同目标”', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="add-remote-targets-btn"]')
    const bsel = q<HTMLSelectElement>('[data-testid="adder-build"]')!
    bsel.value = '11'
    bsel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    // 与已有目标（环境 2）完全相同
    await check('[data-testid="adder-env-2"]')
    expect(text('[data-testid="adder-problem"]')).toContain('已存在相同目标')
    expect(btn('[data-testid="adder-add-btn"]').disabled).toBe(true)
    // 换个环境、但名字手动改成已有目标的名字：重名
    await check('[data-testid="adder-env-2"]', false)
    await check('[data-testid="adder-env-3"]')
    await typeInto('[data-testid="adder-name"] input', '前台发布')
    expect(text('[data-testid="adder-problem"]')).toContain('已有同名目标')
    expect(btn('[data-testid="adder-add-btn"]').disabled).toBe(true)
    await typeInto('[data-testid="adder-name"] input', '前台发布 预发')
    expect(q('[data-testid="adder-problem"]')).toBeNull()
    expect(btn('[data-testid="adder-add-btn"]').disabled).toBe(false)
    await b.done()
  })

  it('没有被 Release 引用的构建定义：列出并标注，但不可选', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="add-remote-targets-btn"]')
    const opt = q<HTMLOptionElement>('[data-testid="adder-build"] option[value="235"]')!
    expect(opt.disabled).toBe(true)
    expect(opt.textContent).toContain('CG_Vue_Front_Admin')
    expect(opt.textContent).toContain('没有关联的 Release，无法发布')
    expect(q<HTMLOptionElement>('[data-testid="adder-build"] option[value="236"]')!.disabled).toBe(
      true,
    )
    await b.done()
  })

  it('仓库只有一个（构建, Release）且已有目标用了它：仍能选同一构建/Release、勾另一个环境添加成功（如已有“测试”再加“正式”）', async () => {
    const orig = makeServer()
    const wrapped = (async (r: Request) =>
      new URL(r.url).pathname === '/api/release-configs/discover/targets'
        ? json({
            builds: [{ id: '11', name: '新优惠构建', kind: 'pipeline' }],
            releases: [
              {
                id: '21',
                name: '新优惠',
                build_definition_ids: ['11'],
                environments: [
                  { id: '2', name: '新优惠-测试环境' },
                  { id: '8', name: '新优惠-正式环境' },
                ],
              },
            ],
            suggested_targets: [],
          })
        : orig.fetchImpl(r)) as unknown as typeof fetch
    const b = await boot({ path: '/tasks', fetchImpl: wrapped })
    b.sock.emit(hello())
    await settle()
    await openEdit(b)
    await click('[data-testid="add-remote-targets-btn"]')
    const box = text('[data-testid="remote-targets-box"]')
    expect(box).not.toContain('不再列出')
    expect(box).not.toContain('没有可以新增的目标')
    expect(q('[data-testid="adder-none"]')).toBeNull()
    await addTarget('21', ['8'], '正式')
    await click('[data-testid="save-task-btn"]')
    const targets = (
      orig.calls.find((c) => c.method === 'PATCH')!.body as {
        targets: Array<Record<string, unknown>>
      }
    ).targets
    expect(targets).toHaveLength(2)
    expect(targets[1]).toMatchObject({
      name: '正式',
      build_id: '11',
      release_id: '21',
      release_stage_ids: ['8'],
      release_stage_names: ['新优惠-正式环境'],
    })
    await b.done()
  })

  it('从远端添加分支：已有分支标为已添加，新增分支带空规则、不带 id；队列可换成下拉里的项', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="add-remote-branches-btn"]')
    expect(discoverCalls(server, 'branches')).toHaveLength(1)
    expect(q<HTMLInputElement>('[data-testid="branch-pick-main"]')!.disabled).toBe(true)
    await check('[data-testid="branch-pick-develop"]')
    await click('[data-testid="confirm-remote-branches-btn"]')
    expect(q('[data-testid="branch-edit-1"]')).not.toBeNull()

    expect(discoverCalls(server, 'queues')).toHaveLength(0)
    await click('[data-testid="change-queue-btn"]')
    expect(discoverCalls(server, 'queues')).toHaveLength(1)
    const sel = q<HTMLSelectElement>('[data-testid="queue-select-input"]')!
    expect(sel.value).toBe('5')
    sel.value = '6'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()

    await click('[data-testid="save-task-btn"]')
    const patch = server.calls.find((c) => c.method === 'PATCH')!
    const body = patch.body as {
      branches: Array<Record<string, unknown>>
      agent_queue_id: string
      agent_queue_name: string
    }
    expect(body.branches.map((x) => x.build_branch)).toEqual(['main', 'develop'])
    expect('id' in body.branches[1]!).toBe(false)
    expect(body.agent_queue_id).toBe('6')
    expect(body.agent_queue_name).toBe('备用队列')
    await b.done()
  })

  it('重新识别：显示识别结果，与当前一致时不改；识别失败给提示', async () => {
    let fail = false
    const server = makeServer({
      repo: (path) =>
        fail ? errBody(502, 'ado_unreachable', 'x') : { ...FOUND, local_repo_path: path },
    })
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="rediscover-btn"]')
    expect(text('[data-testid="rediscover-result"]')).toContain('与当前关联一致')
    expect(q('[data-testid="adopt-discovery-btn"]')).toBeNull()
    fail = true
    await click('[data-testid="rediscover-btn"]')
    expect(text('[data-testid="rediscover-error"]')).toContain('连不上 ADO')
    await b.done()
  })
})

describe('编辑已有目标：环境与构建/Release 配对可改', () => {
  async function openEdit(b: Awaited<ReturnType<typeof bootTasks>>) {
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await settle()
  }
  const patchTargets = (s: ReturnType<typeof makeServer>) =>
    (
      s.calls.find((c) => c.method === 'PATCH')!.body as {
        targets: Array<Record<string, unknown>>
      }
    ).targets

  it('点“修改”才读 discover/targets；列出该 Release 全部环境，当前已选勾上；加减后 PATCH 正确且 id 不变，ids 与 names 等长', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    expect(discoverCalls(server, 'targets')).toHaveLength(0)
    await click('[data-testid="edit-target-btn-0"]')
    expect(discoverCalls(server, 'targets')).toHaveLength(1)
    const boxes = qa<HTMLInputElement>('[data-testid^="target-stage-0-"]')
    expect(boxes).toHaveLength(8)
    expect(boxes.filter((e) => e.checked).map((e) => e.dataset.testid)).toEqual([
      'target-stage-0-2',
    ])
    await check('[data-testid="target-stage-0-3"]')
    await check('[data-testid="target-stage-0-2"]', false)
    await check('[data-testid="target-stage-0-8"]')
    // 摘要里的环境标签按新选择显示
    expect(text('[data-testid="target-edit-0"] .env-tags')).toContain('预发环境')
    expect(text('[data-testid="target-edit-0"] .env-tags')).not.toContain('测试环境')
    await click('[data-testid="edit-target-btn-0"]') // 完成
    expect(q('[data-testid="target-editor-0"]')).toBeNull()
    await click('[data-testid="save-task-btn"]')
    const t = patchTargets(server)[0]!
    expect(t.id).toBe('tg-1')
    expect(t.release_stage_ids).toEqual(['3', '8'])
    expect(t.release_stage_names).toEqual(['预发环境', '正式环境'])
    await b.done()
  })

  it('至少保留一个环境：全取消后该行提示并禁用保存', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="edit-target-btn-0"]')
    await check('[data-testid="target-stage-0-2"]', false)
    expect(text('[data-testid="target-problem-0"]')).toContain('至少保留一个环境')
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(true)
    await check('[data-testid="target-stage-0-4"]')
    expect(q('[data-testid="target-problem-0"]')).toBeNull()
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(false)
    await b.done()
  })

  it('换构建/Release 定义（先构建后 Release）后环境清空、不默认勾；重新勾选后保存，目标 id 不变', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="edit-target-btn-0"]')
    expect(q<HTMLSelectElement>('[data-testid="target-build-0"]')!.value).toBe('11')
    expect(q<HTMLSelectElement>('[data-testid="target-release-0"]')!.value).toBe('21')
    // 没被引用的构建定义不可选
    expect(
      q<HTMLOptionElement>('[data-testid="target-build-0"] option[value="235"]')!.disabled,
    ).toBe(true)
    const sel = q<HTMLSelectElement>('[data-testid="target-build-0"]')!
    sel.value = '12'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    // 构建 12 只有一个 Release（22）：自动选中
    expect(q<HTMLSelectElement>('[data-testid="target-release-0"]')!.value).toBe('22')
    const boxes = qa<HTMLInputElement>('[data-testid^="target-stage-0-"]')
    expect(boxes).toHaveLength(8)
    expect(boxes.some((e) => e.checked)).toBe(false)
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(true)
    await check('[data-testid="target-stage-0-1"]')
    await click('[data-testid="save-task-btn"]')
    const t = patchTargets(server)[0]!
    expect(t).toMatchObject({
      id: 'tg-1',
      build_id: '12',
      release_id: '22',
      release_name: '后台发布',
      release_stage_ids: ['1'],
      release_stage_names: ['开发环境'],
    })
    await b.done()
  })

  it('已保存的环境在 ADO 里已不存在：仍显示并标注，可取消勾选；不动它则原样保留', async () => {
    const tweak = (c: ReleaseView) => {
      const t = c.targets![0]!
      t.release_stage_ids = ['2', '99']
      t.release_stage_names = ['测试环境', '旧环境']
    }
    const server = makeServer({ tweakExisting: tweak })
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="edit-target-btn-0"]')
    expect(text('[data-testid="target-stage-gone-0-99"]')).toContain('ADO 中已不存在')
    expect(q<HTMLInputElement>('[data-testid="target-stage-0-99"]')!.checked).toBe(true)
    await check('[data-testid="target-stage-0-99"]', false)
    await click('[data-testid="save-task-btn"]')
    const t = patchTargets(server)[0]!
    expect(t.release_stage_ids).toEqual(['2'])
    expect(t.release_stage_names).toEqual(['测试环境'])
    await b.done()
  })

  it('ADO 不可达：提示原因并引导到高级手填，手填字段仍可用', async () => {
    const orig = makeServer()
    const wrapped = (async (r: Request) =>
      new URL(r.url).pathname === '/api/release-configs/discover/targets'
        ? errBody(502, 'ado_unreachable', 'x')
        : orig.fetchImpl(r)) as unknown as typeof fetch
    const b = await boot({ path: '/tasks', fetchImpl: wrapped })
    b.sock.emit(hello())
    await settle()
    await openEdit(b)
    await click('[data-testid="edit-target-btn-0"]')
    const err = text('[data-testid="target-editor-error-0"]')
    expect(err).toContain('连不上 ADO')
    expect(err).toContain('高级')
    expect(q('[data-testid="target-pair-0"]')).toBeNull()
    // 打开高级后仍能手填环境
    const fold = q('[data-testid="edit-advanced"] [data-testid="fold-toggle"]')!
    expect(fold.getAttribute('aria-expanded')).toBe('false')
    await click('[data-testid="target-editor-error-0"] button:last-child')
    expect(fold.getAttribute('aria-expanded')).toBe('true')
    await typeByLabel('环境 ID', '2, 3')
    await click('[data-testid="save-task-btn"]')
    expect(orig.calls.find((c) => c.method === 'PATCH')).toBeDefined()
    await b.done()
  })

  it('被命令使用的目标：修改区顶部提示会影响哪些命令，但不阻止修改；删除仍被禁用', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="edit-target-btn-0"]')
    expect(text('[data-testid="target-impact-0"]')).toContain('修改会影响命令：发测试')
    expect(btn('[data-testid="remove-target-0"]').disabled).toBe(true)
    expect(text('[data-testid="target-used-0"]')).toContain('不能删除')
    await check('[data-testid="target-stage-0-5"]')
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(false)
    await b.done()
  })
})

describe('编辑已有配置：保存可用性、未保存标记与成功反馈', () => {
  async function openEdit(b: Awaited<ReturnType<typeof bootTasks>>) {
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await settle()
  }
  const noPath = (c: ReleaseView) => {
    c.local_repo_path = ''
  }
  const patches = (s: ReturnType<typeof makeServer>) => s.calls.filter((c) => c.method === 'PATCH')

  it('local_repo_path 为空的已有配置（迁移数据）：改目标名后保存可用，PATCH 成功并给成功反馈', async () => {
    const server = makeServer({ tweakExisting: noPath })
    const b = await bootTasks(server)
    await openEdit(b)
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(false)
    expect(q('[data-testid="save-blockers"]')).toBeNull()
    await typeInto('[data-testid="target-edit-0"] input[type="text"]', '前台发布改')
    expect(text('[data-testid="target-unsaved-0"]')).toContain('未保存')
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(false)
    await click('[data-testid="save-task-btn"]')
    expect(patches(server)).toHaveLength(1)
    const body = patches(server)[0]!.body as {
      local_repo_path: string
      targets: Array<{ id: string; name: string }>
    }
    expect(body.local_repo_path).toBe('')
    expect(body.targets[0]).toMatchObject({ id: 'tg-1', name: '前台发布改' })
    // 保存成功：Sheet 关闭，页面给明确反馈
    expect(q('[data-testid="task-edit-sheet"]')).toBeNull()
    expect(b.wrapper.get('[data-testid="config-saved-notice"]').text()).toContain('已保存')
    await b.done()
  })

  it('无本地路径但分支已有 Git 规则：规则区整块禁用并只读显示，按钮旁写原因；“清空这些规则”后可保存，“选择本地仓库”聚焦路径', async () => {
    const server = makeServer({
      tweakExisting: (c) => {
        c.local_repo_path = ''
        c.branches![0]!.update_branches = ['develop']
        c.branches![0]!.push_branches = ['main']
      },
    })
    const b = await bootTasks(server)
    await openEdit(b)
    // 整块禁用态：只有一份说明，不再每个分支各报一遍红字
    expect(text('[data-testid="rules-disabled"]')).toContain('Git 规则')
    expect(q('[data-testid="gitrules-nopath-0"]')).toBeNull()
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(true)
    expect(text('[data-testid="gitrules-nopath"]')).toContain('选择本地仓库')
    await click('[data-testid="toggle-branch-0"]')
    // 已有规则只读显示（有标签，没有编辑控件）
    expect(text('[data-testid="branch-0-update-tag-develop"]')).toContain('develop')
    expect(q('[data-testid="branch-0-update-toggle"]')).toBeNull()
    expect(q('[data-testid="branch-0-merge-add"]')).toBeNull()
    // 只读时不会去读远端分支
    expect(discoverCalls(server, 'branches')).toHaveLength(0)
    await click('[data-testid="choose-local-repo-btn"]')
    expect(document.activeElement).toBe(q('[data-testid="local-path-input"] input'))
    await click('[data-testid="clear-rules-btn"]')
    expect(q('[data-testid="branch-0-update-tag-develop"]')).toBeNull()
    expect(q('[data-testid="clear-rules-btn"]')).toBeNull()
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(false)
    await click('[data-testid="save-task-btn"]')
    const body = server.calls.find((c) => c.method === 'PATCH')!.body as {
      branches: Array<{ update_branches: string[]; push_branches: string[] }>
    }
    expect(body.branches[0]).toMatchObject({ update_branches: [], push_branches: [] })
    await b.done()
  })

  const scenarios: Array<
    [string, string, (b: Awaited<ReturnType<typeof bootTasks>>) => Promise<void>]
  > = [
    ['配置名称为空', 'name-empty', async () => typeByLabel('配置名称', '')],
    [
      '分支重复',
      'branches-invalid',
      async () => {
        await click('[data-testid="add-branch-btn"]')
        await typeByLabel('分支 2 构建分支', 'main')
      },
    ],
    [
      '合并规则没选完整',
      'merges-invalid',
      async () => {
        await click('[data-testid="toggle-branch-0"]')
        await click('[data-testid="branch-0-merge-add"]')
      },
    ],
    [
      '目标名称为空',
      'targets-invalid',
      async () => typeInto('[data-testid="target-edit-0"] input[type="text"]', ''),
    ],
    ['手动添加的空目标', 'targets-invalid', async () => click('[data-testid="add-target-btn"]')],
    [
      '目标环境全部取消',
      'targets-invalid',
      async () => {
        await click('[data-testid="edit-target-btn-0"]')
        await check('[data-testid="target-stage-0-2"]', false)
      },
    ],
  ]
  it.each(scenarios)('保存禁用的每个原因都在按钮旁可见：%s', async (_n, testid, act) => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await act(b)
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(true)
    const box = q('[data-testid="save-blockers"]')
    expect(box).not.toBeNull()
    expect((box!.textContent ?? '').trim().length).toBeGreaterThan(0)
    expect(text(`[data-testid="${testid}"]`).trim().length).toBeGreaterThan(0)
    await b.done()
  })

  it('空目标的原因旁给“去修改”：点了自动展开高级区', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="add-target-btn"]')
    const fold = q('[data-testid="edit-advanced"] [data-testid="fold-toggle"]')!
    expect(fold.getAttribute('aria-expanded')).toBe('false')
    await click('[data-testid="targets-invalid"] button')
    expect(fold.getAttribute('aria-expanded')).toBe('true')
    await b.done()
  })

  it('改了构建定义：点“完成”收起后摘要立刻显示新构建/Release/环境，并标“未保存”；保存失败给原因，成功后关闭并提示', async () => {
    let fail = true
    const server = makeServer({
      onWrite: (c) => (c.method === 'PATCH' && fail ? errBody(500, 'internal', '后端挂了') : null),
    })
    const b = await bootTasks(server)
    await openEdit(b)
    expect(q('[data-testid="target-unsaved-0"]')).toBeNull()
    await click('[data-testid="edit-target-btn-0"]')
    const sel = q<HTMLSelectElement>('[data-testid="target-build-0"]')!
    sel.value = '12'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    await settle()
    await check('[data-testid="target-stage-0-8"]')
    await click('[data-testid="edit-target-btn-0"]') // 完成
    const card = text('[data-testid="target-edit-0"]')
    expect(card).toContain('构建 后台发布')
    expect(card).toContain('后台发布')
    expect(card).toContain('正式环境')
    expect(card).not.toContain('测试环境')
    expect(card).toContain('未保存')

    await click('[data-testid="save-task-btn"]')
    // 失败：仍在 Sheet 里，给错误原因，标记仍在
    expect(q('[data-testid="task-edit-error"]')).not.toBeNull()
    expect(text('[data-testid="target-unsaved-0"]')).toContain('未保存')
    fail = false
    await click('[data-testid="save-task-btn"]')
    expect(q('[data-testid="task-edit-sheet"]')).toBeNull()
    expect(b.wrapper.get('[data-testid="config-saved-notice"]').text()).toContain('已保存')
    await b.done()
  })
})

describe('Git 规则选择器与本地仓库路径', () => {
  async function openEdit(b: Awaited<ReturnType<typeof bootTasks>>) {
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await settle()
  }
  const patchBody = (s: ReturnType<typeof makeServer>) =>
    s.calls.find((c) => c.method === 'PATCH')!.body as {
      local_repo_path: string
      branches: Array<{
        update_branches: string[]
        push_branches: string[]
        merges: Array<{ source: string; target: string }>
      }>
    }

  it('规则选择器：懒加载远端分支；更新/推送用标签多选（可搜索、可手输），合并规则一行源 → 目标，可增删和上下移，保存按顺序提交', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    expect(discoverCalls(server, 'branches')).toHaveLength(0)
    await click('[data-testid="toggle-branch-0"]')
    expect(discoverCalls(server, 'branches')).toHaveLength(1)
    expect(text('[data-testid="branch-0-order"]')).toContain('更新 → 按顺序合并 → 推送 → 构建')
    // 空时显示“未设置”，没有会被误认成真值的 placeholder
    expect(text('[data-testid="branch-0-update-none"]')).toBe('未设置')
    expect(text('[data-testid="branch-0-push-none"]')).toBe('未设置')
    expect(text('[data-testid="branch-0-merge-none"]')).toBe('未设置')
    expect(qa('[placeholder="main"], [placeholder="dev:main, feature:dev"]')).toHaveLength(0)

    // 更新分支：搜索后勾选，再手输一个远端没有的名字
    await click('[data-testid="branch-0-update-toggle"]')
    await typeInto(
      '[data-testid="branch-picker"] input[type="search"], [data-testid="branch-picker"] input',
      'feature/lo',
    )
    expect(qa('[data-testid^="branch-pick-"]')).toHaveLength(1)
    await check('[data-testid="branch-pick-feature/login"]')
    await typeByLabel('分支 1 更新分支 其他分支名', 'my-branch')
    await click('[data-testid="branch-0-update-extra-add"]')
    expect(q('[data-testid="branch-0-update-tag-feature/login"]')).not.toBeNull()
    expect(q('[data-testid="branch-0-update-tag-my-branch"]')).not.toBeNull()
    await click('[data-testid="branch-0-update-remove-my-branch"]')
    expect(q('[data-testid="branch-0-update-tag-my-branch"]')).toBeNull()
    await click('[data-testid="branch-0-update-toggle"]') // 收起

    // 合并规则：两行，再把第 2 行上移，再删掉一行
    await click('[data-testid="branch-0-merge-add"]')
    await selectVal('[data-testid="branch-0-merge-src-0"]', 'develop')
    await selectVal('[data-testid="branch-0-merge-dst-0"]', 'main')
    await click('[data-testid="branch-0-merge-add"]')
    await selectVal('[data-testid="branch-0-merge-src-1"]', 'feature/pay')
    await selectVal('[data-testid="branch-0-merge-dst-1"]', 'develop')
    await click('[data-testid="branch-0-merge-up-1"]')
    expect(q<HTMLSelectElement>('[data-testid="branch-0-merge-src-0"]')!.value).toBe('feature/pay')
    expect(btn('[data-testid="branch-0-merge-up-0"]').disabled).toBe(true)
    expect(btn('[data-testid="branch-0-merge-down-1"]').disabled).toBe(true)

    // 推送分支
    await click('[data-testid="branch-0-push-toggle"]')
    await check('[data-testid="branch-pick-main"]')
    await click('[data-testid="branch-0-push-toggle"]')

    await click('[data-testid="save-task-btn"]')
    expect(patchBody(server).branches[0]).toMatchObject({
      update_branches: ['feature/login'],
      push_branches: ['main'],
      merges: [
        { source: 'feature/pay', target: 'develop' },
        { source: 'develop', target: 'main' },
      ],
    })
    await b.done()
  })

  it('合并规则源=目标：行内报错并禁止保存，改正后恢复；删除该行也行', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    await click('[data-testid="toggle-branch-0"]')
    await click('[data-testid="branch-0-merge-add"]')
    await selectVal('[data-testid="branch-0-merge-src-0"]', 'develop')
    await selectVal('[data-testid="branch-0-merge-dst-0"]', 'develop')
    expect(text('[data-testid="branch-0-merge-err-0"]')).toContain('不能相同')
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(true)
    expect(q('[data-testid="merges-invalid"]')).not.toBeNull()
    await selectVal('[data-testid="branch-0-merge-dst-0"]', 'main')
    expect(q('[data-testid="branch-0-merge-err-0"]')).toBeNull()
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(false)
    await selectVal('[data-testid="branch-0-merge-dst-0"]', 'develop')
    await click('[data-testid="branch-0-merge-del-0"]')
    expect(btn('[data-testid="save-task-btn"]').disabled).toBe(false)
    await b.done()
  })

  const emptyPath = (c: ReleaseView) => {
    c.local_repo_path = ''
  }

  it('自动匹配：路径为空时用同名的已登记本地仓库校验 repo_id，一致才给“填入”按钮，不自动写入；点了才填', async () => {
    const server = makeServer({ tweakExisting: emptyPath })
    const b = await bootTasks(server)
    await openEdit(b)
    const sug = text('[data-testid="local-path-suggestion"]')
    expect(sug).toContain('检测到本地仓库 /repos/front')
    // 只校验了同名的那一个候选，没有碰 PinBall
    expect(
      discoverCalls(server, 'repo').map(
        (c) => (c.body as { local_repo_path: string }).local_repo_path,
      ),
    ).toEqual(['/repos/front'])
    // 没有自动写入
    expect(q<HTMLInputElement>('[data-testid="local-path-input"] input')!.value).toBe('')
    await click('[data-testid="path-autofill-btn"]')
    expect(q<HTMLInputElement>('[data-testid="local-path-input"] input')!.value).toBe(
      '/repos/front',
    )
    expect(q('[data-testid="local-path-suggestion"]')).toBeNull()
    await click('[data-testid="save-task-btn"]')
    expect(patchBody(server).local_repo_path).toBe('/repos/front')
    await b.done()
  })

  it('自动匹配：同名候选对应的是另一个仓库（repo_id 不一致）时不给建议', async () => {
    const server = makeServer({
      tweakExisting: emptyPath,
      repo: (path) => ({
        ...FOUND,
        local_repo_path: path,
        repo_id: 'repo-other',
        repo_name: 'Other',
      }),
    })
    const b = await bootTasks(server)
    await openEdit(b)
    expect(q('[data-testid="local-path-suggestion"]')).toBeNull()
    await b.done()
  })

  it('选错仓库被拒：从已登记里选了另一个仓库的文件夹，提示“这个文件夹是 X 仓库，不是本配置的 Y”，路径不变', async () => {
    const server = makeServer({
      tweakExisting: (c) => {
        c.local_repo_path = '/repos/event'
      },
      repo: (path) =>
        path === '/repos/pinball'
          ? { ...FOUND, local_repo_path: path, repo_id: 'repo-pin', repo_name: 'PinBall' }
          : { ...FOUND, local_repo_path: path },
    })
    const b = await bootTasks(server)
    await openEdit(b)
    expect(q<HTMLInputElement>('[data-testid="local-path-input"] input')!.value).toBe(
      '/repos/event',
    )
    await selectVal('[data-testid="registered-repo-select"]', '/repos/pinball')
    const msg = text('[data-testid="local-path-rejected"]')
    expect(msg).toContain('这个文件夹是 PinBall 仓库，不是本配置的 CG_Vue_Front')
    expect(q<HTMLInputElement>('[data-testid="local-path-input"] input')!.value).toBe(
      '/repos/event',
    )
    // 选对的则采用
    await selectVal('[data-testid="registered-repo-select"]', '/repos/front')
    expect(q<HTMLInputElement>('[data-testid="local-path-input"] input')!.value).toBe(
      '/repos/front',
    )
    expect(q('[data-testid="local-path-rejected"]')).toBeNull()
    await b.done()
  })

  it('非 Tauri 环境：不显示“选择文件夹…”，只有输入框和已登记下拉，不报错', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    expect(q('[data-testid="local-path-input"] input')).not.toBeNull()
    expect(q('[data-testid="pick-folder-btn"]')).toBeNull()
    expect(q('[data-testid="registered-repo-select"]')).not.toBeNull()
    await b.done()
  })

  it('Tauri 环境：显示“选择文件夹…”，选完用 dialog 插件返回的路径，同样先校验', async () => {
    ;(globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
    try {
      const server = makeServer()
      const b = await bootTasks(server)
      await openEdit(b)
      await click('[data-testid="pick-folder-btn"]')
      expect(
        discoverCalls(server, 'repo').map(
          (c) => (c.body as { local_repo_path: string }).local_repo_path,
        ),
      ).toContain('/repos/front')
      expect(q<HTMLInputElement>('[data-testid="local-path-input"] input')!.value).toBe(
        '/repos/front',
      )
      await b.done()
    } finally {
      delete (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
    }
  })

  it('路径字段在基本信息区，不在“高级”折叠里', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await openEdit(b)
    const fold = q('[data-testid="edit-advanced"]')!
    expect(fold.contains(q('[data-testid="local-path-field"]'))).toBe(false)
    await b.done()
  })
})
