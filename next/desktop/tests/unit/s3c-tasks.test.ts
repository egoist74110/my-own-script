import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'
import RunConfirmSheet from '@/features/tasks/RunConfirmSheet.vue'
import TaskRollbackSheet from '@/features/tasks/TaskRollbackSheet.vue'
import RunCard from '@/features/tasks/RunCard.vue'
import {
  TASK_ERROR_MESSAGES,
  errorText,
  mapStatusToPill,
  formatDuration,
  ApiError,
  toApiError,
  type PlanResponse,
  type TaskView,
} from '@/features/tasks/api'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

const fakeTask: TaskView = {
  id: 'task-1',
  name: '生产构建发布',
  enabled: true,
  repo_name: 'my-repo',
  local_repo_path: '/repos/my-repo',
  active_run_id: null,
  last_run: null,
  sort_order: 1,
  tg_command: '',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  git_flow: {
    build_branch: 'main',
  },
  targets: [
    {
      name: '目标1',
      enabled: true,
      build_name: 'Build-Main',
      build_kind: 'pipeline' as const,
      release_name: 'Release-Prod',
      release_stage_names: ['Deploy-Prod'],
    },
  ],
  created_at: '2026-10-23T10:00:00Z',
  updated_at: '2026-10-23T10:00:00Z',
}

const fakePlan: PlanResponse = {
  plan_id: 'plan-xyz-123',
  revision: 1,
  task_summary: {
    id: 'task-1',
    name: '生产构建发布',
  },
  targets: [
    {
      target_index: 0,
      name: '目标1',
      definition_id: 101,
      release_definition_id: 202,
      stage_ids: [1],
    },
  ],
  steps: [
    { kind: 'git', target_index: null },
    { kind: 'build', target_index: 0 },
    { kind: 'release', target_index: 0 },
  ],
  warnings: ['不可撤回的生产环境副作用'],
  expires_at: '2026-10-23T10:05:00Z',
}

describe('S3-C 任务执行计划与确认（Preflight -> Confirm -> Start）', () => {
  it('RunConfirmSheet 显示分支、目标与步骤；无需勾选即可确认', async () => {
    const open = ref(true)
    const submittedPayload = ref<unknown>(null)

    const w = mount(RunConfirmSheet, {
      props: {
        open: open.value,
        task: fakeTask,
        operation: 'sync_build_release',
        plan: fakePlan,
        submitting: false,
        error: null,
        onConfirm: (payload) => {
          submittedPayload.value = payload
        },
        'onUpdate:open': (v) => {
          open.value = v
        },
      },
      attachTo: document.body,
    })
    await flushPromises()

    const body = document.body.innerHTML
    expect(body).toContain('运行“生产构建发布”？')
    expect(body).toContain('不可撤回的生产环境副作用')
    expect(body).toContain('计划 5 分钟内有效')

    // 确认按钮无需勾选，直接可用
    const confirmBtn = document.querySelector(
      '[data-testid=confirm-start-btn]',
    ) as HTMLButtonElement
    expect(confirmBtn).not.toBeNull()
    expect(confirmBtn.disabled).toBe(false)

    // 点击确认
    confirmBtn.click()
    await flushPromises()

    expect(submittedPayload.value).not.toBeNull()
    const p = submittedPayload.value as { planId: string; requestId: string; ack: boolean }
    expect(p.planId).toBe('plan-xyz-123')
    expect(p.ack).toBe(true)
    expect(typeof p.requestId).toBe('string')
    expect(p.requestId.length).toBeGreaterThan(8)
    w.unmount()
  })

  it('双击确认幂等：同一确认会话内多次点击保持同一个 requestId', async () => {
    const open = ref(true)
    const requests: string[] = []

    const w = mount(RunConfirmSheet, {
      props: {
        open: open.value,
        task: fakeTask,
        operation: 'sync_build_release',
        plan: fakePlan,
        submitting: false,
        error: null,
        onConfirm: (payload) => {
          requests.push(payload.requestId)
        },
      },
      attachTo: document.body,
    })
    await flushPromises()

    const confirmBtn = document.querySelector(
      '[data-testid=confirm-start-btn]',
    ) as HTMLButtonElement
    confirmBtn.click()
    confirmBtn.click()
    await flushPromises()

    expect(requests.length).toBe(2)
    expect(requests[0]).toBe(requests[1])
    w.unmount()
  })

  it('回滚 offset 选择 Sheet 支持 1..5', async () => {
    const open = ref(true)
    const chosenOffset = ref<number | null>(null)

    const w = mount(TaskRollbackSheet, {
      props: {
        open: open.value,
        task: fakeTask,
        onSubmit: (offset: number) => {
          chosenOffset.value = offset
        },
      },
      attachTo: document.body,
    })
    await flushPromises()

    const select = document.querySelector(
      '[data-testid=rollback-offset-select]',
    ) as HTMLSelectElement
    expect(select).not.toBeNull()
    expect(select.value).toBe('1')

    select.value = '3'
    select.dispatchEvent(new Event('change'))
    await flushPromises()

    const confirmBtn = document.querySelector(
      '[data-testid=start-rollback-preflight-btn]',
    ) as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    expect(chosenOffset.value).toBe(3)
    w.unmount()
  })
})

