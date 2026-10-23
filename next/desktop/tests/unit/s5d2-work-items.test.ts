import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import type { Plugin } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backendRuntimeKey, type BackendRuntime } from '@/app/backend-runtime'
import { createTestRouter } from '@/app/router'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { json } from './settings-fake'
import WorkItemDetail from '@/features/work-items/WorkItemDetail.vue'

function createMountOptions(
  runtime?: BackendRuntime,
  router?: ReturnType<typeof createTestRouter>,
) {
  const r = router ?? createTestRouter()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    global: {
      plugins: [r, [VueQueryPlugin, { queryClient }]] as unknown as (
        Plugin | [Plugin, ...unknown[]]
      )[],
      provide: runtime ? { [backendRuntimeKey as symbol]: runtime } : {},
    },
  }
}

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

const FAKE_DETAIL = {
  id: 1234,
  rev: 3,
  type: 'Bug',
  title: '支付网关超时偶发失败',
  assigned_to: '张三',
  created_date: '2026-10-20T10:00:00Z',
  changed_date: '2026-10-21T11:00:00Z',
  parent_id: null,
  child_ids: [],
  attachments: [],
  links: [],
  html: {
    description: { html: '<p>复现步骤：高并发下网络超时</p>', omitted: false },
  },
}

const FAKE_ADO = {
  libraries: [{ id: 'lib-1', name: '默认组织' }],
  projects: [{ id: 'proj-1', name: '核心项目' }],
  local_repos: [{ id: 'repo-1', name: 'payment-svc', path: '/code/payment-svc' }],
}

const FAKE_AI = {
  profiles: [
    {
      id: 'prof-claude',
      name: 'Claude Code',
      cli: 'claude',
      resolved: { ok: true, path_hint: '/usr/bin/claude' },
    },
    {
      id: 'prof-agy',
      name: 'Antigravity CLI',
      cli: 'agy',
      resolved: { ok: true, path_hint: '/usr/bin/agy' },
    },
  ],
  revision: 1,
}

