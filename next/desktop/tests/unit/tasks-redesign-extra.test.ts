// 方向 A「线路图」补充测试：补齐 tasks-route-redesign.test.ts 未覆盖的分支。
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import type { components } from '@/api/schema'
import OverflowMenu from '@/components/OverflowMenu.vue'
import { repoLineColor, stationState } from '@/features/tasks/route'
import { INSPECTOR_KEY, useUiStore } from '@/stores/ui'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

type TaskView = components['schemas']['TaskView']
type RunResponse = components['schemas']['RunResponse']
type StepView = components['schemas']['StepView']

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

describe('stationState 补充分支', () => {
  it('步骤自身为 unknown：任何运行状态下都是需核实', () => {
    for (const run of ['running', 'failed', 'cancelled', 'succeeded', 'unknown'] as const) {
      expect(stationState({ status: 'unknown' }, run)).toBe('verify')
    }
  })

  it('终态运行里 skipped 步骤是没有执行；终态运行里 unknown 步骤仍是需核实', () => {
    for (const run of ['failed', 'cancelled', 'succeeded'] as const) {
      expect(stationState({ status: 'skipped' }, run)).toBe('skip')
    }
    expect(stationState({ status: 'unknown' }, 'failed')).toBe('verify')
  })

  it('运行状态缺失（null/undefined）时不当作活动运行，running 步骤不是当前站', () => {
    expect(stationState({ status: 'running' }, null)).toBe('skip')
    expect(stationState({ status: 'running' })).toBe('skip')
  })

  // 已知缺陷（待修）：route.ts:66 活动运行里非 running 的步骤一律 wait，skipped 也落进 wait。
  it('活动运行里 skipped 步骤显示为没有执行', () => {
    expect(stationState({ status: 'skipped' }, 'running')).toBe('skip')
  })
})

describe('repoLineColor 补充', () => {
  it('组合名按优先级：event 先于一切，vip 先于 api，api 先于 front', () => {
    expect(repoLineColor('event_api')).toBe('var(--l-event)')
    expect(repoLineColor('vip_api')).toBe('var(--l-vip)')
    expect(repoLineColor('front_api')).toBe('var(--l-api)')
    expect(repoLineColor('vue_front')).toBe('var(--l-front)')
  })

  it('同名（含首尾空白）返回同一颜色，且其余仓库不落在固定四色上', () => {
    expect(repoLineColor('  billing-core ')).toBe(repoLineColor('billing-core'))
    const fixed = ['var(--l-event)', 'var(--l-front)', 'var(--l-vip)', 'var(--l-api)']
    for (const n of ['orders', 'payments', 'ledger', 'search']) {
      expect(fixed).not.toContain(repoLineColor(n))
    }
  })
})

describe('「⋯」菜单补充', () => {
  it('点菜单外部（pointerdown 落在 body）时收起，不抢走焦点', async () => {
    const w = mount(OverflowMenu, {
      props: { label: '更多操作' },
      slots: { default: () => h('button', { role: 'menuitem', class: 'menu-item' }, '编辑') },
      attachTo: document.body,
    })
    const trigger = w.get('button[aria-haspopup="menu"]')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).not.toBe(trigger.element)
    w.unmount()
  })

  it('点菜单内部的非菜单项区域不收起；选中菜单项时触发它自己的事件并收起', async () => {
    const onEdit = vi.fn()
    const onDelete = vi.fn()
    const w = mount(OverflowMenu, {
      props: { label: '更多操作' },
      slots: {
        default: () => [
          h('button', { role: 'menuitem', class: 'menu-item', onClick: onEdit }, '编辑'),
          h('button', { role: 'menuitem', class: 'menu-item', onClick: onDelete }, '删除'),
        ],
      },
      attachTo: document.body,
    })
    const trigger = w.get('button[aria-haspopup="menu"]')
    await trigger.trigger('click')
    const items = w.findAll('[role="menuitem"]')
    await items[1]!.trigger('click')
    expect(onDelete).toHaveBeenCalledTimes(1)
    expect(onEdit).not.toHaveBeenCalled()
    expect(trigger.attributes('aria-expanded')).toBe('false')
    w.unmount()
  })
})

