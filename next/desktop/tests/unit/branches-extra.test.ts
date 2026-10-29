// 发布配置 v8 分支目录的补充测试：路线文案边界、配置编辑器的分支保存请求体、命令编辑器的分支选择、确认单 Git 步骤与预检请求体。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  commandBranch,
  commandBranchIssue,
  commandRouteText,
  type ReleaseView,
} from '@/features/tasks/api'
import { boot, json } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

function makeConfig(): ReleaseView {
  return {
    id: 'cfg-event',
    name: 'CG_Vue_Event',
    sort_order: 0,
    project_id: 'p1',
    repo_id: 'r1',
    repo_name: 'CG_Vue_Event',
    local_repo_path: '/repos/event',
    branches: [
      {
        id: 'b-main',
        build_branch: 'main',
        update_branches: ['main'],
        merges: [],
        push_branches: [],
      },
      {
        id: 'b-dev',
        build_branch: 'develop',
        update_branches: ['develop'],
        merges: [{ source: 'develop', target: 'main' }],
        push_branches: ['main'],
      },
      {
        id: 'b-spare',
        build_branch: 'release/x',
        update_branches: [],
        merges: [],
        push_branches: [],
      },
    ],
    warnings: [],
    targets: [
      { id: 'tg-1', name: 'Event 测试', enabled: true },
      { id: 'tg-2', name: 'Event 预发', enabled: true },
    ],
    commands: [
      {
        id: 'cmd-1',
        name: '发布测试环境',
        enabled: true,
        sort_order: 0,
        branch_id: 'b-main',
        tg_command: 'sync_build_event_test',
        tg_desc: '',
        target_ids: ['tg-1'],
        active_run_id: null,
        last_run: null,
      },
      {
        id: 'cmd-2',
        name: '发布预发环境',
        enabled: true,
        sort_order: 1,
        branch_id: 'b-dev',
        tg_command: 'sync_build_event_pre',
        tg_desc: '',
        target_ids: ['tg-2', 'tg-1'],
        active_run_id: null,
        last_run: null,
      },
    ],
  }
}

interface Call {
  method: string
  path: string
  body: unknown
}

/** 带状态的假后端：只实现任务页与发布配置接口。 */
function makeServer(tweak?: (c: ReleaseView) => void) {
  const calls: Call[] = []
  const config = makeConfig()
  tweak?.(config)
  const plan = {
    plan_id: 'plan-1',
    revision: 7,
    task_summary: { id: 'cmd-1', name: 'CG_Vue_Event' },
    targets: [
      {
        target_index: 0,
        name: 'Event 测试',
        definition_id: 1,
        release_definition_id: 2,
        stage_ids: [1],
      },
    ],
    steps: [
      { kind: 'git', target_index: null },
      { kind: 'build', target_index: 0 },
      { kind: 'release', target_index: 0 },
    ],
    warnings: [],
    expires_at: '2026-10-23T10:05:00Z',
  }
  const fetchImpl = async (input: Request) => {
    const url = new URL(input.url)
    const text = input.method === 'GET' ? '' : await input.clone().text()
    const call: Call = {
      method: input.method,
      path: url.pathname,
      body: text ? JSON.parse(text) : null,
    }
    calls.push(call)
    if (url.pathname === '/health')
      return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
    if (url.pathname === '/api/tasks') return json({ items: [], revision: 7 })
    if (url.pathname === '/api/release-configs' && input.method === 'GET')
      return json({ items: [config], revision: 7 })
    if (url.pathname === '/api/release-configs/cfg-event' && input.method === 'GET')
      return json({ item: config, revision: 7 })
    if (url.pathname === '/api/runs') return json({ items: [], cursor: null })
    if (/\/preflight$/.test(url.pathname)) return json(plan)
    if (/\/runs$/.test(url.pathname) && input.method === 'POST')
      return new Response(JSON.stringify({ run_id: 'run-9' }), {
        status: 202,
        headers: { 'content-type': 'application/json' },
      })
    if (input.method !== 'GET') return json({ revision: 8, id: 'new-id' })
    return json({})
  }
  return { calls, fetchImpl: fetchImpl as unknown as typeof fetch }
}

async function bootTasks(server: ReturnType<typeof makeServer>) {
  const b = await boot({ path: '/tasks', fetchImpl: server.fetchImpl })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  return b
}

const q = <T extends Element>(sel: string) => document.querySelector(sel) as T | null
const norm = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim()

