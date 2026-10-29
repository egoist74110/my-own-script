import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RunConfirmSheet from '@/features/tasks/RunConfirmSheet.vue'
import RunCard from '@/features/tasks/RunCard.vue'
import { boot, pickCommand } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import {
  formatRunReason,
  RUN_REASON_MESSAGES,
  type PlanResponse,
  type RunResponse,
  type TaskView,
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

const fakeTask: TaskView = {
  id: 'task-test',
  name: '测试任务',
  enabled: true,
  repo_name: 'test-repo',
  local_repo_path: '/repos/test-repo',
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

const fullCommit = '0123456789abcdef0123456789abcdef01234567'

const planWithCommit: PlanResponse = {
  plan_id: 'plan-1',
  expires_at: '2026-10-23T10:00:00Z',
  revision: 1,
  task_summary: { id: fakeTask.id, name: fakeTask.name },
  steps: [{ kind: 'release', target_index: 0 }],
  warnings: [],
  targets: [
    {
      target_index: 0,
      name: '生产环境',
      definition_id: 10,
      release_definition_id: 20,
      stage_ids: [1],
      build_id: 731,
      release_id: 842,
      commit: fullCommit,
    },
  ],
}

const planWithoutCommit: PlanResponse = {
  ...planWithCommit,
  plan_id: 'plan-no-commit',
  targets: [
    {
      target_index: 0,
      name: '生产环境',
      definition_id: 10,
      release_definition_id: 20,
      stage_ids: [1],
      build_id: 731,
      release_id: 842,
      commit: null,
    },
  ],
}

describe('S3-C 第四轮修复验证（TDD 失败断言）', () => {
  it('1. 只发布确认单展示完整 commit 且等宽可选；无 commit 时提示“计划未提供 commit”并禁用开始运行', async () => {
    // A. 完整 commit
    const w1 = mount(RunConfirmSheet, {
      props: {
        open: true,
        task: fakeTask,
        operation: 'deploy_only',
        plan: planWithCommit,
      },
      attachTo: document.body,
    })
    await flushPromises()
    const text1 = document.body.textContent ?? ''
    expect(text1).toContain('731')
    expect(text1).toContain(fullCommit)
    expect(text1).not.toContain('0123456)')
    expect(text1).not.toContain('最新')
    w1.unmount()
    document.body.innerHTML = ''

    // B. 无 commit
    const w2 = mount(RunConfirmSheet, {
      props: {
        open: true,
        task: fakeTask,
        operation: 'deploy_only',
        plan: planWithoutCommit,
      },
      attachTo: document.body,
    })
    await flushPromises()
    const text2 = document.body.textContent ?? ''
    expect(text2).toContain('计划未提供 commit')
    expect(text2).not.toContain('最新')

    const startBtn = document.querySelector(
      '[data-testid="confirm-start-btn"]',
    ) as HTMLButtonElement
    expect(startBtn.disabled).toBe(true)

    w2.unmount()
  })

  it('2. 回滚确认单展示完整 Release id 与完整 commit；无 commit 时提示“计划未提供 commit”并禁用', async () => {
    // A. 完整 commit
    const w1 = mount(RunConfirmSheet, {
      props: {
        open: true,
        task: fakeTask,
        operation: 'rollback',
        plan: planWithCommit,
      },
      attachTo: document.body,
    })
    await flushPromises()
    expect(document.body.textContent).toContain('Release #842')
    expect(document.body.textContent).toContain(fullCommit)
    expect(document.body.textContent).not.toContain('0123456)')
    w1.unmount()
    document.body.innerHTML = ''

    // B. 无 commit
    const w2 = mount(RunConfirmSheet, {
      props: {
        open: true,
        task: fakeTask,
        operation: 'rollback',
        plan: planWithoutCommit,
      },
      attachTo: document.body,
    })
    await flushPromises()
    expect(document.body.textContent).toContain('计划未提供 commit')
    const startBtn = document.querySelector(
      '[data-testid="confirm-start-btn"]',
    ) as HTMLButtonElement
    expect(startBtn.disabled).toBe(true)
    w2.unmount()
  })

  it('3. RunCard 在 failed/unknown/cancelled 态展示服务的 reason_code 中文说明与 summary，且不自造原因', () => {
    expect(formatRunReason('release_failed')).toBe('发布部署失败')
    expect(formatRunReason('build_failed')).toBe('构建失败')
    expect(RUN_REASON_MESSAGES.remote_unknown).toBe('远端状态未知')

    const fakeRun: RunResponse = {
      run_id: 'run-fail-1',
      task_id: fakeTask.id,
      operation: 'deploy_only',
      status: 'failed',
      reason_code: 'release_failed',
      summary: '阶段执行失败',
      config_revision: 1,
      phase: 'release',
      recovery_state: 'none',
      created_at: '2026-10-23T09:00:00Z',
      started_at: '2026-10-23T09:00:02Z',
      finished_at: '2026-10-23T09:02:00Z',
      cancel_requested_at: null,
      stop_reason: null,
      deadline_at: '2026-10-23T09:30:00Z',
      log_bytes: 10,
      last_seq: 1,
      request_hash: 'h',
      request_id: 'r',
      state_version: 1,
      task_snapshot: {} as unknown as RunResponse['task_snapshot'],
      updated_at: '2026-10-23T09:02:00Z',
      steps: [],
      effects: [],
    }

    const w = mount(RunCard, {
      props: {
        run: fakeRun,
        steps: [],
        lines: [],
      },
    })

    const cardText = w.find('[data-testid="run-card"]').text()
    expect(cardText).toContain('发布部署失败')
    expect(cardText).toContain('阶段执行失败')
  })

  it('4. TasksPage 运行确认快速双击只 POST 一次；服务拒绝后重试沿用原 request_id，202 仅展示服务快照状态', async () => {
    const posted: Array<{ plan_id: string; request_id: string; ack_old_app_idle: boolean }> = []
    let postCalls = 0
    const queuedRun: RunResponse = {
      run_id: 'run-queued-1',
      task_id: fakeTask.id,
      operation: 'deploy_only',
      status: 'queued',
      reason_code: null,
      summary: '排队中',
      config_revision: 1,
      phase: 'release',
      recovery_state: 'none',
      created_at: '2026-10-23T09:00:00Z',
      started_at: null,
      finished_at: null,
      cancel_requested_at: null,
      stop_reason: null,
      deadline_at: '2026-10-23T09:30:00Z',
      log_bytes: 0,
      last_seq: 0,
      request_hash: 'h',
      request_id: 'r',
      state_version: 1,
      task_snapshot: {} as unknown as RunResponse['task_snapshot'],
      updated_at: '2026-10-23T09:00:00Z',
      steps: [],
      effects: [],
    }

    const fakeFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const fullUrl = typeof input === 'string' ? input : (input as Request).url
      const u = new URL(fullUrl)
      if (u.pathname.endsWith('/health')) {
        return new Response(
          JSON.stringify({ status: 'ok', version: '1.0', pid: 1234, uptime_s: 10, alert: false }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (u.pathname === '/api/tasks') {
        return new Response(JSON.stringify({ items: [fakeTask], revision: 1 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname === `/api/tasks/${fakeTask.id}/preflight`) {
        return new Response(JSON.stringify(planWithCommit), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname === `/api/tasks/${fakeTask.id}/runs`) {
        postCalls++
        const body = JSON.parse((init?.body as string) || '{}')
        posted.push(body)
        if (postCalls === 1) {
          return new Response(JSON.stringify({ detail: { code: 'busy', message: 'busy' } }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return new Response(JSON.stringify({ run_id: queuedRun.run_id }), {
          status: 202,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname.endsWith('/events')) {
        return new Response(JSON.stringify({ items: [], has_more: false, next_seq: 1 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (u.pathname === `/api/runs/${queuedRun.run_id}`) {
        return new Response(JSON.stringify(queuedRun), {
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

    // 点击运行打开确认单
    await pickCommand(b, fakeTask.id)

    const startBtn = document.querySelector(
      '[data-testid="confirm-start-btn"]',
    ) as HTMLButtonElement
    expect(startBtn.disabled).toBe(false)

    // 连续双击
    startBtn.click()
    startBtn.click()
    await flushPromises()

    expect(posted).toHaveLength(1)
    expect(document.body.textContent).toContain('系统繁忙')

    // 再次点击重试
    const retryBtn = document.querySelector(
      '[data-testid="confirm-start-btn"]',
    ) as HTMLButtonElement
    retryBtn.click()
    await flushPromises()

    expect(posted).toHaveLength(2)
    expect(posted[1]?.request_id).toBe(posted[0]?.request_id)
    expect(b.wrapper.find('[data-testid="run-card"]').text()).toContain('排队中')
    expect(b.wrapper.find('[data-testid="run-card"]').text()).not.toContain('成功')

    await b.done()
  })
})
