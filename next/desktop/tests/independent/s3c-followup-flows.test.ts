import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import RunCard from '@/features/tasks/RunCard.vue'
import { boot } from '../unit/boot'
import { FakeSocket, hello, resetSeq } from '../unit/helpers'
import { createWiFake, wiErr } from '../unit/wi-fake'
import { openWi, settle } from '../unit/wi-helpers'

type S = components['schemas']
type TaskView = S['TaskView']
type RunResponse = S['RunResponse']
type PlanResponse = S['PlanResponse']

const task: TaskView = {
  id: 'task-followup',
  name: '跟进任务',
  enabled: true,
  sort_order: 1,
  local_repo_path: '/tmp/followup',
  tg_command: '',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  active_run_id: null,
  last_run: null,
}
const commit = '0123456789abcdef0123456789abcdef01234567'
const plan = (planId: string): PlanResponse => ({
  plan_id: planId,
  expires_at: '2026-10-23T10:05:00Z',
  revision: 1,
  task_summary: { id: task.id, name: task.name },
  steps: [{ kind: 'build', target_index: 0 }],
  targets: [
    {
      target_index: 0,
      name: '生产',
      definition_id: 1,
      release_definition_id: 2,
      stage_ids: [3],
      build_id: 4,
      release_id: 5,
      commit,
    },
  ],
  warnings: [],
})
const run = (status: RunResponse['status'], over: Partial<RunResponse> = {}): RunResponse => ({
  run_id: 'run-followup',
  task_id: task.id,
  operation: 'sync_build_release',
  status,
  reason_code: null,
  summary: '服务摘要',
  config_revision: 1,
  phase: 'build',
  recovery_state: 'none',
  created_at: '2026-10-23T09:00:00Z',
  started_at: '2026-10-23T09:00:01Z',
  finished_at: null,
  cancel_requested_at: null,
  deadline_at: '2026-10-23T09:30:00Z',
  log_bytes: 0,
  last_seq: 0,
  request_hash: 'hash',
  request_id: 'request-followup',
  state_version: 1,
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
  ...over,
})
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
  document.body.innerHTML = ''
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('S3-C 独立补充路径', () => {
  it.each(['plan_expired', 'plan_changed'] as const)(
    '预检错误 %s 可恢复：重新预检后再次启动并生成新的 request_id',
    async (code) => {
      const posted: S['StartRequest'][] = []
      const plans = [plan('plan-old'), plan('plan-new')]
      let preflights = 0
      const fetchImpl: typeof fetch = async (request) => {
        const req = request as Request
        const url = new URL(req.url)
        if (url.pathname === '/health')
          return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
        if (url.pathname === '/api/tasks') return json({ revision: 1, items: [task] })
        if (url.pathname === '/api/runs') return json({ cursor: null, items: [] })
        if (url.pathname === `/api/tasks/${task.id}/preflight`) return json(plans[preflights++]!)
        if (url.pathname === `/api/tasks/${task.id}/runs`) {
          posted.push((await req.json()) as S['StartRequest'])
          return posted.length === 1
            ? json({ detail: { code, message: code } }, 409)
            : json({ run_id: 'run-followup' }, 202)
        }
        if (url.pathname === '/api/runs/run-followup') return json(run('queued'))
        if (url.pathname === '/api/runs/run-followup/events')
          return json({ items: [], next_seq: 0, has_more: false })
        return json({})
      }
      const b = await boot({ path: '/tasks', fetchImpl })
      b.sock.emit(hello())
      await flushPromises()
      await b.wrapper.get('[data-testid="run-task-btn"]').trigger('click')
      await flushPromises()
      const acknowledge = () => {
        const checkbox = document.querySelector(
          '[data-testid="ack-old-app-idle-checkbox"]',
        ) as HTMLInputElement
        checkbox.checked = true
        checkbox.dispatchEvent(new Event('change', { bubbles: true }))
      }
      acknowledge()
      await flushPromises()
      const firstButton = document.querySelector(
        '[data-testid="confirm-start-btn"]',
      ) as HTMLButtonElement
      firstButton.click()
      await flushPromises()
      expect(document.querySelector('[data-testid="plan-error-banner"]')?.textContent).toContain(
        '重新确认',
      )
      const firstRequestId = posted[0]?.request_id
      const close = document.querySelector('[data-testid="sheet"] button') as HTMLButtonElement
      close.click()
      await flushPromises()
      await b.wrapper.get('[data-testid="run-task-btn"]').trigger('click')
      await flushPromises()
      acknowledge()
      await flushPromises()
      ;(document.querySelector('[data-testid="confirm-start-btn"]') as HTMLButtonElement).click()
      await flushPromises()
      expect(preflights).toBe(2)
      expect(posted).toHaveLength(2)
      expect(posted[0]?.plan_id).toBe('plan-old')
      expect(posted[1]?.plan_id).toBe('plan-new')
      expect(posted[1]?.request_id).not.toBe(firstRequestId)
      await b.done()
    },
  )

  it('取消只发一次请求；cancelling 与终态都由服务状态事件驱动，unknown 不冒称已取消', async () => {
    let cancelCalls = 0
    let serverStatus: RunResponse['status'] = 'running'
    const activeTask = { ...task, active_run_id: 'run-followup' }
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      const url = new URL(req.url)
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') return json({ revision: 1, items: [activeTask] })
      if (url.pathname === '/api/runs') return json({ cursor: null, items: [run('running')] })
      if (url.pathname === '/api/runs/run-followup/events')
        return json({ items: [], next_seq: 0, has_more: false })
      if (url.pathname === '/api/runs/run-followup/cancel' && req.method === 'POST') {
        cancelCalls++
        return json(run('cancelling'))
      }
      if (url.pathname === '/api/runs/run-followup') return json(run(serverStatus))
      return json({})
    }
    const b = await boot({ path: '/tasks', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()
    await b.wrapper.get('[data-testid="cancel-run-btn"]').trigger('click')
    await flushPromises()
    ;(document.querySelector('[data-testid="confirm-cancel-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(cancelCalls).toBe(1)
    expect(b.wrapper.get('[data-testid="run-card"]').text()).toContain('运行中')
    serverStatus = 'cancelling'
    b.sock.emit({
      seq: 1,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-23T09:00:02Z',
      data: {
        run_id: 'run-followup',
        run_seq: 1,
        type: 'state',
        payload: { status: 'cancelling', summary: '停止请求已提交' },
      },
    })
    await flushPromises()
    expect(b.wrapper.get('[data-testid="run-card"]').text()).toContain('停止中')
    serverStatus = 'unknown'
    b.sock.emit({
      seq: 2,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-23T09:00:03Z',
      data: {
        run_id: 'run-followup',
        run_seq: 2,
        type: 'state',
        payload: { status: 'unknown', summary: '远端可能仍在运行' },
      },
    })
    await flushPromises()
    expect(b.wrapper.get('[data-testid="unknown-banner"]').text()).toContain('结果需要核实')
    expect(b.wrapper.text()).not.toContain('已取消')
    await b.done()
  })

  it('失败运行卡片显示服务 reason_code 中文映射与原始 summary', async () => {
    const wrapper = mount(RunCard, {
      props: {
        run: run('failed', { reason_code: 'build_failed', summary: '构建代理返回退出码 17' }),
        steps: [],
        lines: [],
      },
      attachTo: document.body,
    })
    await flushPromises()
    const notice = wrapper.get('[data-testid="run-reason-banner"]').text()
    expect(notice).toContain('构建失败')
    expect(notice).toContain('构建代理返回退出码 17')
    expect(notice).not.toContain('运行失败，请重试')
    wrapper.unmount()
  })

  it('工单无凭据错误呈现居中错误 EmptyState，重试重发请求且设置入口可用', async () => {
    const fake = createWiFake()
    let adoAttempts = 0
    const fetchImpl: typeof fetch = async (request) => {
      const req = request as Request
      if (new URL(req.url).pathname === '/api/ado') {
        adoAttempts++
        return wiErr(401, 'no_credential')
      }
      return fake.fetch(req)
    }
    const b = await openWi({ ...fake, fetch: fetchImpl })
    const state = b.wrapper.get('[data-testid="wi-error"]')
    expect(state.text()).toContain('无法读取工单')
    expect(state.classes()).toContain('wi-error')
    expect(b.wrapper.find('[data-testid="banner"]').exists()).toBe(false)
    expect(state.text()).toContain('前往设置')
    const attempts = adoAttempts
    await state.get('button').trigger('click')
    await settle()
    expect(adoAttempts).toBeGreaterThan(attempts)
    expect(b.wrapper.get('[data-testid="wi-error"]').text()).toContain('无法读取工单')
    await b.done()
  })
})
