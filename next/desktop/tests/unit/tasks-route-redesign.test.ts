// 方向 A「线路图」：任务页与外壳的回归测试（含两个功能 bug 的回归）。
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import StepList from '@/features/tasks/StepList.vue'
import RunHistory from '@/features/tasks/RunHistory.vue'
import OverflowMenu from '@/components/OverflowMenu.vue'
import {
  LINE_PALETTE,
  buildStations,
  coarseDots,
  repoLineColor,
  runDots,
  stationState,
} from '@/features/tasks/route'
import { useUiStore } from '@/stores/ui'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

type TaskView = components['schemas']['TaskView']
type RunResponse = components['schemas']['RunResponse']
type StepView = components['schemas']['StepView']

const step = (
  no: number,
  kind: string,
  status: StepView['status'],
  extra: Partial<StepView> = {},
): StepView => ({
  step_no: no,
  run_id: 'run-1',
  kind,
  status,
  started_at: status === 'pending' ? null : '2026-10-28T09:21:00Z',
  finished_at: status === 'succeeded' || status === 'failed' ? '2026-10-28T09:21:21Z' : null,
  checkpoint: {},
  target_index: kind === 'git' ? null : 0,
  ...extra,
})

beforeEach(() => {
  setActivePinia(createPinia())
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  document.body.innerHTML = ''
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('仓库线路色', () => {
  it('Event / Front / VIP / API 四个固定色，同名永远同色', () => {
    expect(repoLineColor('CG_Vue_Event')).toBe('var(--l-event)')
    expect(repoLineColor('CG_Vue_Front')).toBe('var(--l-front)')
    expect(repoLineColor('cg_vip_h5')).toBe('var(--l-vip)')
    expect(repoLineColor('CG_Front_API')).toBe('var(--l-api)')
    expect(repoLineColor('CG_Vue_Event')).toBe(repoLineColor('CG_Vue_Event'))
  })
  it('其余仓库按 hash 落在后四色，且稳定；空名用中性色', () => {
    const extras = LINE_PALETTE.slice(4)
    for (const n of ['alpha', 'beta', 'gamma', 'delta', 'epsilon']) {
      expect(extras).toContain(repoLineColor(n))
      expect(repoLineColor(n)).toBe(repoLineColor(n))
    }
    expect(repoLineColor(null)).toBe(LINE_PALETTE[7])
  })
})

describe('Bug2：终态运行里没走完的步骤显示“没有执行”，不再转圈', () => {
  it('stationState：终态运行里 pending/running/skipped 都是 skip；活动运行里 running 才是当前站', () => {
    for (const run of ['failed', 'cancelled', 'succeeded'] as const) {
      expect(stationState({ status: 'running' }, run)).toBe('skip')
      expect(stationState({ status: 'pending' }, run)).toBe('skip')
      expect(stationState({ status: 'skipped' }, run)).toBe('skip')
    }
    expect(stationState({ status: 'succeeded' }, 'failed')).toBe('done')
    expect(stationState({ status: 'failed' }, 'failed')).toBe('fail')
    expect(stationState({ status: 'running' }, 'running')).toBe('here')
    expect(stationState({ status: 'pending' }, 'running')).toBe('wait')
    // 需核实的运行里仍标 running 的步骤：结果不确定，显示需核实而不是转圈
    expect(stationState({ status: 'running' }, 'unknown')).toBe('verify')
  })

  it('StepList：失败运行里 running / pending 步骤都写“没有执行”，没有当前站、没有“部署中/构建中”', () => {
    const w = mount(StepList, {
      props: {
        runStatus: 'failed',
        steps: [
          step(0, 'git', 'succeeded'),
          step(1, 'build', 'failed'),
          step(2, 'release', 'running'),
          step(3, 'release', 'pending', { target_index: 1 }),
        ],
      },
    })
    const states = w.findAll('.stn').map((s) => s.attributes('data-state'))
    expect(states).toEqual(['done', 'fail', 'skip', 'skip'])
    const text = w.text()
    expect(text).not.toContain('部署中')
    expect(text).not.toContain('构建中')
    expect(text).not.toContain('运行中')
    expect(w.findAll('.stn').filter((s) => s.text().includes('没有执行'))).toHaveLength(2)
  })

  it('StepList：已取消的运行里还在 running 的构建站同样是“没有执行”', () => {
    const w = mount(StepList, {
      props: { runStatus: 'cancelled', steps: [step(0, 'build', 'running')] },
    })
    expect(w.get('.stn').attributes('data-state')).toBe('skip')
    expect(w.text()).toContain('没有执行')
  })

  it('StepList：运行中时当前站有进度文案，之后的站是等待', () => {
    const w = mount(StepList, {
      props: {
        runStatus: 'running',
        steps: [
          step(0, 'git', 'succeeded'),
          step(1, 'build', 'running'),
          step(2, 'release', 'pending'),
        ],
      },
    })
    expect(w.findAll('.stn').map((s) => s.attributes('data-state'))).toEqual([
      'done',
      'here',
      'wait',
    ])
    expect(w.findAll('.stn')[1]!.text()).toContain('构建中')
  })

  it('已完成站写构建号与用时', () => {
    const [s] = buildStations(
      [step(1, 'build', 'succeeded', { checkpoint: { build_id: 64758 } })],
      'succeeded',
    )
    expect(s!.sub).toBe('#64758，0:21')
  })

  it('迷你线路：有步骤用步骤状态，没有步骤给粗略线路', () => {
    expect(runDots([step(0, 'git', 'succeeded'), step(1, 'build', 'running')], 'failed')).toEqual([
      'ok',
      'idle',
    ])
    expect(coarseDots('succeeded', 3)).toEqual(['ok', 'ok', 'ok'])
    expect(runDots(undefined, null)).toEqual(['idle', 'idle', 'idle'])
  })
})

describe('运行记录：一行不折行，时间为本地 MM-DD HH:mm', () => {
  it('每行含状态标签、迷你线路、触发来源、时间、用时，选中态与键盘行为不变', async () => {
    const run = {
      run_id: 'r1',
      task_id: 't',
      operation: 'sync_build_release',
      status: 'failed',
      origin: { kind: 'telegram' },
      created_at: '2026-10-28T01:21:00Z',
      started_at: '2026-10-28T01:21:00Z',
      finished_at: '2026-10-28T01:25:23Z',
      steps: [step(0, 'git', 'succeeded'), step(1, 'build', 'failed')],
      task_snapshot: {},
    } as unknown as RunResponse
    const w = mount(RunHistory, { props: { runs: [run], selectedRunId: 'r1' } })
    const row = w.get('[data-testid="run-history-row-r1"]')
    expect(row.text()).toContain('失败')
    expect(row.text()).toContain('由 Telegram 触发')
    expect(row.text()).toMatch(/\d\d-\d\d \d\d:\d\d/)
    expect(row.text()).toContain('4:23')
    expect(row.text()).not.toMatch(/T\d\d:\d\d/)
    expect(row.find('.mini').exists()).toBe(true)
    expect(row.attributes('aria-current')).toBe('true')
    await row.trigger('keydown.enter')
    expect(w.emitted('select')).toHaveLength(1)
  })
})

describe('「⋯」菜单', () => {
  it('点触发按钮展开，Esc 收起并还焦点，点菜单项后收起', async () => {
    const w = mount(OverflowMenu, {
      props: { label: '更多操作' },
      slots: {
        default: '<button role="menuitem" class="menu-item" data-testid="m1">编辑</button>',
      },
      attachTo: document.body,
    })
    const trigger = w.get('button[aria-haspopup="menu"]')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger.element)
    await trigger.trigger('click')
    await w.get('[data-testid=m1]').trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    w.unmount()
  })
})

// ---------- 整页集成：Bug1 与外壳 ----------

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

function task(over: Partial<TaskView> = {}): TaskView {
  return {
    id: 'task-1',
    name: 'sync_build_event_test',
    enabled: true,
    sort_order: 1,
    repo_name: 'CG_Vue_Event',
    local_repo_path: '/tmp/CG_Vue_Event',
    tg_command: '/sync_build_event_test',
    tg_desc: '',
    validation: { valid: true },
    warnings: [],
    active_run_id: null,
    last_run: {
      run_id: 'run-1',
      operation: 'sync_build_release',
      status: 'unknown',
      created_at: '2026-10-28T01:21:00Z',
      finished_at: null,
    },
    git_flow: { build_branch: 'main' },
    targets: [],
    ...over,
  } as TaskView
}

function runOf(status: RunResponse['status']): RunResponse {
  return {
    run_id: 'run-1',
    task_id: 'task-1',
    operation: 'sync_build_release',
    status,
    reason_code: null,
    summary: status === 'unknown' ? '结果未能确认' : '已核对',
    config_revision: 1,
    phase: 'release',
    recovery_state: status === 'unknown' ? 'pending' : 'reconciled',
    created_at: '2026-10-28T01:21:00Z',
    started_at: '2026-10-28T01:21:01Z',
    finished_at: status === 'unknown' ? null : '2026-10-28T01:25:00Z',
    cancel_requested_at: null,
    deadline_at: '2026-10-28T02:00:00Z',
    log_bytes: 0,
    last_seq: 1,
    request_hash: 'h',
    request_id: 'r',
    state_version: 1,
    stop_reason: null,
    updated_at: '2026-10-28T01:25:00Z',
    task_snapshot: {
      id: 'task-1',
      name: 'sync_build_event_test',
      enabled: true,
      sort_order: 1,
      local_repo_path: '/tmp/CG_Vue_Event',
      tg_command: '',
      tg_desc: '',
    },
    steps: [
      step(0, 'git', 'succeeded'),
      step(1, 'build', 'succeeded'),
      step(2, 'release', 'running'),
    ],
    effects: [],
  } as unknown as RunResponse
}

function makeFetch(
  state: { run: RunResponse },
  hits: { tasks: number; runs: number; posts: string[] },
) {
  return (async (request: Request) => {
    const url = new URL(request.url)
    if (url.pathname === '/health')
      return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
    if (url.pathname === '/api/tasks') {
      hits.tasks += 1
      return json({
        revision: 1,
        items: [task({ last_run: { ...task().last_run!, status: state.run.status } })],
      })
    }
    if (url.pathname === '/api/runs') {
      hits.runs += 1
      return json({ cursor: null, items: [state.run] })
    }
    if (url.pathname.endsWith('/reconcile')) {
      hits.posts.push(url.pathname)
      return json(state.run, 202)
    }
    if (url.pathname.endsWith('/events')) return json({ items: [], next_seq: 1, has_more: false })
    if (url.pathname === '/api/runs/run-1') return json(state.run)
    return json({})
  }) as unknown as typeof fetch
}

describe('Bug1：运行从 unknown 变成终态后，任务列表与运行历史必须刷新', () => {
  it('WS 推送 unknown → failed：任务列表与历史各重新请求，行上状态更新', async () => {
    const state = { run: runOf('unknown') }
    const hits = { tasks: 0, runs: 0, posts: [] as string[] }
    localStorage.setItem('toolbox.tasks.selection', 'task-1')
    const b = await boot({ path: '/tasks', fetchImpl: makeFetch(state, hits) })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()
    expect(b.wrapper.find('[data-testid=unknown-banner]').exists()).toBe(true)
    expect(b.wrapper.get('[data-testid="task-row-task-1"]').text()).toContain('需核实')
    const before = { ...hits }

    state.run = { ...runOf('failed'), summary: '核对后确认失败' }
    b.sock.emit({
      seq: 50,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-28T01:25:00Z',
      data: {
        run_id: 'run-1',
        run_seq: 2,
        type: 'state',
        payload: { status: 'failed', summary: '核对后确认失败' },
      },
    })
    await flushPromises()
    await flushPromises()
    await flushPromises()

    expect(hits.tasks).toBeGreaterThan(before.tasks)
    expect(hits.runs).toBeGreaterThan(before.runs)
    expect(b.wrapper.get('[data-testid="task-row-task-1"]').text()).toContain('失败')
    expect(b.wrapper.find('[data-testid=unknown-banner]').exists()).toBe(false)
    await b.done()
  })

  it('点「立即核对」后即使没有 WS 事件，也会刷新任务列表与运行历史', async () => {
    const state = { run: runOf('unknown') }
    const hits = { tasks: 0, runs: 0, posts: [] as string[] }
    localStorage.setItem('toolbox.tasks.selection', 'task-1')
    const b = await boot({ path: '/tasks', fetchImpl: makeFetch(state, hits) })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()
    const before = { ...hits }

    state.run = runOf('succeeded')
    await b.wrapper.get('[data-testid="reconcile-btn"]').trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()

    expect(hits.posts).toEqual(['/api/runs/run-1/reconcile'])
    expect(hits.tasks).toBeGreaterThan(before.tasks)
    expect(hits.runs).toBeGreaterThan(before.runs)
    expect(b.wrapper.get('[data-testid="task-row-task-1"]').text()).toContain('成功')
    await b.done()
  })
})

describe('外壳：三档宽度', () => {
  function stubMedia(matches: boolean) {
    const listeners = new Set<(e: { matches: boolean }) => void>()
    const mq = {
      matches,
      media: '',
      addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: (e: { matches: boolean }) => void) =>
        listeners.delete(fn),
    }
    vi.stubGlobal('matchMedia', () => mq)
    return {
      set(next: boolean) {
        mq.matches = next
        for (const fn of listeners) fn({ matches: next })
      },
    }
  }
  const seed = async () => {
    const state = { run: runOf('failed') }
    const hits = { tasks: 0, runs: 0, posts: [] as string[] }
    localStorage.setItem('toolbox.tasks.selection', 'task-1')
    const b = await boot({ path: '/tasks', fetchImpl: makeFetch(state, hits) })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()
    return b
  }

  it('≥1280（并排）：检查器随持久化开关显示，不是浮层', async () => {
    stubMedia(false)
    const b = await seed()
    expect(b.wrapper.get('[data-testid=app-shell]').attributes('data-inspector-mode')).toBe(
      'docked',
    )
    expect(b.wrapper.get('[data-testid=inspector]').isVisible()).toBe(true)
    await b.done()
  })

  it('<1280（浮层）：默认收起；点开关展开；Esc 关闭；点浮层外关闭；点浮层内不关', async () => {
    stubMedia(true)
    const b = await seed()
    const shell = b.wrapper.get('[data-testid=app-shell]')
    expect(shell.attributes('data-inspector-mode')).toBe('overlay')
    const insp = () => b.wrapper.get('[data-testid=inspector]')
    expect(insp().isVisible()).toBe(false)

    await b.wrapper.get('[data-testid=inspector-toggle]').trigger('click')
    expect(insp().isVisible()).toBe(true)
    // 浮层模式不动并排模式的持久化开关
    expect(localStorage.getItem('toolbox.ui.inspector')).toBeNull()

    insp().element.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(insp().isVisible()).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(insp().isVisible()).toBe(false)

    await b.wrapper.get('[data-testid=inspector-toggle]').trigger('click')
    expect(insp().isVisible()).toBe(true)
    b.wrapper
      .get('[data-testid=task-title]')
      .element.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(insp().isVisible()).toBe(false)
    await b.done()
  })

  it('窗口从窄变宽：浮层状态复位，回到并排', async () => {
    const media = stubMedia(true)
    const b = await seed()
    await b.wrapper.get('[data-testid=inspector-toggle]').trigger('click')
    expect(useUiStore().inspectorFloatOpen).toBe(true)
    media.set(false)
    await flushPromises()
    expect(useUiStore().inspectorOverlay).toBe(false)
    expect(useUiStore().inspectorFloatOpen).toBe(false)
    await b.done()
  })

  it('侧栏每个入口都有 title（960–1099 只剩图标时靠它显示名称）', async () => {
    stubMedia(false)
    const b = await seed()
    const titles = b.wrapper.findAll('nav[aria-label=分区] .item, nav[aria-label=设置] .item')
    expect(titles.length).toBeGreaterThanOrEqual(7)
    for (const t of titles) expect(t.attributes('title')).toContain(t.text().trim())
    await b.done()
  })
})

