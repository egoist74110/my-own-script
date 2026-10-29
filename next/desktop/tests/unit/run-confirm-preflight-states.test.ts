import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import RunConfirmSheet from '@/features/tasks/RunConfirmSheet.vue'
import { ApiError, type PlanResponse } from '@/features/tasks/api'

beforeEach(() => {
  document.body.innerHTML = ''
})
afterEach(() => {
  document.body.innerHTML = ''
})

const plan = {
  plan_id: 'p1',
  steps: [{ kind: 'git' }],
  targets: [],
  warnings: [],
  expires_at: '2026-10-23T10:05:00Z',
} as unknown as PlanResponse

const task = { name: 'CG_Vue_Front', local_repo_path: '/repo' }

function mountSheet(props: Record<string, unknown>) {
  return mount(RunConfirmSheet, {
    props: {
      open: true,
      task,
      commandName: 'Front发布',
      operation: 'sync_build_release',
      plan: null,
      ...props,
    },
    attachTo: document.body,
  })
}
const q = (sel: string) => document.querySelector(sel) as HTMLElement | null

describe('RunConfirmSheet 预检三态', () => {
  it('预检中：显示加载指示，不说“将按下面的计划执行”，开始运行禁用并写明原因', async () => {
    mountSheet({ loading: true })
    await flushPromises()
    expect(q('[data-testid=preflight-loading]')?.textContent).toContain('正在检查仓库和 ADO…')
    expect(q('.spinner')).not.toBeNull()
    expect(document.body.textContent).not.toContain('将按下面的计划执行')
    expect((q('[data-testid=confirm-start-btn]') as HTMLButtonElement).disabled).toBe(true)
    expect(q('[data-testid=confirm-disabled-reason]')?.textContent).toContain('正在检查')
  })

  it('预检失败：显示后端 message、跳转配置按钮；重试发出事件', async () => {
    const err = new ApiError(409, 'unsafe_repository', '仓库 origin 不受支持：git@x:y.git')
    const w = mountSheet({ error: err })
    await flushPromises()
    expect(q('[data-testid=plan-error-banner]')?.textContent).toContain(
      '仓库 origin 不受支持：git@x:y.git',
    )
    expect(document.body.textContent).toContain('无法运行')
    expect(document.body.textContent).not.toContain('将按下面的计划执行')
    expect((q('[data-testid=confirm-start-btn]') as HTMLButtonElement).disabled).toBe(true)
    expect(q('[data-testid=confirm-disabled-reason]')?.textContent).toContain('预检未通过')

    q('[data-testid=preflight-open-config]')!.click()
    expect(w.emitted('open-config')).toHaveLength(1)
    q('[data-testid=preflight-retry]')!.click()
    expect(w.emitted('retry')).toHaveLength(1)
  })

  it('预检失败（ado_request_failed）：只有重试，没有跳转配置按钮', async () => {
    mountSheet({ error: new ApiError(502, 'ado_request_failed', 'ADO 超时') })
    await flushPromises()
    expect(q('[data-testid=preflight-open-config]')).toBeNull()
    expect(q('[data-testid=preflight-retry]')).not.toBeNull()
  })

  it('成功：显示计划；无需勾选，禁用原因为空且可直接开始', async () => {
    mountSheet({ plan })
    await flushPromises()
    expect(q('[data-testid=run-confirm-sheet]')).not.toBeNull()
    expect(document.body.textContent).toContain('将按下面的计划执行')
    expect(q('[data-testid=confirm-disabled-reason]')).toBeNull()
    expect((q('[data-testid=confirm-start-btn]') as HTMLButtonElement).disabled).toBe(false)
  })

  it('缺 commit 的只发布：禁用原因写明缺 commit', async () => {
    mountSheet({
      operation: 'deploy_only',
      plan: { ...plan, targets: [{ name: 't', build_id: 1, commit: '' }] },
    })
    await flushPromises()
    expect(q('[data-testid=confirm-disabled-reason]')?.textContent).toContain('commit')
  })
})
