// S4-C 单测：任务删除遇 409 task_referenced 解除 ACL 引用与运行来源 Telegram 标记
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import TaskDeleteSheet from '@/features/tasks/TaskDeleteSheet.vue'
import RunCard from '@/features/tasks/RunCard.vue'
import RunHistory from '@/features/tasks/RunHistory.vue'
import { ApiError, type TaskView, type RunResponse } from '@/features/tasks/api'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

const fakeTask: TaskView = {
  id: 'task-deploy-1',
  name: '生产构建发布',
  enabled: true,
  repo_name: 'my-repo',
  local_repo_path: '/repos/my-repo',
  active_run_id: null,
  last_run: null,
  sort_order: 1,
  tg_command: 'deploy',
  tg_desc: '触发生产发布',
  validation: { valid: true },
  warnings: [],
  git_flow: {
    build_branch: 'main',
  },
  targets: [],
  created_at: '2026-10-23T10:00:00Z',
  updated_at: '2026-10-23T10:00:00Z',
  revision: 1,
}

const fakeSnapshot: components['schemas']['TaskSnapshot'] = {
  id: 'task-deploy-1',
  name: '生产构建发布',
  enabled: true,
  repo_name: 'my-repo',
  local_repo_path: '/repos/my-repo',
  sort_order: 1,
  tg_command: 'deploy',
  tg_desc: '触发生产发布',
  targets: [],
}

const fakeRunTelegram: RunResponse = {
  run_id: 'run-tg-100',
  task_id: 'task-deploy-1',
  operation: 'sync_build_release',
  status: 'running',
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
  recovery_state: 'none',
  request_hash: 'h',
  request_id: 'req-1',
  state_version: 1,
  stop_reason: null,
  summary: 'Running build',
  task_snapshot: fakeSnapshot,
  origin: {
    kind: 'telegram',
  },
  steps: [],
  updated_at: '2026-10-23T10:00:01Z',
}

const fakeRunUi: RunResponse = {
  ...fakeRunTelegram,
  run_id: 'run-ui-200',
  origin: {
    kind: 'ui',
  },
}

