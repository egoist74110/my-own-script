import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import RunHistory from '@/features/tasks/RunHistory.vue'
import { formatDateTime } from '@/features/tasks/api'
import { boot, pickCommand } from '../unit/boot'
import { FakeSocket, hello, resetSeq } from '../unit/helpers'

type S = components['schemas']
type RunResponse = S['RunResponse']
const task: S['TaskView'] = {
  id: 'task-keys',
  name: '键盘任务',
  enabled: true,
  sort_order: 1,
  local_repo_path: '/tmp/keys',
  tg_command: '',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  active_run_id: null,
  last_run: null,
}
const run = (id: string, date: string): RunResponse => ({
  run_id: id,
  task_id: task.id,
  operation: 'sync_build_release',
  status: 'succeeded',
  reason_code: null,
  summary: id,
  config_revision: 1,
  phase: 'done',
  recovery_state: 'none',
  created_at: date,
  started_at: date,
  finished_at: date,
  cancel_requested_at: null,
  deadline_at: date,
  log_bytes: 0,
  last_seq: 0,
  request_hash: 'hash',
  request_id: `request-${id}`,
  state_version: 1,
  stop_reason: null,
  updated_at: date,
  task_snapshot: {
    id: task.id,
    name: task.name,
    enabled: true,
    sort_order: 1,
    local_repo_path: '/tmp/keys',
    tg_command: '',
    tg_desc: '',
  },
  steps: [],
  effects: [],
})
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  document.body.innerHTML = ''
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('S3-C 独立历史与键盘交互', () => {
  it('历史各行使用各自 run 的开始时间，Enter 可选中有焦点的历史行', async () => {
    const first = run('run-new', '2026-10-23T09:00:00Z')
    const second = run('run-old', '2026-10-21T09:00:00Z')
    const selected: RunResponse[] = []
    const wrapper = mount(RunHistory, {
      props: { runs: [first, second], onSelect: (value) => selected.push(value) },
    })
    const newRow = wrapper.get('[data-testid="run-history-row-run-new"]')
    const oldRow = wrapper.get('[data-testid="run-history-row-run-old"]')
    expect(newRow.text()).toContain(formatDateTime(first.started_at))
    expect(oldRow.text()).toContain(formatDateTime(second.started_at))
    expect(newRow.text()).not.toBe(oldRow.text())
    await oldRow.trigger('keydown.enter')
    expect(selected.map((r) => r.run_id)).toEqual(['run-old'])
    wrapper.unmount()
  })

  it('任务列表行可通过 Tab 聚焦并用 Enter 选择', async () => {
    const second: S['TaskView'] = { ...task, id: 'task-keys-2', name: '第二个任务' }
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      const url = new URL(req.url)
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') return json({ revision: 1, items: [task, second] })
      if (url.pathname === '/api/runs') return json({ cursor: null, items: [] })
      return json({})
    }
    const b = await boot({ path: '/tasks', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    const row = b.wrapper.get('[data-testid="task-row-task-keys-2"]')
    expect(row.element.tagName).toBe('BUTTON')
    expect((row.element as HTMLButtonElement).tabIndex).toBe(0)
    ;(row.element as HTMLButtonElement).focus()
    expect(document.activeElement).toBe(row.element)
    // jsdom 不合成浏览器对 Enter 的原生 button click 默认动作；核对键盘事件和其默认激活目标。
    await row.trigger('keydown.enter')
    ;(row.element as HTMLButtonElement).click()
    await flushPromises()
    expect(row.attributes('aria-current')).toBe('true')
    await b.done()
  })

  it('活动运行结束后自动跟随服务返回的最新 run', async () => {
    const live = {
      ...run('run-live', '2026-10-23T09:00:00Z'),
      status: 'running' as const,
      summary: '当前运行',
    }
    const latest = { ...run('run-latest', '2026-10-23T10:00:00Z'), summary: '终态后最新运行' }
    const old = run('run-old-auto', '2026-10-20T10:00:00Z')
    let taskState: S['TaskView'] = { ...task, active_run_id: live.run_id }
    let items: RunResponse[] = [live, old]
    const byId = new Map([
      [live.run_id, live],
      [latest.run_id, latest],
      [old.run_id, old],
    ])
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      const url = new URL(req.url)
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') return json({ revision: 1, items: [taskState] })
      if (url.pathname === '/api/runs') return json({ cursor: null, items })
      const match = /^\/api\/runs\/(.+?)(?:\/events)?$/.exec(url.pathname)
      if (match?.[1] && url.pathname.endsWith('/events'))
        return json({ items: [], next_seq: 0, has_more: false })
      if (match?.[1]) return json(byId.get(match[1]) ?? latest)
      return json({})
    }
    const b = await boot({ path: '/tasks', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()
    taskState = {
      ...taskState,
      active_run_id: null,
      last_run: {
        run_id: latest.run_id,
        status: 'succeeded',
        operation: latest.operation,
        created_at: latest.created_at,
        finished_at: latest.finished_at,
      },
    }
    items = [latest, live, old]
    b.sock.emit({
      seq: 1,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-23T10:00:00Z',
      data: {
        run_id: live.run_id,
        run_seq: 1,
        type: 'state',
        payload: { status: 'succeeded', summary: '当前结束' },
      },
    })
    for (let i = 0; i < 8; i++) await flushPromises()
    expect(
      b.wrapper.find('[data-testid="run-history-row-run-latest"]').attributes('data-selected'),
    ).toBe('true')
    await b.done()
  })

  it('用户选中的历史 run 在后台列表刷新时保留，不被最新 run 抢回', async () => {
    const latest = run('run-latest-manual', '2026-10-23T10:00:00Z')
    const old = {
      ...run('run-old-manual', '2026-10-20T10:00:00Z'),
      status: 'running' as const,
      summary: '手动历史',
    }
    const newest = {
      ...run('run-newest-manual', '2026-10-24T10:00:00Z'),
      summary: '刷新产生的新记录',
    }
    let taskState: S['TaskView'] = {
      ...task,
      last_run: {
        run_id: latest.run_id,
        status: 'succeeded',
        operation: latest.operation,
        created_at: latest.created_at,
        finished_at: latest.finished_at,
      },
    }
    let items: RunResponse[] = [latest, old]
    const byId = new Map([
      [latest.run_id, latest],
      [old.run_id, old],
      [newest.run_id, newest],
    ])
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      const url = new URL(req.url)
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') return json({ revision: 1, items: [taskState] })
      if (url.pathname === '/api/runs') return json({ cursor: null, items })
      const match = /^\/api\/runs\/(.+?)(?:\/events)?$/.exec(url.pathname)
      if (url.pathname.endsWith('/events') && match?.[1])
        return json({ items: [], next_seq: 0, has_more: false })
      if (match?.[1]) return json(byId.get(match[1]) ?? latest)
      return json({})
    }
    const b = await boot({ path: '/tasks', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()
    await b.wrapper.get('[data-testid="run-history-row-run-old-manual"]').trigger('click')
    await flushPromises()
    taskState = {
      ...taskState,
      last_run: {
        run_id: newest.run_id,
        status: 'succeeded',
        operation: newest.operation,
        created_at: newest.created_at,
        finished_at: newest.finished_at,
      },
    }
    items = [newest, latest, { ...old, status: 'failed', summary: '手动历史失败' }]
    byId.set(old.run_id, items[2]!)
    b.sock.emit({
      seq: 1,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-23T10:00:00Z',
      data: {
        run_id: old.run_id,
        run_seq: 1,
        type: 'state',
        payload: { status: 'failed', summary: '手动历史失败' },
      },
    })
    for (let i = 0; i < 8; i++) await flushPromises()
    expect(b.wrapper.get('[data-testid="run-card"]').text()).toContain('手动历史失败')
    expect(
      b.wrapper.find('[data-testid="run-history-row-run-old-manual"]').attributes('data-selected'),
    ).toBe('true')
    expect(
      b.wrapper
        .find('[data-testid="run-history-row-run-newest-manual"]')
        .attributes('data-selected'),
    ).toBe('false')
    await b.done()
  })

  it('运行确认 Sheet 焦点留在 Sheet 内，Tab 可循环，Enter 确认且 Esc 关闭不发启动请求', async () => {
    let starts = 0
    const plan: S['PlanResponse'] = {
      plan_id: 'plan-key',
      expires_at: '2026-10-23T10:00:00Z',
      revision: 1,
      task_summary: { id: task.id, name: task.name },
      steps: [{ kind: 'git' }],
      targets: [],
      warnings: [],
    }
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      const url = new URL(req.url)
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') return json({ revision: 1, items: [task] })
      if (url.pathname === '/api/runs') return json({ cursor: null, items: [] })
      if (url.pathname === `/api/tasks/${task.id}/preflight`) return json(plan)
      if (url.pathname === `/api/tasks/${task.id}/runs`) {
        starts++
        return json({ run_id: 'run-key' }, 202)
      }
      return json({})
    }
    const b = await boot({ path: '/tasks', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    await pickCommand(b, task.id)
    let sheet = document.querySelector('[data-testid="sheet"]') as HTMLElement
    expect(sheet.contains(document.activeElement)).toBe(true)
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    )
    await flushPromises()
    expect(document.querySelector('[data-testid="sheet"]')).toBeNull()
    expect(starts).toBe(0)
    await pickCommand(b, task.id)
    sheet = document.querySelector('[data-testid="sheet"]') as HTMLElement
    expect(sheet.contains(document.activeElement)).toBe(true)
    // 原生 button 参与焦点序列，Tab 前进后再 Shift+Tab 回到确认按钮。
    const actionButtons = [...sheet.querySelectorAll('button:not(:disabled)')]
    const confirm = document.querySelector('[data-testid="confirm-start-btn"]') as HTMLButtonElement
    expect(actionButtons).toContain(confirm)
    confirm.focus()
    expect(sheet.contains(document.activeElement)).toBe(true)
    confirm.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }),
    )
    expect(sheet.contains(document.activeElement)).toBe(true)
    expect(document.activeElement).not.toBe(confirm)
    document.activeElement?.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: 'Tab',
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    )
    expect(document.activeElement).toBe(confirm)
    confirm.focus()
    confirm.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
    )
    // 在 DOM 测试环境中用原生 click 默认动作模拟键盘 Enter 激活。
    confirm.click()
    await flushPromises()
    expect(starts).toBe(1)
    await b.done()
  })
})
