import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import RunConfirmSheet from '@/features/tasks/RunConfirmSheet.vue'
import LogPanel from '@/features/tasks/LogPanel.vue'
import { ApiError, errorText, TASK_ERROR_MESSAGES } from '@/features/tasks/api'
import { boot, pickCommand } from '../unit/boot'
import { FakeSocket, hello, resetSeq } from '../unit/helpers'

type TaskView = components['schemas']['TaskView']
type PlanResponse = components['schemas']['PlanResponse']
type RunResponse = components['schemas']['RunResponse']

const task: TaskView = {
  id: 'task-contract',
  name: '合同测试任务',
  enabled: true,
  sort_order: 1,
  local_repo_path: '/tmp/repo',
  tg_command: '',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  active_run_id: null,
  last_run: null,
}

const commit = '0123456789abcdef0123456789abcdef01234567'
const cleanups: Array<() => void> = []
const plan: PlanResponse = {
  plan_id: 'plan-contract',
  expires_at: '2026-10-23T10:05:00Z',
  revision: 7,
  task_summary: { id: task.id, name: task.name },
  steps: [{ kind: 'release', target_index: 0 }],
  targets: [
    {
      target_index: 0,
      name: '生产环境',
      definition_id: 21,
      release_definition_id: 22,
      stage_ids: [3],
      build_id: 731,
      release_id: 842,
      commit,
    },
  ],
  warnings: [],
}