function setInput(placeholder: string, value: string) {
  const el = document.querySelector(`input[placeholder="${placeholder}"]`) as HTMLInputElement
  if (!el) throw new Error(`找不到输入框 ${placeholder}`)
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

function setBranchField(idx: number, field: string, value: string) {
  const label = Array.from(document.querySelectorAll('label.text-input')).find(
    (l) => l.querySelector('.sr-only')?.textContent === `分支 ${idx + 1} ${field}`,
  )
  const el = label?.querySelector('input') as HTMLInputElement | undefined
  if (!el) throw new Error(`找不到分支 ${idx + 1} 的 ${field}`)
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
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

// ───────────────────────── api.ts：分支与路线文案的边界 ─────────────────────────

describe('分支目录：commandBranch / commandBranchIssue 边界', () => {
  const cfg = { branches: makeConfig().branches }

  it('没选分支（空串）返回 none，取不到分支对象', () => {
    expect(commandBranchIssue(cfg, { branch_id: '' })).toBe('none')
    expect(commandBranch(cfg, { branch_id: '' })).toBeNull()
  })

  it('选了分支但目录里已没有它（被删）返回 missing', () => {
    expect(commandBranchIssue(cfg, { branch_id: 'b-deleted' })).toBe('missing')
    expect(commandBranch(cfg, { branch_id: 'b-deleted' })).toBeNull()
  })

  it('分支目录为空时，任何已选分支都是 missing', () => {
    expect(commandBranchIssue({ branches: [] }, { branch_id: 'b-main' })).toBe('missing')
  })

  it('分支存在时没有问题，返回的是目录里同一个分支对象', () => {
    expect(commandBranchIssue(cfg, { branch_id: 'b-dev' })).toBeNull()
    expect(commandBranch(cfg, { branch_id: 'b-dev' })?.build_branch).toBe('develop')
  })
})

describe('分支目录：commandRouteText 边界', () => {
  const full = makeConfig()

  it('没选分支：写“未选分支”，目标照常列出', () => {
    expect(commandRouteText(full, { branch_id: '', target_ids: ['tg-1'] })).toBe(
      '未选分支，发布 Event 测试',
    )
  })

  it('分支被删：写“分支已不存在”，不退回显示别的分支名', () => {
    expect(commandRouteText(full, { branch_id: 'b-deleted', target_ids: ['tg-1'] })).toBe(
      '分支已不存在，发布 Event 测试',
    )
  })

  it('分支存在但没有目标：写“未选发布目标”', () => {
    expect(commandRouteText(full, { branch_id: 'b-main', target_ids: [] })).toBe(
      'main 分支，未选发布目标',
    )
  })

  it('多个目标按命令里的顺序列出，不按目录顺序', () => {
    expect(commandRouteText(full, { branch_id: 'b-dev', target_ids: ['tg-2', 'tg-1'] })).toBe(
      'develop 分支，发布 Event 预发、Event 测试',
    )
    expect(commandRouteText(full, { branch_id: 'b-dev', target_ids: ['tg-1', 'tg-2'] })).toBe(
      'develop 分支，发布 Event 测试、Event 预发',
    )
  })

  it('目标 id 在目录里找不到时跳过它，其余目标照常列出', () => {
    expect(commandRouteText(full, { branch_id: 'b-main', target_ids: ['tg-gone', 'tg-2'] })).toBe(
      'main 分支，发布 Event 预发',
    )
  })

  it('目标 id 全部找不到时仍写“未选发布目标”（与引用不一致，记为观察）', () => {
    expect(commandRouteText(full, { branch_id: 'b-main', target_ids: ['tg-gone'] })).toBe(
      'main 分支，未选发布目标',
    )
  })
})

// ───────────────────────── 配置编辑器：分支保存请求体 ─────────────────────────

describe('配置编辑器：分支目录保存', () => {
  it('已有分支回传原 id，新增分支整个对象不含 id 键；请求体顶层与分支内都没有 git_flow', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="add-branch-btn"]')!.click()
    await flushPromises()
    setBranchField(3, '构建分支', 'hotfix')
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
    await flushPromises()

    const patch = server.calls.find((c) => c.method === 'PATCH')!
    const body = patch.body as { git_flow?: unknown; branches: Array<Record<string, unknown>> }
    expect(body).not.toHaveProperty('git_flow')
    expect(body.branches).toHaveLength(4)
    expect(body.branches[0]).toHaveProperty('id', 'b-main')
    expect(body.branches[1]).toHaveProperty('id', 'b-dev')
    // 新增项不能带 id 键（不是 id: undefined）
    expect('id' in body.branches[3]!).toBe(false)
    for (const br of body.branches) expect(br).not.toHaveProperty('git_flow')
    await b.done()
  })

  it('构建分支首尾空格在提交前去掉；“ main ”与已有的“main”算重复，禁止保存', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="toggle-branch-2"]')!.click()
    await flushPromises()
    setBranchField(2, '构建分支', ' main ')
    await flushPromises()
    expect(q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.disabled).toBe(true)
    expect(q('[data-testid="branch-dup-0"]')!.textContent).toContain('重复')

    setBranchField(2, '构建分支', '  hotfix  ')
    await flushPromises()
    expect(q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.disabled).toBe(false)
    q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
    await flushPromises()
    const patch = server.calls.find((c) => c.method === 'PATCH')!
    const names = (patch.body as { branches: Array<{ build_branch: string }> }).branches.map(
      (x) => x.build_branch,
    )
    expect(names).toEqual(['main', 'develop', 'hotfix'])
    await b.done()
  })

  it('大小写不同的“MAIN”与“main”不算重复（与后端一样区分大小写）：允许保存，原样提交', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="toggle-branch-2"]')!.click()
    await flushPromises()
    setBranchField(2, '构建分支', 'MAIN')
    await flushPromises()
    expect(q('[data-testid="branch-dup-0"]')).toBeNull()
    expect(q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.disabled).toBe(false)
    q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
    await flushPromises()
    const patch = server.calls.find((c) => c.method === 'PATCH')!
    const names = (patch.body as { branches: Array<{ build_branch: string }> }).branches.map(
      (x) => x.build_branch,
    )
    expect(names).toEqual(['main', 'develop', 'MAIN'])
    await b.done()
  })
})

