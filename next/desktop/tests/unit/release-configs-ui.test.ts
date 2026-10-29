// 发布配置 + 运行命令：任务页的新结构（标题是配置名、运行先选命令、命令编辑、删除与冲突处理）
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { boot, json } from './boot'
import { ApiError, releaseErrorText } from '@/features/tasks/api'
import { FakeSocket, hello, resetSeq } from './helpers'

type ReleaseView = components['schemas']['ReleaseView']
type RunResponse = components['schemas']['RunResponse']

const TG = 'sync_build_event_test'

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
      // 没有命令使用的分支，可以删
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
        tg_command: TG,
        tg_desc: '同步构建并发布测试环境',
        target_ids: ['tg-1'],
        active_run_id: null,
        last_run: {
          run_id: 'run-1',
          status: 'succeeded',
          operation: 'sync_build_release',
          created_at: '2026-10-23T09:00:00Z',
          finished_at: '2026-10-23T09:05:00Z',
        },
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
      {
        id: 'cmd-3',
        name: '旧发布流程',
        enabled: false,
        sort_order: 2,
        branch_id: 'b-main',
        tg_command: 'old_cmd',
        tg_desc: '',
        target_ids: ['tg-1'],
        active_run_id: null,
        last_run: null,
      },
    ],
  }
}

function makeRun(runId: string, taskId: string, createdAt: string): RunResponse {
  return {
    run_id: runId,
    task_id: taskId,
    operation: 'sync_build_release',
    status: 'succeeded',
    reason_code: null,
    summary: '完成',
    config_revision: 3,
    phase: 'release',
    recovery_state: 'none',
    created_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
    cancel_requested_at: null,
    deadline_at: '2026-10-23T09:30:00Z',
    log_bytes: 0,
    last_seq: 0,
    request_hash: 'h',
    request_id: 'r',
    state_version: 1,
    stop_reason: null,
    updated_at: createdAt,
    task_snapshot: {
      id: taskId,
      name: 'CG_Vue_Event',
      enabled: true,
      sort_order: 0,
      local_repo_path: '/repos/event',
      tg_command: TG,
      tg_desc: '',
    },
    steps: [],
    effects: [],
  }
}

interface Call {
  method: string
  path: string
  query: Record<string, string>
  body: unknown
}

/** 带状态的假后端：只实现任务页用到的接口。 */
function makeServer(
  opts: { onWrite?: (c: Call) => Response | null; tweak?: (c: ReleaseView) => void } = {},
) {
  const calls: Call[] = []
  let revision = 7
  const config = makeConfig()
  opts.tweak?.(config)
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
      query: Object.fromEntries(url.searchParams),
      body: text ? JSON.parse(text) : null,
    }
    calls.push(call)
    if (url.pathname === '/health')
      return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
    if (url.pathname === '/api/tasks') return json({ items: [], revision })
    if (url.pathname === '/api/release-configs' && input.method === 'GET')
      return json({ items: [config], revision })
    if (url.pathname === '/api/release-configs/cfg-event' && input.method === 'GET')
      return json({ item: config, revision })
    if (url.pathname === '/api/runs') {
      const id = url.searchParams.get('task_id')
      const items =
        id === 'cmd-1'
          ? [makeRun('run-1', 'cmd-1', '2026-10-23T09:00:00Z')]
          : id === 'cmd-2'
            ? [makeRun('run-2', 'cmd-2', '2026-10-23T10:00:00Z')]
            : []
      return json({ items, cursor: null })
    }
    if (/^\/api\/runs\/run-\d+\/events$/.test(url.pathname))
      return json({ items: [], next_seq: 0, has_more: false })
    const m = url.pathname.match(/^\/api\/runs\/(run-\d+)$/)
    if (m) return json(makeRun(m[1]!, m[1] === 'run-2' ? 'cmd-2' : 'cmd-1', '2026-10-23T09:00:00Z'))
    if (/\/preflight$/.test(url.pathname)) return json(plan)
    if (/\/runs$/.test(url.pathname) && input.method === 'POST')
      return new Response(JSON.stringify({ run_id: 'run-9' }), {
        status: 202,
        headers: { 'content-type': 'application/json' },
      })
    if (input.method !== 'GET') {
      const custom = opts.onWrite?.(call)
      if (custom) return custom
      revision += 1
      return json({ revision, id: 'new-id' })
    }
    return json({})
  }
  return {
    calls,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    setRevision: (n: number) => (revision = n),
  }
}

