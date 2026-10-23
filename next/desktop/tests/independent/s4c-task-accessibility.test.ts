import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import TaskDeleteSheet from '@/features/tasks/TaskDeleteSheet.vue'
import RunCard from '@/features/tasks/RunCard.vue'
import TelegramEnableSheet from '@/features/settings/TelegramEnableSheet.vue'

type S = components['schemas']
const task: S['TaskView'] = {
  id: 'task-1',
  name: '发布任务',
  enabled: true,
  local_repo_path: '/repo',
  sort_order: 1,
  tg_command: 'deploy',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  active_run_id: null,
  last_run: null,
}
const snapshot: S['TaskSnapshot'] = {
  id: task.id,
  name: task.name,
  enabled: true,
  local_repo_path: task.local_repo_path,
  sort_order: 1,
  tg_command: task.tg_command,
  tg_desc: task.tg_desc,
}
const run: S['RunResponse'] = {
  run_id: 'run-1',
  task_id: task.id,
  operation: 'sync_build_release',
  status: 'running',
  created_at: '2026-10-23T10:00:00Z',
  started_at: '2026-10-23T10:00:00Z',
  finished_at: null,
  cancel_requested_at: null,
  config_revision: 3,
  deadline_at: '2026-10-23T11:00:00Z',
  effects: [],
  last_seq: 0,
  log_bytes: 0,
  phase: 'build',
  reason_code: null,
  recovery_state: 'none',
  request_hash: 'hash',
  request_id: 'request',
  state_version: 1,
  stop_reason: null,
  summary: 'running',
  task_snapshot: snapshot,
  origin: { kind: 'telegram' },
  steps: [],
  updated_at: '2026-10-23T10:00:00Z',
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('S4-C 独立任务删除和键盘可访问性检查', () => {
  it('task_referenced 错误展示组名，并给出与引用数一致的解除引用删除操作', async () => {
    const wrapper = mount(TaskDeleteSheet, {
      props: {
        open: true,
        task,
        error: {
          code: 'task_referenced',
          status: 409,
          message: '任务已被权限组引用',
          detail: { groups: ['发布审批组', '值班组'] },
        },
      },
      attachTo: document.body,
    })
    await flushPromises()
    const dialog = document.querySelector('[data-testid="task-referenced-groups"]')
    expect(dialog?.textContent).toContain('发布审批组')
    expect(dialog?.textContent).toContain('值班组')
    const detach = document.querySelector(
      '[data-testid="confirm-detach-delete-task-btn"]',
    ) as HTMLButtonElement
    expect(detach.textContent).toContain('同时从 2 个权限组移除并删除')
    detach.click()
    await flushPromises()
    expect(wrapper.emitted('confirm-detach')).toHaveLength(1)
    wrapper.unmount()
  })

  it('运行详情只对 origin.kind=telegram 显示触发来源', async () => {
    const tg = mount(RunCard, { props: { run, steps: [], lines: [] } })
    expect(tg.find('[data-testid="run-origin-telegram"]').text()).toBe('由 Telegram 触发')
    const ui = mount(RunCard, {
      props: { run: { ...run, origin: { kind: 'ui' } }, steps: [], lines: [] },
    })
    expect(ui.find('[data-testid="run-origin-telegram"]').exists()).toBe(false)
    tg.unmount()
    ui.unmount()
  })

  it('Esc 关闭启用确认 Sheet 不提交动作，对话框有可访问名称', async () => {
    const wrapper = mount(TelegramEnableSheet, { props: { open: true }, attachTo: document.body })
    await flushPromises()
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog?.getAttribute('aria-labelledby')).toBeTruthy()
    expect(document.querySelector('[data-testid="confirm-enable-btn"]')?.textContent).toContain(
      '确认启用',
    )
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(wrapper.emitted('update:open')?.at(-1)?.[0]).toBe(false)
    expect(wrapper.emitted('confirm')).toBeUndefined()
    wrapper.unmount()
  })
})