function snapshotRun(status: RunResponse['status']): RunResponse {
  return {
    run_id: 'run-contract',
    task_id: task.id,
    operation: 'deploy_only',
    status,
    reason_code: null,
    summary: status === 'unknown' ? '远端结果待核实' : '运行中',
    config_revision: 7,
    phase: 'release',
    recovery_state: status === 'unknown' ? 'pending' : 'none',
    created_at: '2026-10-23T09:00:00Z',
    started_at: '2026-10-23T09:00:01Z',
    finished_at: null,
    cancel_requested_at: null,
    deadline_at: '2026-10-23T09:30:00Z',
    log_bytes: 0,
    last_seq: 0,
    request_hash: 'request-hash',
    request_id: 'request-id',
    state_version: 2,
    stop_reason: null,
    updated_at: '2026-10-23T09:00:01Z',
    task_snapshot: {
      id: task.id,
      name: task.name,
      enabled: true,
      sort_order: 1,
      local_repo_path: task.local_repo_path,
      tg_command: '',
      tg_desc: '',
    },
    steps: [],
    effects: [],
  }
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('S3-C 独立契约观察', () => {
  it('启动错误码映射为可操作中文说明', () => {
    expect(TASK_ERROR_MESSAGES.plan_expired).toContain('重新确认')
    expect(TASK_ERROR_MESSAGES.plan_changed).toContain('重新确认')
    expect(TASK_ERROR_MESSAGES.task_active).toContain('正在运行中')
    expect(TASK_ERROR_MESSAGES.busy).toContain('稍后重试')
    expect(TASK_ERROR_MESSAGES.run_store_unavailable).toContain('只读模式')
    expect(TASK_ERROR_MESSAGES.revision_conflict).toContain('刷新后重试')
    expect(errorText(new ApiError(503, 'busy', ''))).toContain('系统繁忙')
  })

  it('只发布确认单保留完整 build id 与完整 commit', async () => {
    const wrapper = mount(RunConfirmSheet, {
      props: {
        open: true,
        task,
        operation: 'deploy_only',
        plan,
        'onUpdate:open': () => undefined,
        onConfirm: () => undefined,
      },
      attachTo: document.body,
    })
    cleanups.push(() => wrapper.unmount())
    await flushPromises()

    const copy = document.body.textContent ?? ''
    expect(copy).toContain('731')
    expect(copy).toContain(commit)
    expect(copy).not.toContain('0123456)')

    const start = document.querySelector('[data-testid="confirm-start-btn"]') as HTMLButtonElement
    // 计划带 commit，无需勾选即可开始
    expect(start.disabled).toBe(false)
  })

  it('回滚确认显示完整历史 Release id 与完整 commit', async () => {
    const wrapper = mount(RunConfirmSheet, {
      props: {
        open: true,
        task,
        operation: 'rollback',
        plan,
      },
      attachTo: document.body,
    })
    cleanups.push(() => wrapper.unmount())
    await flushPromises()
    expect(document.body.textContent).toContain('Release #842')
    expect(document.body.textContent).toContain(commit)
  })

  it('运行确认快速双击只 POST 一次；服务拒绝后重试沿用原 request_id，202 只显示服务快照状态', async () => {
    const posted: components['schemas']['StartRequest'][] = []
    let calls = 0
    const queued = snapshotRun('queued')
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      const url = new URL(req.url)
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') return json({ revision: 7, items: [task] })
      if (url.pathname === '/api/runs') return json({ cursor: null, items: [] })
      if (url.pathname === '/api/tasks/task-contract/preflight') return json(plan)
      if (url.pathname === '/api/tasks/task-contract/runs') {
        posted.push((await req.json()) as components['schemas']['StartRequest'])
        calls++
        if (calls === 1) return json({ detail: { code: 'busy', message: 'busy' } }, 503)
        return json({ run_id: queued.run_id }, 202)
      }
      if (url.pathname === `/api/runs/${queued.run_id}/events`)
        return json({ items: [], next_seq: 0, has_more: false })
      if (url.pathname === `/api/runs/${queued.run_id}`) return json(queued)
      return json({})
    }
    const b = await boot({ path: '/tasks', fetchImpl })
    cleanups.push(() => {
      b.runtime.stop()
      b.wrapper.unmount()
    })
    b.sock.emit(hello())
    await flushPromises()
    await pickCommand(b, 'task-contract')
    const start = document.querySelector('[data-testid="confirm-start-btn"]') as HTMLButtonElement

    start.click()
    start.click()
    await flushPromises()
    expect(posted).toHaveLength(1)
    expect(document.body.textContent).toContain('系统繁忙')

    const retry = document.querySelector('[data-testid="confirm-start-btn"]') as HTMLButtonElement
    retry.click()
    await flushPromises()
    expect(posted).toHaveLength(2)
    expect(posted[1]?.request_id).toBe(posted[0]?.request_id)
    expect(b.wrapper.find('[data-testid="run-card"]').text()).toContain('排队中')
    expect(b.wrapper.find('[data-testid="run-card"]').text()).not.toContain('成功')
    await b.done()
  })

  it('unknown 运行只显示核实语义；立即核对发 POST 且不发送请求体，storage 不收录 token/日志/草稿', async () => {
    const requests: Array<{ method: string; url: string; body: string }> = []
    const run = snapshotRun('unknown')
    const unknownTask: TaskView = {
      ...task,
      active_run_id: run.run_id,
      last_run: {
        run_id: run.run_id,
        status: 'unknown',
        operation: run.operation,
        created_at: run.created_at,
        finished_at: null,
      },
    }
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      const url = new URL(req.url)
      const body = await req.clone().text()
      requests.push({ method: req.method, url: url.pathname, body })
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') return json({ revision: 7, items: [unknownTask] })
      if (url.pathname === '/api/runs') return json({ cursor: null, items: [run] })
      if (url.pathname === `/api/runs/${run.run_id}/events`)
        return json({ items: [], next_seq: 0, has_more: false })
      if (url.pathname === `/api/runs/${run.run_id}/reconcile`) return json(run, 202)
      if (url.pathname === `/api/runs/${run.run_id}`) return json(run)
      return json({})
    }

    const b = await boot({ path: '/tasks', fetchImpl })
    cleanups.push(() => {
      b.runtime.stop()
      b.wrapper.unmount()
    })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    expect(b.wrapper.get('[data-testid="unknown-banner"]').text()).toContain('结果需要核实')
    expect(b.wrapper.get('[data-testid="unknown-banner"]').text()).toContain('停止不会回滚')
    expect(b.wrapper.text()).not.toContain('已取消')
    expect(b.wrapper.text()).not.toContain('已失败')

    await b.wrapper.get('[data-testid="reconcile-btn"]').trigger('click')
    await flushPromises()
    const request = requests.find((r) => r.url.endsWith('/reconcile'))
    expect(request).toEqual({ method: 'POST', url: `/api/runs/${run.run_id}/reconcile`, body: '' })

    expect(localStorage.getItem('toolbox.tasks.selection')).toBe(task.id)
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)!
      expect(key).toContain('selection')
      expect(localStorage.getItem(key)).not.toContain('fake-token')
      expect(localStorage.getItem(key)).not.toContain('远端结果待核实')
    }
    expect(sessionStorage.length).toBe(0)
    expect(b.sock.url).not.toContain('fake-token')
    expect(document.body.innerHTML).not.toContain('fake-token')
    await b.done()
  })

  it('日志内容作为纯文本显示，ANSI 与 HTML 字符串不被解释，日志面板不补造逐行时间戳', async () => {
    const line = '\u001b[31m<img src=x onerror="window.__pwned=1">\u001b[0m'
    const wrapper = mount(LogPanel, {
      props: { lines: [{ seq: 6, text: line }], totalLineCount: 1 },
      attachTo: document.body,
    })
    cleanups.push(() => wrapper.unmount())
    await flushPromises()

    expect(wrapper.find('[data-testid="log-content"]').text()).toContain(line)
    expect(document.querySelector('[data-testid="log-content"] img')).toBeNull()
    expect((window as unknown as { __pwned?: unknown }).__pwned).toBeUndefined()
    expect(wrapper.findAll('.log-line').length).toBe(1)
    expect(wrapper.find('.log-line').text()).not.toMatch(/\d{2}:\d{2}:\d{2}/)
  })
})