async function bootTasks(server: ReturnType<typeof makeServer>) {
  const b = await boot({ path: '/tasks', fetchImpl: server.fetchImpl })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  return b
}

const q = <T extends Element>(sel: string) => document.querySelector(sel) as T | null
function setInput(placeholder: string, value: string) {
  const el = document.querySelector(`input[placeholder="${placeholder}"]`) as HTMLInputElement
  if (!el) throw new Error(`找不到输入框 ${placeholder}`)
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

/** 设置第 idx 个分支里某个字段（按输入框的读屏标签找，如“分支 3 构建分支”）。 */
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

describe('发布配置任务页', () => {
  it('列表与标题只显示配置名称，不出现 TG 英文命令；元信息写仓库/分支、目标数、命令数', async () => {
    const server = makeServer()
    const b = await bootTasks(server)

    const row = b.wrapper.get('[data-testid="task-row-cfg-event"]')
    expect(row.text()).toContain('CG_Vue_Event')
    expect(b.wrapper.get('[data-testid="task-title"]').text()).toBe('CG_Vue_Event')
    // 列表和标题区都不显示英文命令
    expect(row.text()).not.toContain(TG)
    expect(b.wrapper.get('.detail-content > h2').text()).not.toContain(TG)
    expect(b.wrapper.get('[data-testid="task-repo"]').text()).toContain('CG_Vue_Event')
    expect(b.wrapper.get('[data-testid="task-branch-count"]').text()).toContain('3 个分支')
    expect(b.wrapper.get('[data-testid="task-target-count"]').text()).toContain('2 个发布目标')
    expect(b.wrapper.get('[data-testid="task-command-count"]').text()).toContain('3 条运行命令')
    expect(b.wrapper.get('.task-sub-info').text()).not.toContain('·')
    expect(b.wrapper.get('.task-sub-info').text()).not.toContain('/')
    // 状态取最近一次运行的结果
    expect(row.text()).toContain('成功')
    await b.done()
  })

  it('运行先选命令：只列启用的命令（名称、目标名、TG 命令小字），选中后按命令 id 预检与启动，不带临时目标', async () => {
    const server = makeServer()
    const b = await bootTasks(server)

    await b.wrapper.get('[data-testid="run-task-btn"]').trigger('click')
    await flushPromises()
    // 点运行先弹出选择器，还没有发预检
    expect(server.calls.some((c) => c.path.endsWith('/preflight'))).toBe(false)
    const picker = q('[data-testid="command-picker"]')!
    expect(picker.textContent).toContain('发布测试环境')
    // 每条命令写明用的分支和要发布的目标
    expect(q('[data-testid="command-pick-route-cmd-1"]')!.textContent!.trim()).toBe(
      'main 分支，发布 Event 测试',
    )
    expect(picker.textContent).toContain(TG)
    // 命令里目标的顺序就是发布顺序
    expect(q('[data-testid="command-pick-route-cmd-2"]')!.textContent!.trim()).toBe(
      'develop 分支，发布 Event 预发、Event 测试',
    )
    expect(picker.textContent).not.toContain('旧发布流程')

    q<HTMLButtonElement>('[data-testid="command-pick-cmd-2"]')!.click()
    await flushPromises()
    const pre = server.calls.find((c) => c.path === '/api/tasks/cmd-2/preflight')!
    expect(pre.body).toMatchObject({ operation: 'sync_build_release', revision: 7 })
    // 确认单标题标明配置与命令
    expect(document.body.textContent).toContain('运行“CG_Vue_Event”的命令“发布预发环境”？')
    // 确认单写明分支，Git 步骤按该分支的规则
    const confirm = q('[data-testid="run-confirm-sheet"]')!.textContent!
    expect(q('[data-testid="confirm-command-route"]')!.textContent).toContain(
      'develop 分支，发布 Event 预发、Event 测试',
    )
    expect(confirm).toContain('合并 develop → main')
    expect(confirm).toContain('推送 main')

    q<HTMLButtonElement>('[data-testid="confirm-start-btn"]')!.click()
    await flushPromises()
    const start = server.calls.find((c) => c.path === '/api/tasks/cmd-2/runs')!
    expect(Object.keys(start.body as object).sort()).toEqual([
      'ack_old_app_idle',
      'plan_id',
      'request_id',
    ])
    await b.done()
  })

  it('只发布与回滚同样先选命令', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="deploy-only-btn"]').trigger('click')
    await flushPromises()
    expect(q('[data-testid="command-picker"]')!.textContent).toContain('发布预发环境')
    expect(document.body.textContent).toContain('选择要只发布的命令')
    q<HTMLButtonElement>('[data-testid="command-pick-cmd-1"]')!.click()
    await flushPromises()
    const pre = server.calls.find((c) => c.path === '/api/tasks/cmd-1/preflight')!
    expect((pre.body as { operation: string }).operation).toBe('deploy_only')
    await b.done()
  })

  it('运行记录合并配置下所有命令的运行，并标明命令名称', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    const rows = b.wrapper.findAll('[data-testid="run-history-command"]')
    expect(rows.map((r) => r.text())).toEqual(['发布预发环境', '发布测试环境'])
    // 记录里同时标明命令用的分支
    expect(b.wrapper.findAll('[data-testid="run-history-branch"]').map((r) => r.text())).toEqual([
      'develop 分支',
      'main 分支',
    ])
    expect(b.wrapper.get('[data-testid="run-command-branch"]').text()).toBe('main 分支')
    expect(b.wrapper.get('[data-testid="run-command-name"]').text()).toBe('发布测试环境')
    await b.done()
  })

  it('运行命令区列出名称、TG 命令、所选目标与最近一次结果', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    const row = b.wrapper.get('[data-testid="command-row-cmd-1"]')
    expect(row.text()).toContain('发布测试环境')
    expect(row.text()).toContain(TG)
    expect(row.text()).toContain('main 分支，发布 Event 测试')
    expect(row.text()).toContain('成功')
    expect(b.wrapper.get('[data-testid="command-row-cmd-3"]').text()).toContain('已停用')
    await b.done()
  })

  it('命令编辑：没选目标不能保存并提示；选目标后按勾选顺序保存', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="new-command-btn"]').trigger('click')
    await flushPromises()

    setInput('例如：同步构建发布测试环境', '新命令')
    await flushPromises()
    const save = () => q<HTMLButtonElement>('[data-testid="save-command-btn"]')!
    expect(save().disabled).toBe(true)
    expect(q('[data-testid="command-targets-required"]')!.textContent).toContain(
      '至少选择一个发布目标',
    )
    // 配置有多个分支时不替用户选；没选分支同样不能保存
    expect(q('[data-testid="command-branch-required"]')!.textContent).toContain('请选择一个分支')
    expect(q<HTMLInputElement>('[data-testid="select-branch-b-main"]')!.checked).toBe(false)
    q<HTMLButtonElement>('[data-testid="select-target-tg-2"]')!.click()
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="select-target-tg-1"]')!.click()
    await flushPromises()
    expect(save().disabled).toBe(true)
    q<HTMLButtonElement>('[data-testid="unselect-target-tg-2"]')!.click()
    q<HTMLButtonElement>('[data-testid="unselect-target-tg-1"]')!.click()
    await flushPromises()
    save().click()
    await flushPromises()
    expect(server.calls.some((c) => c.method === 'POST' && c.path.endsWith('/commands'))).toBe(
      false,
    )

    // 选了分支但没选目标仍不能保存
    const pick = q<HTMLInputElement>('[data-testid="select-branch-b-dev"]')!
    pick.click()
    pick.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    expect(q('[data-testid="command-branch-required"]')).toBeNull()
    expect(save().disabled).toBe(true)

    // 先选第二个，再选第一个：顺序就是执行顺序
    q<HTMLButtonElement>('[data-testid="select-target-tg-2"]')!.click()
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="select-target-tg-1"]')!.click()
    await flushPromises()
    expect(q('[data-testid="command-targets-required"]')).toBeNull()
    expect(save().disabled).toBe(false)
    save().click()
    await flushPromises()
    const post = server.calls.find(
      (c) => c.method === 'POST' && c.path === '/api/release-configs/cfg-event/commands',
    )!
    expect(post.body).toMatchObject({
      name: '新命令',
      branch_id: 'b-dev',
      target_ids: ['tg-2', 'tg-1'],
      revision: 7,
    })
    await b.done()
  })

  it('配置编辑：被命令使用的目标不能删并写清怎么办；没被使用的可以删', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()

    const remove0 = q<HTMLButtonElement>('[data-testid="remove-target-0"]')!
    expect(remove0.disabled).toBe(true)
    const note = q('[data-testid="target-used-0"]')!.textContent!
    expect(note).toContain('发布测试环境')
    expect(note).toContain('不能删除')
    expect(note).toContain('取消勾选')

    q<HTMLButtonElement>('[data-testid="add-target-btn"]')!.click()
    await flushPromises()
    // 新增目标还没被任何命令使用，可以删
    expect(q<HTMLButtonElement>('[data-testid="remove-target-2"]')!.disabled).toBe(false)
    await b.done()
  })

  it('配置编辑：保存时已有目标回传 id、新增目标省略 id；后端拒绝删除被引用目标时给出怎么办', async () => {
    const server = makeServer({
      onWrite: (c) =>
        c.method === 'PATCH'
          ? new Response(
              JSON.stringify({
                detail: { code: 'validation_error', message: '目标仍被运行命令引用' },
              }),
              { status: 422, headers: { 'content-type': 'application/json' } },
            )
          : null,
    })
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="add-target-btn"]')!.click()
    await flushPromises()
    // 新目标必须填全构建定义、Release 定义和环境才能保存：填最后一个目标的手填字段
    for (const [label, value] of [
      ['构建定义 ID', '12'],
      ['Release 定义 ID', '7'],
      ['环境 ID', '1'],
    ] as const) {
      const labels = Array.from(document.querySelectorAll('label.text-input')).filter(
        (l) => l.querySelector('.sr-only')?.textContent === label,
      )
      const el = labels[labels.length - 1]!.querySelector('input')!
      el.value = value
      el.dispatchEvent(new Event('input', { bubbles: true }))
      await flushPromises()
    }
    q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
    await flushPromises()
    const patch = server.calls.find((c) => c.method === 'PATCH')!
    const targets = (patch.body as { targets: Array<{ id?: string }> }).targets
    expect(targets.map((t) => t.id)).toEqual(['tg-1', 'tg-2', undefined])
    // 分支目录整份回传：已有分支带 id，且不再有配置级 git_flow
    const sent = patch.body as { branches: Array<{ id?: string; build_branch: string }> }
    expect(sent.branches.map((x) => x.id)).toEqual(['b-main', 'b-dev', 'b-spare'])
    expect(patch.body).not.toHaveProperty('git_flow')
    expect(q('[data-testid="task-edit-error"]')!.textContent).toContain('请先在对应命令里取消勾选')
    await b.done()
  })

  it('revision 冲突：重新读取最新配置，不自动重发；再次保存才用新版本', async () => {
    let conflict = true
    const server = makeServer({
      onWrite: (c) => {
        if (c.method === 'PATCH' && conflict) {
          conflict = false
          return new Response(
            JSON.stringify({ detail: { code: 'revision_conflict', message: 'x' } }),
            { status: 409, headers: { 'content-type': 'application/json' } },
          )
        }
        return null
      },
    })
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()
    const listReads = () =>
      server.calls.filter((c) => c.method === 'GET' && c.path === '/api/release-configs').length
    const before = listReads()
    // 别处已经改过配置，版本变成 12
    server.setRevision(12)
    q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
    await flushPromises()
    await flushPromises()

    expect(server.calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
    expect(listReads()).toBeGreaterThan(before)
    expect(q('[data-testid="task-edit-error"]')!.textContent).toContain('已重新读取最新内容')

    q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
    await flushPromises()
    const patches = server.calls.filter((c) => c.method === 'PATCH')
    expect(patches).toHaveLength(2)
    expect((patches[0]!.body as { revision: number }).revision).toBe(7)
    expect((patches[1]!.body as { revision: number }).revision).toBe(12)
    await b.done()
  })

  it('删除命令遇到 task_referenced：展示权限组并用 detach_acl=true 重试', async () => {
    const server = makeServer({
      onWrite: (c) =>
        c.method === 'DELETE' && !c.query.detach_acl
          ? new Response(
              JSON.stringify({
                detail: { code: 'task_referenced', message: 'x', groups: ['夜间发布组'] },
              }),
              { status: 409, headers: { 'content-type': 'application/json' } },
            )
          : null,
    })
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="command-delete-cmd-2"]').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('确认删除运行命令「发布预发环境」？')
    q<HTMLButtonElement>('[data-testid="confirm-delete-task-btn"]')!.click()
    await flushPromises()
    expect(q('[data-testid="task-referenced-groups"]')!.textContent).toContain('夜间发布组')
    q<HTMLButtonElement>('[data-testid="confirm-detach-delete-task-btn"]')!.click()
    await flushPromises()
    const dels = server.calls.filter((c) => c.method === 'DELETE')
    expect(dels.map((d) => d.path)).toEqual([
      '/api/release-configs/cfg-event/commands/cmd-2',
      '/api/release-configs/cfg-event/commands/cmd-2',
    ])
    expect(dels[1]!.query.detach_acl).toBe('true')
    await b.done()
  })

  it('命令上移按全部命令 id 排序提交', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="command-up-cmd-2"]').trigger('click')
    await flushPromises()
    const put = server.calls.find((c) => c.method === 'PUT')!
    expect(put.path).toBe('/api/release-configs/cfg-event/commands/order')
    expect(put.body).toEqual({ ids: ['cmd-2', 'cmd-1', 'cmd-3'], revision: 7 })
    await b.done()
  })

  it('配置编辑：被命令使用的分支不能删并写清怎么办；没被使用的可以删，保存时分支目录整份提交', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()

    // main 被“发布测试环境”“旧发布流程”使用，develop 被“发布预发环境”使用
    expect(q<HTMLButtonElement>('[data-testid="remove-branch-0"]')!.disabled).toBe(true)
    const note = q('[data-testid="branch-used-0"]')!.textContent!
    expect(note).toContain('正在被命令“发布测试环境”“旧发布流程”使用，不能删除')
    expect(note).toContain('先把这些命令改用别的分支')
    expect(q<HTMLButtonElement>('[data-testid="remove-branch-1"]')!.disabled).toBe(true)
    expect(q('[data-testid="branch-used-2"]')).toBeNull()

    // 没被使用的分支能删；新加的分支也能删
    q<HTMLButtonElement>('[data-testid="remove-branch-2"]')!.click()
    await flushPromises()
    expect(q('[data-testid="branch-edit-2"]')).toBeNull()
    q<HTMLButtonElement>('[data-testid="add-branch-btn"]')!.click()
    await flushPromises()
    expect(q<HTMLButtonElement>('[data-testid="remove-branch-2"]')!.disabled).toBe(false)
    setBranchField(2, '构建分支', 'hotfix')
    // 新分支的规则用选择器：推送分支手输其他分支名；合并规则一行源 → 目标（远端分支没读到时退回文本框）
    q<HTMLButtonElement>('[data-testid="branch-2-push-toggle"]')!.click()
    await flushPromises()
    const lab = (t: string) =>
      Array.from(document.querySelectorAll('label.text-input'))
        .find((l) => l.querySelector('.sr-only')?.textContent === t)!
        .querySelector('input') as HTMLInputElement
    const typeLab = async (t: string, v: string) => {
      const el = lab(t)
      el.value = v
      el.dispatchEvent(new Event('input', { bubbles: true }))
      await flushPromises()
    }
    await typeLab('分支 3 推送分支 其他分支名', 'hotfix')
    q<HTMLButtonElement>('[data-testid="branch-2-push-extra-add"]')!.click()
    await flushPromises()
    q<HTMLButtonElement>('[data-testid="branch-2-merge-add"]')!.click()
    await flushPromises()
    await typeLab('分支 3 合并 1 源分支', 'hotfix')
    await typeLab('分支 3 合并 1 目标分支', 'main')

    q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
    await flushPromises()
    const patch = server.calls.find((c) => c.method === 'PATCH')!
    expect((patch.body as { branches: unknown }).branches).toEqual([
      {
        id: 'b-main',
        build_branch: 'main',
        update_branches: ['main'],
        push_branches: [],
        merges: [],
      },
      {
        id: 'b-dev',
        build_branch: 'develop',
        update_branches: ['develop'],
        push_branches: ['main'],
        merges: [{ source: 'develop', target: 'main' }],
      },
      {
        build_branch: 'hotfix',
        update_branches: [],
        push_branches: ['hotfix'],
        merges: [{ source: 'hotfix', target: 'main' }],
      },
    ])
    await b.done()
  })

  it('配置编辑：构建分支名重复时本地提示并禁止保存，改掉后才能保存', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
    await flushPromises()
    const save = () => q<HTMLButtonElement>('[data-testid="save-task-btn"]')!
    expect(save().disabled).toBe(false)

    // 把第三个分支改成和第一个同名
    q<HTMLButtonElement>('[data-testid="toggle-branch-2"]')!.click()
    await flushPromises()
    setBranchField(2, '构建分支', 'main')
    await flushPromises()
    expect(save().disabled).toBe(true)
    expect(q('[data-testid="branch-dup-0"]')!.textContent).toContain('重复')
    expect(q('[data-testid="branch-dup-2"]')!.textContent).toContain('“main”')
    expect(q('[data-testid="branches-invalid"]')).not.toBeNull()
    save().click()
    await flushPromises()
    expect(server.calls.some((c) => c.method === 'PATCH')).toBe(false)

    setBranchField(2, '构建分支', 'release/y')
    await flushPromises()
    expect(save().disabled).toBe(false)
    expect(q('[data-testid="branch-dup-0"]')).toBeNull()

    // 构建分支留空同样不能保存
    setBranchField(2, '构建分支', '  ')
    await flushPromises()
    expect(save().disabled).toBe(true)
    await b.done()
  })

  it('选择器：命令没选分支或分支已被删掉时禁用并写明原因', async () => {
    const server = makeServer({
      tweak: (c) => {
        c.commands.push(
          {
            id: 'cmd-nobranch',
            name: '没选分支的命令',
            enabled: true,
            sort_order: 3,
            tg_command: '',
            tg_desc: '',
            branch_id: '',
            target_ids: ['tg-1'],
            active_run_id: null,
            last_run: null,
          },
          {
            id: 'cmd-gone',
            name: '分支被删的命令',
            enabled: true,
            sort_order: 4,
            tg_command: '',
            tg_desc: '',
            branch_id: 'b-deleted',
            target_ids: ['tg-1'],
            active_run_id: null,
            last_run: null,
          },
        )
      },
    })
    const b = await bootTasks(server)
    await b.wrapper.get('[data-testid="run-task-btn"]').trigger('click')
    await flushPromises()

    const none = q<HTMLButtonElement>('[data-testid="command-pick-cmd-nobranch"]')!
    expect(none.disabled).toBe(true)
    expect(none.textContent).toContain('未选分支，发布 Event 测试')
    expect(none.textContent).toContain('还没有选分支')
    const gone = q<HTMLButtonElement>('[data-testid="command-pick-cmd-gone"]')!
    expect(gone.disabled).toBe(true)
    expect(gone.textContent).toContain('分支已不存在')
    expect(gone.textContent).toContain('它用的分支已被删除')
    // 好命令照常可选
    expect(q<HTMLButtonElement>('[data-testid="command-pick-cmd-1"]')!.disabled).toBe(false)
    gone.click()
    await flushPromises()
    expect(server.calls.some((c) => c.path.endsWith('/preflight'))).toBe(false)
    await b.done()
  })

  it('检查器按分支分组展示 Git 规则', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    const dev = b.wrapper.get('[data-testid="inspector-branch-b-dev"]').text()
    expect(dev).toContain('develop')
    expect(dev).toContain('develop → main')
    expect(dev).toContain('1 条命令使用')
    expect(b.wrapper.get('[data-testid="inspector-branch-b-main"]').text()).toContain(
      '2 条命令使用',
    )
    expect(b.wrapper.get('[data-testid="inspector-branch-b-spare"]').text()).toContain('release/x')
    await b.done()
  })

  it('后端按错误码拒绝删除被引用的分支或目标：显示怎么办，不依赖消息文本', async () => {
    for (const [code, expected] of [
      ['branch_in_use', '请先把这些命令改用别的分支'],
      ['target_in_use', '请先在对应命令里取消勾选它'],
    ] as const) {
      const server = makeServer({
        onWrite: (c) =>
          c.method === 'PATCH'
            ? new Response(JSON.stringify({ detail: { code, message: 'whatever' } }), {
                status: 422,
                headers: { 'content-type': 'application/json' },
              })
            : null,
      })
      const b = await bootTasks(server)
      await b.wrapper.get('[data-testid="edit-task-btn"]').trigger('click')
      await flushPromises()
      q<HTMLButtonElement>('[data-testid="save-task-btn"]')!.click()
      await flushPromises()
      expect(q('[data-testid="task-edit-error"]')!.textContent).toContain(expected)
      expect(q('[data-testid="task-edit-error"]')!.textContent).not.toContain('whatever')
      await b.done()
      document.body.innerHTML = ''
      FakeSocket.reset()
    }
  })

  it('错误翻译：按错误码翻译，旧文本兜底，认不出的原样展示', () => {
    const err = (code: string, message: string) => new ApiError(422, code, message)
    expect(releaseErrorText(err('branch_in_use', '分支仍被运行命令引用'))).toContain('改用别的分支')
    expect(releaseErrorText(err('target_in_use', '目标仍被运行命令引用'))).toContain('取消勾选')
    // 旧后端：validation_error + 文本
    expect(releaseErrorText(err('validation_error', '目标仍被运行命令引用'))).toContain('取消勾选')
    expect(releaseErrorText(err('validation_error', '分支仍被运行命令引用'))).toContain(
      '改用别的分支',
    )
    expect(releaseErrorText(err('validation_error', '某个没见过的原因'))).toBe('某个没见过的原因')
  })
})
