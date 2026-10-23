import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import {
  resolveRowPillState,
  formatTime,
  type TaskView,
  type RunResponse,
} from '@/features/tasks/api'

beforeEach(() => {
  setActivePinia(createPinia())
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

const taskNeverRan: TaskView = {
  id: 'task-never',
  name: '从不运行的任务',
  enabled: true,
  repo_name: 'never-repo',
  local_repo_path: '/repos/never-repo',
  active_run_id: null,
  last_run: null,
  sort_order: 1,
  tg_command: '',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  git_flow: { build_branch: 'main' },
  targets: [],
  created_at: '2026-10-23T08:00:00Z',
  updated_at: '2026-10-23T08:00:00Z',
}

const taskFailed: TaskView = {
  id: 'task-failed',
  name: '只发布失败的任务',
  enabled: true,
  repo_name: 'fail-repo',
  local_repo_path: '/repos/fail-repo',
  active_run_id: null,
  last_run: {
    run_id: 'run-latest-2',
    status: 'failed',
    operation: 'deploy_only',
    created_at: '2026-10-23T09:00:00Z',
    finished_at: '2026-10-23T09:02:00Z',
  },
  sort_order: 2,
  tg_command: '',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  git_flow: { build_branch: 'main' },
  targets: [],
  created_at: '2026-10-23T08:00:00Z',
  updated_at: '2026-10-23T08:00:00Z',
}

const taskDisabled: TaskView = {
  ...taskNeverRan,
  id: 'task-disabled',
  name: '已停用的任务',
  enabled: false,
}

const runLatest: RunResponse = {
  run_id: 'run-latest-2',
  task_id: 'task-failed',
  operation: 'deploy_only',
  status: 'failed',
  reason_code: 'deploy_error',
  summary: '部署失败',
  config_revision: 1,
  phase: 'release',
  recovery_state: 'none',
  created_at: '2026-10-23T09:00:00Z',
  started_at: '2026-10-23T09:00:02Z',
  finished_at: '2026-10-23T09:02:00Z',
  cancel_requested_at: null,
  stop_reason: null,
  deadline_at: '2026-10-23T09:30:00Z',
  log_bytes: 100,
  last_seq: 10,
  request_hash: 'h2',
  request_id: 'r2',
  state_version: 1,
  task_snapshot: {} as unknown as RunResponse['task_snapshot'],
  updated_at: '2026-10-23T09:02:00Z',
  steps: [],
  effects: [],
}

const runOldest: RunResponse = {
  ...runLatest,
  run_id: 'run-oldest-1',
  created_at: '2026-10-23T08:00:00Z',
  started_at: '2026-10-23T08:00:02Z',
  finished_at: '2026-10-23T08:01:00Z',
}

describe('S3-C 第三轮修复验证（TDD 失败断言）', () => {
  it('1.1 列表行状态不捏造：从未运行的任务不显示状态胶囊，失败任务显示失败，绝不默认显示成功', () => {
    expect(resolveRowPillState(taskNeverRan, false, null)).toBeNull()
    expect(resolveRowPillState(taskFailed, false, null)).toBe('failed')
    expect(resolveRowPillState(taskDisabled, false, null)).toBe('disabled')
  })

  it('1.2 列表行状态在界面中真实渲染：未运行任务无 StatusPill，失败任务有“失败”胶囊', async () => {
    const fakeFetch = async (input: RequestInfo | URL) => {
      const u = new URL(typeof input === 'string' ? input : (input as Request).url)
      if (u.pathname.endsWith('/health')) {
        return new Response(
          JSON.stringify({ status: 'ok', version: '1.0', pid: 1234, uptime_s: 10, alert: false }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (u.pathname === '/api/tasks') {
        return new Response(
          JSON.stringify({
            items: [taskNeverRan, taskFailed, taskDisabled],
            revision: 1,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (u.pathname.endsWith('/events')) {
        return new Response(JSON.stringify({ items: [], has_more: false, next_seq: 1 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname.startsWith('/api/runs/')) {
        return new Response(JSON.stringify(runLatest), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname === '/api/runs') {
        return new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    }

    const b = await boot({ path: '/tasks', fetchImpl: fakeFetch as unknown as typeof fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 检查第 1 行（task-never）：不应该出现“成功”胶囊
    const neverRow = b.wrapper.find('[data-testid="task-row-task-never"]')
    expect(neverRow.exists()).toBe(true)
    expect(neverRow.text()).not.toContain('成功')

    // 检查第 2 行（task-failed）：应该展示“失败”，绝不是“成功”
    const failRow = b.wrapper.find('[data-testid="task-row-task-failed"]')
    expect(failRow.exists()).toBe(true)
    expect(failRow.text()).toContain('失败')
    expect(failRow.text()).not.toContain('成功')

    await b.done()
  })

  it('2. 列表行时间取自己的 last_run.created_at，从未运行显示“未运行”', async () => {
    const fakeFetch = async (input: RequestInfo | URL) => {
      const u = new URL(typeof input === 'string' ? input : (input as Request).url)
      if (u.pathname.endsWith('/health')) {
        return new Response(
          JSON.stringify({ status: 'ok', version: '1.0', pid: 1234, uptime_s: 10, alert: false }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (u.pathname === '/api/tasks') {
        return new Response(
          JSON.stringify({
            items: [taskNeverRan, taskFailed],
            revision: 1,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (u.pathname.endsWith('/events')) {
        return new Response(JSON.stringify({ items: [], has_more: false, next_seq: 1 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname.startsWith('/api/runs/')) {
        return new Response(JSON.stringify(runLatest), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname === '/api/runs') {
        return new Response(JSON.stringify({ items: [runLatest], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    }

    const b = await boot({ path: '/tasks', fetchImpl: fakeFetch as unknown as typeof fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const neverRow = b.wrapper.find('[data-testid="task-row-task-never"]')
    expect(neverRow.text()).toContain('未运行')

    await b.done()
  })

  it('3. useTaskRuns 使用 order=desc；默认展示最新运行，且用户点击历史行后不被后台刷新抢回', async () => {
    const requestedUrls: string[] = []
    const fakeFetch = async (input: RequestInfo | URL) => {
      const fullUrl = typeof input === 'string' ? input : (input as Request).url
      requestedUrls.push(fullUrl)
      const u = new URL(fullUrl)
      if (u.pathname.endsWith('/health')) {
        return new Response(
          JSON.stringify({ status: 'ok', version: '1.0', pid: 1234, uptime_s: 10, alert: false }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (u.pathname === '/api/tasks') {
        return new Response(
          JSON.stringify({
            items: [taskFailed],
            revision: 1,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (u.pathname.endsWith('/events')) {
        return new Response(JSON.stringify({ items: [], has_more: false, next_seq: 1 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname.startsWith('/api/runs/')) {
        const id = u.pathname.includes('run-latest-2') ? runLatest : runOldest
        return new Response(JSON.stringify(id), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname === '/api/runs') {
        // desc 排序返回 [runLatest, runOldest]
        return new Response(JSON.stringify({ items: [runLatest, runOldest], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    }

    const b = await boot({ path: '/tasks', fetchImpl: fakeFetch as unknown as typeof fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 验证发起的 runs 请求带有 order=desc
    const runsReq = requestedUrls.find((u) => u.includes('/api/runs?') && u.includes('task_id='))
    expect(runsReq).toBeDefined()
    expect(runsReq).toContain('order=desc')

    // 默认展示最新运行（runLatest，即 started_at 较新的运行）
    const runCard = b.wrapper.find('[data-testid=run-card]')
    expect(runCard.exists()).toBe(true)
    expect(runCard.text()).toContain(formatTime(runLatest.started_at))

    // 用户手动在历史表中点击更旧的运行 (run-oldest-1)
    const historyTable = b.wrapper.find('[data-testid=runs-history-table]')
    expect(historyTable.exists()).toBe(true)
    const oldRow = historyTable.find('[data-testid="run-history-row-run-oldest-1"]')
    expect(oldRow.exists()).toBe(true)
    await oldRow.trigger('click')
    await flushPromises()
    // 卡片切换为旧运行
    expect(b.wrapper.find('[data-testid=run-card]').text()).toContain(
      formatTime(runOldest.started_at),
    )

    // 触发后台刷新（WS 心跳或 state 事件）
    b.sock.emit({
      seq: 99,
      topic: 'system',
      type: 'system.heartbeat',
      ts: new Date().toISOString(),
      data: {},
    })
    await flushPromises()

    // 用户选择不应被抢回重置为最新运行
    expect(b.wrapper.find('[data-testid=run-card]').text()).toContain(
      formatTime(runOldest.started_at),
    )

    await b.done()
  })
})