describe('任务页工具条与列表项', () => {
  it('工具条主按钮只有「运行」；回滚/编辑有宽窄两份，窄时在「⋯」里；列表项带线路色与迷你线路', async () => {
    const state = { run: runOf('failed') }
    const hits = { tasks: 0, runs: 0, posts: [] as string[] }
    localStorage.setItem('toolbox.tasks.selection', 'task-1')
    const b = await boot({ path: '/tasks', fetchImpl: makeFetch(state, hits) })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const primaries = b.wrapper.findAll('.detail-topbar .b-btn[data-variant="primary"]')
    expect(primaries).toHaveLength(1)
    expect(primaries[0]!.text()).toBe('运行')
    expect(b.wrapper.find('[data-testid=rollback-btn]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid=rollback-menu-item]').exists()).toBe(true)
    expect(
      b.wrapper.get('.detail-topbar [role=menu]').findAll('[role=menuitem]').length,
    ).toBeGreaterThanOrEqual(5)

    const row = b.wrapper.get('[data-testid="task-row-task-1"]')
    expect(row.attributes('style')).toContain('--l-event')
    expect(row.find('.mini').exists()).toBe(true)
    // 元信息不用中点拼接
    expect(b.wrapper.get('.task-sub-info').text()).not.toContain('·')
    await b.done()
  })
})