describe('ui store 窄窗（<1280）检查器浮层', () => {
  function narrow(persisted?: string) {
    if (persisted !== undefined) localStorage.setItem(INSPECTOR_KEY, persisted)
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      media: '',
      addEventListener: () => {},
      removeEventListener: () => {},
    }))
    setActivePinia(createPinia())
    return useUiStore()
  }

  it('窄窗下 toggleInspector 只切换浮层，不改持久化的 inspectorOpen，也不写 localStorage', () => {
    const ui = narrow()
    expect(ui.inspectorOverlay).toBe(true)
    expect(ui.inspectorFloatOpen).toBe(false)
    expect(ui.inspectorVisible).toBe(false)
    ui.toggleInspector()
    expect(ui.inspectorFloatOpen).toBe(true)
    expect(ui.inspectorVisible).toBe(true)
    expect(ui.inspectorOpen).toBe(true)
    expect(localStorage.getItem(INSPECTOR_KEY)).toBeNull()
  })

  it('窄窗下持久化为收起时，浮层仍只看浮层状态；开关不影响并排偏好', () => {
    const ui = narrow('false')
    expect(ui.inspectorOpen).toBe(false)
    ui.toggleInspector()
    expect(ui.inspectorVisible).toBe(true)
    expect(ui.inspectorOpen).toBe(false)
    expect(localStorage.getItem(INSPECTOR_KEY)).toBe('false')
  })

  it('closeInspectorFloat 关闭浮层（Esc / 点浮层外的入口），且不改持久化值', () => {
    const ui = narrow()
    ui.toggleInspector()
    expect(ui.inspectorFloatOpen).toBe(true)
    ui.closeInspectorFloat()
    expect(ui.inspectorFloatOpen).toBe(false)
    expect(ui.inspectorVisible).toBe(false)
    expect(ui.inspectorOpen).toBe(true)
    expect(localStorage.getItem(INSPECTOR_KEY)).toBeNull()
  })

  it('并排模式（≥1280）下 closeInspectorFloat 不动并排开关与持久化', () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      media: '',
      addEventListener: () => {},
      removeEventListener: () => {},
    }))
    setActivePinia(createPinia())
    const ui = useUiStore()
    expect(ui.inspectorOverlay).toBe(false)
    ui.closeInspectorFloat()
    expect(ui.inspectorOpen).toBe(true)
    expect(localStorage.getItem(INSPECTOR_KEY)).toBeNull()
    ui.toggleInspector()
    expect(ui.inspectorOpen).toBe(false)
    expect(localStorage.getItem(INSPECTOR_KEY)).toBe('false')
  })
})

// ---------- Bug1 补充：unknown → succeeded / cancelled 经 WS 推送也要刷新 ----------

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

function unknownRun(): RunResponse {
  return {
    run_id: 'run-1',
    task_id: 'task-1',
    operation: 'sync_build_release',
    status: 'unknown',
    reason_code: null,
    summary: '结果未能确认',
    config_revision: 1,
    phase: 'release',
    recovery_state: 'pending',
    created_at: '2026-10-28T01:21:00Z',
    started_at: '2026-10-28T01:21:01Z',
    finished_at: null,
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
      {
        step_no: 0,
        run_id: 'run-1',
        kind: 'git',
        status: 'succeeded',
        started_at: '2026-10-28T01:21:01Z',
        finished_at: '2026-10-28T01:21:10Z',
        checkpoint: {},
        target_index: null,
      } as StepView,
      {
        step_no: 1,
        run_id: 'run-1',
        kind: 'build',
        status: 'unknown',
        started_at: '2026-10-28T01:21:11Z',
        finished_at: null,
        checkpoint: {},
        target_index: 0,
      } as StepView,
    ],
    effects: [],
  } as unknown as RunResponse
}

function taskFor(status: RunResponse['status']): TaskView {
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
      status,
      created_at: '2026-10-28T01:21:00Z',
      finished_at: null,
    },
    git_flow: { build_branch: 'main' },
    targets: [],
  } as unknown as TaskView
}

describe.each([
  ['succeeded', '成功'],
  ['cancelled', '已取消'],
] as const)('Bug1：WS 推送 unknown → %s 时任务列表与运行历史刷新', (terminal, label) => {
  it('两个列表各重新请求一次以上，任务行状态与需核实横幅都更新', async () => {
    let run: RunResponse = unknownRun()
    const hits = { tasks: 0, runs: 0 }
    const fetchImpl = (async (request: Request) => {
      const url = new URL(request.url)
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') {
        hits.tasks += 1
        return json({ revision: 1, items: [taskFor(run.status)] })
      }
      if (url.pathname === '/api/runs') {
        hits.runs += 1
        return json({ cursor: null, items: [run] })
      }
      if (url.pathname.endsWith('/events')) return json({ items: [], next_seq: 1, has_more: false })
      if (url.pathname === '/api/runs/run-1') return json(run)
      return json({})
    }) as unknown as typeof fetch

    localStorage.setItem('toolbox.tasks.selection', 'task-1')
    const b = await boot({ path: '/tasks', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()
    expect(b.wrapper.find('[data-testid=unknown-banner]').exists()).toBe(true)
    const before = { ...hits }

    run = {
      ...unknownRun(),
      status: terminal,
      summary: '核对后确认结束',
      finished_at: '2026-10-28T01:25:00Z',
      recovery_state: 'reconciled',
    } as RunResponse
    b.sock.emit({
      seq: 60,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-28T01:25:00Z',
      data: {
        run_id: 'run-1',
        run_seq: 2,
        type: 'state',
        payload: { status: terminal, summary: '核对后确认结束' },
      },
    })
    await flushPromises()
    await flushPromises()
    await flushPromises()

    expect(hits.tasks).toBeGreaterThan(before.tasks)
    expect(hits.runs).toBeGreaterThan(before.runs)
    expect(b.wrapper.get('[data-testid="task-row-task-1"]').text()).toContain(label)
    expect(b.wrapper.find('[data-testid=unknown-banner]').exists()).toBe(false)
    await b.done()
  })
})