// ───────────────────────── 运行命令编辑器：分支选择 ─────────────────────────

describe('运行命令编辑器：分支选择', () => {
  it('配置只有一个分支：新建命令时自动选中它，填名称并选目标后可保存，提交该分支 id', async () => {
    const server = makeServer((c) => {
      c.branches = c.branches!.slice(0, 1)
      c.commands = c.commands.slice(0, 1)
    })
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="new-command-btn"]').trigger('click')
    await flushPromises()
    expect(q<HTMLInputElement>('[data-testid="select-branch-b-main"]')!.checked).toBe(true)
    expect(q('[data-testid="command-branch-required"]')).toBeNull()

    setInput('例如：同步构建发布测试环境', '新命令')
    q<HTMLButtonElement>('[data-testid="select-target-tg-1"]')!.click()
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="save-command-btn"]')!.click()
    await flushPromises()
    const post = server.calls.find(
      (c) => c.method === 'POST' && c.path === '/api/release-configs/cfg-event/commands',
    )!
    expect(post.body).toMatchObject({ branch_id: 'b-main', target_ids: ['tg-1'] })
    await b.done()
  })

  it('配置有多个分支：新建命令不预选，只填名称并选目标仍不能保存，选了分支才行', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="new-command-btn"]').trigger('click')
    await flushPromises()
    for (const id of ['b-main', 'b-dev', 'b-spare']) {
      expect(q<HTMLInputElement>(`[data-testid="select-branch-${id}"]`)!.checked).toBe(false)
    }
    setInput('例如：同步构建发布测试环境', '新命令')
    q<HTMLButtonElement>('[data-testid="select-target-tg-1"]')!.click()
    await flushPromises()
    const save = () => q<HTMLButtonElement>('[data-testid="save-command-btn"]')!
    expect(save().disabled).toBe(true)
    expect(q('[data-testid="command-branch-required"]')).not.toBeNull()
    save().click()
    await flushPromises()
    expect(server.calls.some((c) => c.method === 'POST')).toBe(false)

    q<HTMLInputElement>('[data-testid="select-branch-b-spare"]')!.click()
    await flushPromises()
    expect(save().disabled).toBe(false)
    expect(q('[data-testid="command-branch-required"]')).toBeNull()
    await b.done()
  })

  it('编辑分支已被删的旧命令：单选组没有任何选中项，提示重选，保存禁用', async () => {
    const server = makeServer((c) => {
      c.commands[1]!.branch_id = 'b-gone'
    })
    const b = await bootTasks(server)
    expect(b.wrapper.get('[data-testid="command-route-cmd-2"]').text()).toBe(
      '分支已不存在，发布 Event 预发、Event 测试',
    )
    await b.wrapper.get('[data-testid="command-edit-cmd-2"]').trigger('click')
    await flushPromises()
    for (const id of ['b-main', 'b-dev', 'b-spare']) {
      expect(q<HTMLInputElement>(`[data-testid="select-branch-${id}"]`)!.checked).toBe(false)
    }
    expect(q('[data-testid="command-branch-required"]')!.textContent).toContain('请选择一个分支')
    expect(q<HTMLButtonElement>('[data-testid="save-command-btn"]')!.disabled).toBe(true)
    await b.done()
  })
})