describe('S5-D2: 工单详情页「AI 分析」与「复制提示词」', () => {
  it('配置了 local_repos 与可用 profile 时启用「AI 分析」按钮', async () => {
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/work-items/1234') return json(FAKE_DETAIL)
      if (url.pathname === '/api/ado') return json(FAKE_ADO)
      if (url.pathname === '/api/ai') return json(FAKE_AI)
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(WorkItemDetail, {
      props: { id: 1234, projectId: 'proj-1' },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    const btn = w.find('[data-testid="ai-analysis-btn"]')
    expect(btn.exists()).toBe(true)
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
    w.unmount()
    await b.done()
  })

  it('无 local_repos 时「AI 分析」按钮禁用并提示', async () => {
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/work-items/1234') return json(FAKE_DETAIL)
      if (url.pathname === '/api/ado') return json({ ...FAKE_ADO, local_repos: [] })
      if (url.pathname === '/api/ai') return json(FAKE_AI)
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(WorkItemDetail, {
      props: { id: 1234, projectId: 'proj-1' },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    const btn = w.find('[data-testid="ai-analysis-btn"]')
    expect(btn.exists()).toBe(true)
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    expect(btn.attributes('title')).toContain('需配置本地仓库')
    w.unmount()
    await b.done()
  })

  it('点击「AI 分析」弹出 Sheet，启动分析并发送参数', async () => {
    let sentAnalysisBody: Record<string, unknown> | null = null
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/work-items/1234') return json(FAKE_DETAIL)
      if (url.pathname === '/api/ado') return json(FAKE_ADO)
      if (url.pathname === '/api/ai') return json(FAKE_AI)
      if (url.pathname === '/api/work-items/1234/ai-analysis') {
        sentAnalysisBody = await req.json()
        return json({
          id: 'sess-new-1',
          cli: 'claude',
          kind: 'chat',
          state: 'starting',
          purpose: 'work_item_analysis',
          repo: FAKE_ADO.local_repos[0],
          last_seq: 0,
          created_at: new Date().toISOString(),
          has_external_id: false,
          pending_approval: false,
          queue_len: 0,
        })
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(WorkItemDetail, {
      props: { id: 1234, projectId: 'proj-1' },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    // 点击打开 Sheet
    await w.find('[data-testid="ai-analysis-btn"]').trigger('click')
    await flushPromises()

    const form = document.querySelector('[data-testid="ai-analysis-form"]')
    expect(form).not.toBeNull()

    // 确认启动分析
    const confirmBtn = document.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-analysis-btn"]',
    )!
    expect(confirmBtn).not.toBeNull()
    confirmBtn.click()
    await flushPromises()

    expect(sentAnalysisBody).toBeTruthy()
    expect(sentAnalysisBody!.project_id).toBe('proj-1')
    expect(sentAnalysisBody!.repo_id).toBe('repo-1')
    expect(sentAnalysisBody!.profile_id).toBe('prof-claude')
    w.unmount()
    await b.done()
  })

  it('「复制提示词」成功写入剪贴板并提示警告信息', async () => {
    const clipboardWriteMock = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: {
        writeText: clipboardWriteMock,
      },
    })

    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/work-items/1234') return json(FAKE_DETAIL)
      if (url.pathname === '/api/ado') return json(FAKE_ADO)
      if (url.pathname === '/api/ai') return json(FAKE_AI)
      if (url.pathname === '/api/work-items/1234/ai-prompt') {
        return json({
          prompt: '请分析工单 #1234 的复现步骤与代码定位',
          warnings: ['legacy_mcp_may_not_resolve_project'],
        })
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(WorkItemDetail, {
      props: { id: 1234, projectId: 'proj-1' },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    // 点击复制提示词
    await w.find('[data-testid="copy-prompt-btn"]').trigger('click')
    await flushPromises()

    expect(clipboardWriteMock).toHaveBeenCalledWith('请分析工单 #1234 的复现步骤与代码定位')

    // 验证 Toast 提示与 Warnings 浮层
    expect(w.find('[data-testid="copy-prompt-toast"]').text()).toContain('提示词已复制到剪贴板')
    expect(w.find('[data-testid="prompt-warnings"]').text()).toContain(
      'legacy_mcp_may_not_resolve_project',
    )

    w.unmount()
    await b.done()
  })

  describe('S5-D2 第三轮缺陷回归 (S5D2-T06 ~ T07)', () => {
    it('S5D2-T06: 工单未选中时显示禁用占位，工单详情选中后检查器不再展示 S5 占位', async () => {
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 10, alert: false })
        }
        if (url.pathname === '/api/work-items') {
          return json({
            items: [{ id: 10, title: '工单十', type: 'Task', state: '开发中' }],
            truncated: false,
            omitted: 0,
          })
        }
        if (url.pathname === '/api/work-items/10') {
          return json({
            ...FAKE_DETAIL,
            id: 10,
            title: '工单十',
          })
        }
        if (url.pathname === '/api/ado') return json(FAKE_ADO)
        if (url.pathname === '/api/ai') return json(FAKE_AI)
        return json({})
      })

      const b = await boot({ path: '/work-items', fetchImpl: fakeFetch })
      b.sock.emit(hello())
      for (let i = 0; i < 3; i++) await flushPromises()

      // 未选工单时，检查器保留 S5 占位面板
      expect(b.wrapper.find('[data-testid=wi-ai]').exists()).toBe(true)

      // 选中工单 #10
      await b.wrapper.get('[data-testid=wi-row-10]').trigger('click')
      for (let i = 0; i < 3; i++) await flushPromises()

      // 选中详情后，检查器不应再保留禁用的 S5 占位（真实入口已迁移到详情）
      expect(b.wrapper.find('[data-testid=wi-ai]').exists()).toBe(false)

      await b.done()
    })

    it('S5D2-T07: 工单发起 AI 分析后跳转至 /ai 并通过 query 选中新会话', async () => {
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 10, alert: false })
        }
        if (url.pathname === '/api/work-items/1234') return json(FAKE_DETAIL)
        if (url.pathname === '/api/ado') return json(FAKE_ADO)
        if (url.pathname === '/api/ai') return json(FAKE_AI)
        if (url.pathname === '/api/work-items/1234/ai-analysis' && req.method === 'POST') {
          return json({
            id: 'sess-created-from-wi',
            cli: 'claude',
            kind: 'chat',
            state: 'starting',
            last_seq: 0,
            repo: { id: 'repo-1', name: 'payment-svc' },
          })
        }
        if (url.pathname === '/api/ai/sessions') {
          return json({
            items: [
              {
                id: 'sess-old-1',
                cli: 'claude',
                kind: 'chat',
                state: 'idle',
                last_seq: 0,
                repo: { id: 'repo-1', name: 'payment-svc' },
              },
              {
                id: 'sess-created-from-wi',
                cli: 'claude',
                kind: 'chat',
                state: 'starting',
                last_seq: 0,
                repo: { id: 'repo-1', name: 'payment-svc' },
              },
            ],
          })
        }
        return json({})
      })

      const b = await boot({ path: '/work-items', fetchImpl: fakeFetch })
      b.sock.emit(hello())
      for (let i = 0; i < 3; i++) await flushPromises()

      const w = mount(WorkItemDetail, {
        props: { id: 1234, projectId: 'proj-1' },
        ...createMountOptions(b.runtime, b.router),
      })
      await flushPromises()

      // 打开 AI 分析弹窗并提交
      await w.get('[data-testid=ai-analysis-btn]').trigger('click')
      await flushPromises()
      await (document.querySelector('[data-testid=confirm-analysis-btn]') as HTMLElement)?.click()
      await flushPromises()

      // 验证路由 push 参数包含新会话 id
      expect(b.router.currentRoute.value.path).toBe('/ai')
      expect(b.router.currentRoute.value.query.session).toBe('sess-created-from-wi')

      w.unmount()
      await b.done()
    })
  })
})