describe('S3-C 运行停止、取消确认与副作用说明', () => {
  it('RunCard 停止运行弹出 Sheet 确认，提示“正在进行中的远端构建或发布可能会保持当前状态”', async () => {
    const cancelCalled = ref<string | null>(null)
    const runningRun = {
      run_id: 'run-active-1',
      task_id: 'task-1',
      operation: 'sync_build_release' as const,
      status: 'running' as const,
      created_at: '2026-10-23T10:00:00Z',
      started_at: '2026-10-23T10:00:01Z',
      finished_at: null,
      cancel_requested_at: null,
      config_revision: 1,
      deadline_at: '2026-10-23T10:30:00Z',
      effects: [],
      last_seq: 1,
      log_bytes: 10,
      phase: 'build',
      reason_code: null,
      recovery_state: 'none' as const,
      request_hash: 'h',
      request_id: 'req-1',
      state_version: 1,
      stop_reason: null,
      summary: 'Running build',
      task_snapshot: {
        ...fakeTask,
        revision: 1,
        targets: [
          {
            name: '目标1',
            enabled: true,
            build_name: 'Build-Main',
            build_kind: 'pipeline' as const,
            release_name: 'Release-Prod',
            release_stage_names: ['Deploy-Prod'],
          },
        ],
      },
      updated_at: '2026-10-23T10:00:01Z',
      steps: [
        {
          run_id: 'run-active-1',
          step_no: 1,
          kind: 'git',
          status: 'succeeded' as const,
          target_index: null,
          checkpoint: {},
          started_at: '2026-10-23T10:00:00Z',
          finished_at: '2026-10-23T10:00:10Z',
        },
      ],
    }

    const w = mount(RunCard, {
      props: {
        run: runningRun,
        steps: runningRun.steps,
        lines: [],
        totalLineCount: 0,
        onCancel: (runId: string) => {
          cancelCalled.value = runId
        },
      },
      attachTo: document.body,
    })
    await flushPromises()

    const stopBtn = w.find('[data-testid=cancel-run-btn]')
    expect(stopBtn.exists()).toBe(true)
    await stopBtn.trigger('click')
    await flushPromises()

    // 弹出的 Sheet 必须包含副作用说明
    const bodyHtml = document.body.innerHTML
    expect(bodyHtml).toContain('正在进行中的远端构建或发布可能会保持当前状态')

    const confirmStopBtn = document.querySelector(
      '[data-testid=confirm-cancel-btn]',
    ) as HTMLButtonElement
    expect(confirmStopBtn).not.toBeNull()
    confirmStopBtn.click()
    await flushPromises()

    expect(cancelCalled.value).toBe('run-active-1')
    w.unmount()
  })
})

describe('S3-C 错误码映射与辅助函数', () => {
  it('TASK_ERROR_MESSAGES 覆盖关键错误码中文说明', () => {
    expect(TASK_ERROR_MESSAGES.task_active).toContain('正在运行中')
    expect(TASK_ERROR_MESSAGES.task_referenced).toContain('被 Telegram 权限组引用')
    expect(TASK_ERROR_MESSAGES.resource_active).toContain('资源正在被占用')
    expect(TASK_ERROR_MESSAGES.plan_expired).toContain('已过期')
    expect(TASK_ERROR_MESSAGES.plan_changed).toContain('已失效')
    expect(TASK_ERROR_MESSAGES.run_store_unavailable).toContain('只读模式')
    expect(TASK_ERROR_MESSAGES.busy).toContain('系统繁忙')
  })

  it('errorText 能正确提取 ApiError 与原生 Error', () => {
    const err = new ApiError(409, 'task_active', 'active')
    expect(errorText(err)).toContain('正在运行中')
    expect(errorText(new Error('网络超时'))).toBe('网络超时')
    expect(errorText('未知错误')).toBe('发生未知错误')
  })

  it('toApiError 能从响应体重构 ApiError 并赋予中文提示', () => {
    const err = toApiError(409, { detail: { code: 'task_active' } })
    expect(err.code).toBe('task_active')
    expect(err.message).toContain('正在运行中')
  })

  it('mapStatusToPill 覆盖八态映射', () => {
    expect(mapStatusToPill(false, null)).toBe('disabled')
    expect(mapStatusToPill(true, 'queued')).toBe('queued')
    expect(mapStatusToPill(true, 'running')).toBe('running')
    expect(mapStatusToPill(true, 'cancelling')).toBe('stopping')
    expect(mapStatusToPill(true, 'succeeded')).toBe('success')
    expect(mapStatusToPill(true, 'failed')).toBe('failed')
    expect(mapStatusToPill(true, 'cancelled')).toBe('cancelled')
    expect(mapStatusToPill(true, 'unknown')).toBe('verify')
  })

  it('formatDuration 格式化秒数与时间差', () => {
    expect(formatDuration('2026-10-23T10:00:00Z', '2026-10-23T10:01:30Z')).toBe('1:30')
    expect(formatDuration('2026-10-23T10:00:00Z', '2026-10-23T10:00:45Z')).toBe('0:45')
    expect(formatDuration(null, null)).toBe('—')
  })
})
