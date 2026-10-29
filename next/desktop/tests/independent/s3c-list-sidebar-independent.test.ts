import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { boot } from '../unit/boot'
import { FakeSocket, hello, resetSeq } from '../unit/helpers'

type TaskView = components['schemas']['TaskView']
type RunResponse = components['schemas']['RunResponse']

const baseTask = (id: string, name: string): TaskView => ({
  id,
  name,
  enabled: true,
  sort_order: 1,
  local_repo_path: `/tmp/${id}`,
  tg_command: '',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  active_run_id: null,
  last_run: null,
})

function run(status: RunResponse['status'], lastSeq: number): RunResponse {
  return {
    run_id: 'run-active',
    task_id: 'task-active',
    operation: 'sync_build_release',
    status,
    reason_code: null,
    summary: '服务快照状态',
    config_revision: 2,
    phase: 'git',
    recovery_state: 'none',
    created_at: '2026-10-23T09:00:00Z',
    started_at: '2026-10-23T09:00:01Z',
    finished_at: status === 'succeeded' ? '2026-10-23T09:00:03Z' : null,
    cancel_requested_at: null,
    deadline_at: '2026-10-23T09:30:00Z',
    log_bytes: 0,
    last_seq: lastSeq,
    request_hash: 'hash',
    request_id: 'request-active',
    state_version: lastSeq + 1,
    stop_reason: null,
    updated_at: '2026-10-23T09:00:03Z',
    task_snapshot: {
      id: 'task-active',
      name: '活动任务',
      enabled: true,
      sort_order: 1,
      local_repo_path: '/tmp/task-active',
      tg_command: '',
      tg_desc: '',
    },
    steps: [],
    effects: [],
  }
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  localStorage.setItem('toolbox.tasks.selection', 'task-active')
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('S3-C 独立列表与侧栏状态', () => {
  it('无 last_run 行不伪造状态；命令停用不冒充配置状态；任务角标随服务的 active_run_id 消失', async () => {
    const never = baseTask('task-never', '从未运行')
    const disabled: TaskView = { ...baseTask('task-disabled', '停用任务'), enabled: false }
    let active: TaskView = { ...baseTask('task-active', '活动任务'), active_run_id: 'run-active' }
    let snapshot = run('running', 0)
    const historyQueries: URL[] = []
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      const url = new URL(req.url)
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks')
        return json({ revision: 2, items: [never, disabled, active] })
      if (url.pathname === '/api/runs') {
        historyQueries.push(url)
        return json({
          cursor: null,
          items: url.searchParams.get('task_id') === 'task-active' ? [snapshot] : [],
        })
      }
      if (url.pathname === '/api/runs/run-active/events')
        return json({ items: [], next_seq: 0, has_more: false })
      if (url.pathname === '/api/runs/run-active') return json(snapshot)
      return json({})
    }
    const b = await boot({ path: '/tasks', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const neverRow = b.wrapper.get('[data-testid="task-row-task-never"]')
    expect(neverRow.text()).toContain('未运行')
    expect(neverRow.find('.row-pill-wrap').exists()).toBe(false)
    // 发布配置没有“停用”状态；状态只取最近一次运行，停用命令的配置也不伪造状态
    const disabledRow = b.wrapper.get('[data-testid="task-row-task-disabled"]')
    expect(disabledRow.text()).toContain('停用任务')
    expect(disabledRow.find('.row-pill-wrap').exists()).toBe(false)
    expect(historyQueries.some((url) => url.searchParams.get('order') === 'desc')).toBe(true)
    expect(b.wrapper.find('[data-testid="task-badge"]').text()).toBe('1 运行中')
    await b.wrapper.get('[data-testid="task-row-task-active"]').trigger('click')
    await flushPromises()

    active = { ...active, active_run_id: null }
    snapshot = run('succeeded', 1)
    b.sock.emit({
      seq: 1,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-23T09:00:03Z',
      data: {
        run_id: 'run-active',
        run_seq: 1,
        type: 'state',
        payload: { status: 'succeeded', summary: '完成' },
      },
    })
    await flushPromises()
    await flushPromises()
    expect(b.wrapper.get('[data-testid="run-card"]').text()).toContain('成功')
    expect(b.wrapper.find('[data-testid="task-badge"]').exists()).toBe(false)
    await b.done()
  })
})