describe('S4-C 任务删除与运行来源 Telegram 标记单测', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    document.body.innerHTML = ''
    resetSeq()
    FakeSocket.reset()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  describe('TaskDeleteSheet 组件单元测试', () => {
    it('普通状态：展示删除确认文案与普通删除按钮', async () => {
      const wrapper = mount(TaskDeleteSheet, {
        props: {
          open: true,
          task: fakeTask,
        },
        attachTo: document.body,
      })
      await flushPromises()

      const confirmBtn = document.querySelector(
        'button[data-testid="confirm-delete-task-btn"]',
      ) as HTMLButtonElement
      expect(confirmBtn).not.toBeNull()
      expect(confirmBtn.textContent).toContain('确认删除')

      // 不展示解除 ACL 引用的按钮和警告框
      expect(document.querySelector('[data-testid="task-referenced-groups"]')).toBeNull()
      expect(
        document.querySelector('button[data-testid="confirm-detach-delete-task-btn"]'),
      ).toBeNull()

      confirmBtn.click()
      await flushPromises()

      expect(wrapper.emitted('confirm')).toBeTruthy()
      wrapper.unmount()
    })

    it('409 task_referenced 错误：展示被引用权限组列表与同时移除并删除按钮', async () => {
      const refError = new ApiError(409, 'task_referenced', '该任务已被权限组引用，无法直接删除')
      ;(refError as unknown as { detail: { groups: string[] } }).detail = {
        groups: ['运维管理员组', '夜间发布组'],
      }

      const wrapper = mount(TaskDeleteSheet, {
        props: {
          open: true,
          task: fakeTask,
          error: refError,
        },
        attachTo: document.body,
      })
      await flushPromises()

      // 检查权限组列表
      const refBox = document.querySelector('[data-testid="task-referenced-groups"]')
      expect(refBox).not.toBeNull()
      expect(refBox!.textContent).toContain('已被以下 2 个权限组引用')
      expect(refBox!.textContent).toContain('运维管理员组')
      expect(refBox!.textContent).toContain('夜间发布组')

      // 检查同时移除并删除按钮
      const detachBtn = document.querySelector(
        'button[data-testid="confirm-detach-delete-task-btn"]',
      ) as HTMLButtonElement
      expect(detachBtn).not.toBeNull()
      expect(detachBtn.textContent).toContain('同时从 2 个权限组移除并删除')

      // 点击同时移除并删除按钮，触发 confirm-detach 事件
      detachBtn.click()
      await flushPromises()

      expect(wrapper.emitted('confirm-detach')).toBeTruthy()
      wrapper.unmount()
    })
  })

  describe('TasksPage 任务删除两种路径集成测试', () => {
    it('普通删除不带 detach_acl；遇到 409 task_referenced 后点击解除引用按钮带 detach_acl: true', async () => {
      let failWithReferenced = true
      const calls: { method: string; path: string; query: Record<string, string> }[] = []

      const fetchImpl = vi.fn(async (input: Request) => {
        const url = new URL(input.url)
        calls.push({
          method: input.method,
          path: url.pathname,
          query: Object.fromEntries(url.searchParams),
        })

        if (url.pathname === '/health') {
          return new Response(
            JSON.stringify({
              status: 'ok',
              version: '0.1.0',
              pid: 1234,
              uptime_s: 1,
              alert: false,
            }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          )
        }
        if (url.pathname === '/api/settings') {
          return new Response(
            JSON.stringify({
              app_version: '0.1.0',
              data_dir: '/tmp',
              legacy_config_dir: '/tmp',
              revision: 5,
              schema_version: 2,
              store_state: 'ok',
              import: { state: 'completed' },
            }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          )
        }
        if (url.pathname === '/api/tasks' && input.method === 'GET') {
          return new Response(
            JSON.stringify({
              items: [fakeTask],
              revision: 5,
            }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          )
        }
        if (url.pathname === '/api/runs' && input.method === 'GET') {
          return new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          })
        }

        // 任务删除
        if (url.pathname === '/api/release-configs/task-deploy-1' && input.method === 'DELETE') {
          const detachAcl = url.searchParams.get('detach_acl') === 'true'
          if (failWithReferenced && !detachAcl) {
            return new Response(
              JSON.stringify({
                detail: {
                  code: 'task_referenced',
                  message: '该任务已被权限组引用，无法直接删除',
                  groups: ['运维管理员组'],
                },
              }),
              { status: 409, headers: { 'content-type': 'application/json' } },
            )
          }
          return new Response(JSON.stringify({ revision: 6 }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          })
        }

        return new Response(JSON.stringify({ revision: 5 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      })

      const b = await boot({ path: '/tasks', fetchImpl: fetchImpl as unknown as typeof fetch })
      b.sock.emit(hello())
      await flushPromises()
      await flushPromises()

      // 列表选中任务并点击删除
      const delTaskBtn = b.wrapper.find('button[data-testid="delete-task-btn"]')
      expect(delTaskBtn.exists()).toBe(true)
      await delTaskBtn.trigger('click')
      await flushPromises()

      // 首次点击普通确认删除
      const confirmBtn = document.querySelector(
        'button[data-testid="confirm-delete-task-btn"]',
      ) as HTMLButtonElement
      expect(confirmBtn).not.toBeNull()
      confirmBtn.click()
      await flushPromises()

      // 验证第 1 次调用为普通删除，不带 detach_acl
      const firstDelete = calls.find(
        (c) => c.method === 'DELETE' && c.path === '/api/release-configs/task-deploy-1',
      )
      expect(firstDelete).toBeTruthy()
      expect(firstDelete?.query.detach_acl).toBeUndefined()

      // 遇到 409 task_referenced，Sheet 出现引用组提示与同时移除并删除按钮
      const refBox = document.querySelector('[data-testid="task-referenced-groups"]')
      expect(refBox).not.toBeNull()
      expect(refBox!.textContent).toContain('已被以下 1 个权限组引用')
      expect(refBox!.textContent).toContain('运维管理员组')

      const detachBtn = document.querySelector(
        'button[data-testid="confirm-detach-delete-task-btn"]',
      ) as HTMLButtonElement
      expect(detachBtn).not.toBeNull()
      expect(detachBtn.textContent).toContain('同时从 1 个权限组移除并删除')

      // 点击同时移除并删除按钮
      failWithReferenced = false
      detachBtn.click()
      await flushPromises()

      // 验证第 2 次调用携带了 detach_acl=true
      const secondDelete = calls
        .filter((c) => c.method === 'DELETE' && c.path === '/api/release-configs/task-deploy-1')
        .pop()
      expect(secondDelete).toBeTruthy()
      expect(secondDelete?.query.detach_acl).toBe('true')

      await b.done()
    })
  })

  describe('运行视图由 Telegram 触发标记单元测试', () => {
    it('RunCard: 当 origin.kind === "telegram" 时显示「由 Telegram 触发」Tag', () => {
      const wrapper = mount(RunCard, {
        props: {
          run: fakeRunTelegram,
          steps: [],
          lines: [],
        },
      })

      const tgTag = wrapper.find('[data-testid="run-origin-telegram"]')
      expect(tgTag.exists()).toBe(true)
      expect(tgTag.text()).toContain('由 Telegram 触发')
      wrapper.unmount()
    })

    it('RunCard: 当 origin.kind === "ui" 时不显示「由 Telegram 触发」Tag', () => {
      const wrapper = mount(RunCard, {
        props: {
          run: fakeRunUi,
          steps: [],
          lines: [],
        },
      })

      const tgTag = wrapper.find('[data-testid="run-origin-telegram"]')
      expect(tgTag.exists()).toBe(false)
      wrapper.unmount()
    })

    it('RunHistory: 当 origin.kind === "telegram" 时在运行条目显示「由 Telegram 触发」', () => {
      const wrapper = mount(RunHistory, {
        props: {
          runs: [fakeRunTelegram, fakeRunUi],
          selectedId: null,
        },
      })

      const text = wrapper.text()
      expect(text).toContain('由 Telegram 触发')
      wrapper.unmount()
    })
  })
})