// ───────────────────────── 分支规则选择器的行为 ─────────────────────────

describe('配置编辑器：分支规则选择器', () => {
  type SavedBranches = {
    branches: Array<{
      build_branch: string
      update_branches: string[]
      push_branches: string[]
      merges: unknown[]
    }>
  }

  async function openRules() {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="toggle-branch-0"]')!.click()
    await flushPromises()
    return { server, b }
  }
  const save = async (server: ReturnType<typeof makeServer>) => {
    q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
    await flushPromises()
    return server.calls.find((c) => c.method === 'PATCH')?.body as SavedBranches | undefined
  }

  // 旧缺陷 DEF-2（合并规则缺冒号被静默丢弃）在选择器里对应“没选完整的行”：行内提示、禁用保存、不发请求
  it('DEF-2 合并规则没选完整的行不静默丢弃：行内提示、禁用保存、不发请求', async () => {
    const { server, b } = await openRules()
    q<HTMLButtonElement>('[data-testid="branch-0-merge-add"]')!.click()
    await flushPromises()
    expect(q('[data-testid="branch-0-merge-err-0"]')!.textContent).toContain(
      '请选择源分支和目标分支',
    )
    expect(q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.disabled).toBe(true)
    expect(q('[data-testid="merges-invalid"]')).not.toBeNull()
    expect(await save(server)).toBeUndefined()
    await b.done()
  })

  // 旧缺陷 DEF-1（只按半角逗号切分）在“输入其他分支名”里：中文逗号也拆成多个分支
  it('DEF-1 手输其他分支名接受中文逗号：“main，develop”拆成两个推送分支', async () => {
    const { server, b } = await openRules()
    q<HTMLButtonElement>('[data-testid="branch-0-push-toggle"]')!.click()
    await flushPromises()
    const label = Array.from(document.querySelectorAll('label.text-input')).find(
      (l) => l.querySelector('.sr-only')?.textContent === '分支 1 推送分支 其他分支名',
    )!
    const el = label.querySelector('input') as HTMLInputElement
    el.value = 'main，develop'
    el.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="branch-0-push-extra-add"]')!.click()
    await flushPromises()
    const body = await save(server)
    expect(body?.branches[0]?.push_branches).toEqual(['main', 'develop'])
    await b.done()
  })
})

// ───────────────────────── 确认单与运行请求体 ─────────────────────────

describe('确认单与预检请求体', () => {
  it('确认单的 Git 步骤写所选命令的分支规则：选 main 命令时不出现 develop 的合并与推送', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="run-task-btn"]').trigger('click')
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="command-pick-cmd-1"]')!.click()
    await flushPromises()
    const confirm = norm(q('[data-testid="run-confirm-sheet"]')!.textContent)
    expect(confirm).toContain('（main 分支）：更新 main，合并 —，推送 —')
    expect(confirm).not.toContain('develop')
    expect(confirm).not.toContain('develop → main')
    expect(norm(q('[data-testid="confirm-command-route"]')!.textContent)).toBe(
      'main 分支，发布 Event 测试',
    )
    await b.done()
  })

  it('预检请求体只有 operation 与 revision：不带 branch_id、target_ids 等临时选择，路径用命令 id', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="run-task-btn"]').trigger('click')
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="command-pick-cmd-2"]')!.click()
    await flushPromises()
    const pre = server.calls.find((c) => c.path.endsWith('/preflight'))!
    expect(pre.path).toBe('/api/tasks/cmd-2/preflight')
    expect(Object.keys(pre.body as object).sort()).toEqual(['operation', 'revision'])
    await b.done()
  })
})
