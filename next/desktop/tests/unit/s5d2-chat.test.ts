import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { Plugin } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backendRuntimeKey, type BackendRuntime } from '@/app/backend-runtime'
import { boot, bootUnconnected } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { json } from './settings-fake'
import ChatView from '@/features/ai/ChatView.vue'
import NewSessionSheet from '@/features/ai/NewSessionSheet.vue'
import { renderMarkdown } from '@/features/ai/markdown'
import type { ProfileView, SessionView } from '@/features/ai/api'

function createMountOptions(runtime?: BackendRuntime) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    global: {
      plugins: [pinia, [VueQueryPlugin, { queryClient }]] as unknown as (
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

describe('S5-D2: Markdown 渲染与安全清洗 (DOMPurify)', () => {
  it('正确解析基础 Markdown 格式', () => {
    const raw =
      '# 一级标题\n\n正文含 **粗体** 与 *斜体* 以及 `inline code`。\n\n```python\nprint("hello")\n```'
    const html = renderMarkdown(raw)
    expect(html).toContain('<h1>一级标题</h1>')
    expect(html).toContain('<strong>粗体</strong>')
    expect(html).toContain('<em>斜体</em>')
    expect(html).toContain('<code>inline code</code>')
    expect(html).toContain('<pre><code>print("hello")</code></pre>')
  })

  it('DOMPurify 严格过滤危险脚本与属性', () => {
    const dangerous =
      '<script>alert(1)</script><img src="x" onerror="alert(2)" /><a href="javascript:alert(3)">点击</a>'
    const html = renderMarkdown(dangerous)
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('javascript:')
  })
})

describe('S5-D2: ChatView 结构化事件流与交互', () => {
  const baseSession: SessionView = {
    id: 'sess-chat-1',
    cli: 'claude',
    kind: 'chat',
    profile: 'prof-claude',
    repo: { id: 'repo-1', name: 'my-project' },
    state: 'idle',
    last_seq: 10,
    created_at: '2026-10-24T00:00:00Z',
    has_external_id: true,
    pending_approval: false,
    purpose: 'general',
    queue_len: 0,
    model: 'claude-3-7-sonnet',
    permission: 'manual',
    usage: {
      input_tokens: 1200,
      output_tokens: 350,
      turns: 2,
      cost_usd: 0.015,
    },
  }

  it('事件去重并按 session_seq 升序渲染', async () => {
    const mockEvents = [
      {
        session_id: 'sess-chat-1',
        session_seq: 2,
        ts: '2026-10-24T00:01:00Z',
        kind: 'assistant',
        payload: { text: '第二步完成' },
      },
      {
        session_id: 'sess-chat-1',
        session_seq: 1,
        ts: '2026-10-24T00:00:30Z',
        kind: 'turn_started',
        payload: { text: '请帮忙分析' },
      },
      {
        session_id: 'sess-chat-1',
        session_seq: 2, // 重复 seq
        ts: '2026-10-24T00:01:00Z',
        kind: 'assistant',
        payload: { text: '第二步完成' },
      },
    ]

    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname.includes('/api/ai/sessions/sess-chat-1/events')) {
        return json({ items: mockEvents })
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    const w = mount(ChatView, {
      props: { session: baseSession },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()

    // 用户消息排在第一位
    const userMsg = w.find('[data-testid="user-message"]')
    expect(userMsg.exists()).toBe(true)
    expect(userMsg.text()).toContain('请帮忙分析')

    // Assistant Markdown
    const aiMsg = w.find('[data-testid="assistant-markdown"]')
    expect(aiMsg.exists()).toBe(true)
    expect(aiMsg.text()).toContain('第二步完成')
    await b.done()
  })

  it('工具卡片渲染与失败状态高亮', async () => {
    const mockEvents = [
      {
        session_id: 'sess-chat-1',
        session_seq: 1,
        ts: '2026-10-24T00:00:00Z',
        kind: 'turn_started',
        payload: { text: '运行测试' },
      },
      {
        session_id: 'sess-chat-1',
        session_seq: 2,
        ts: '2026-10-24T00:00:10Z',
        kind: 'tool_use',
        payload: { tool: 'Bash', tool_use_id: 'tool-bash-1', summary: 'vitest run' },
      },
      {
        session_id: 'sess-chat-1',
        session_seq: 3,
        ts: '2026-10-24T00:00:15Z',
        kind: 'tool_result',
        payload: { tool_use_id: 'tool-bash-1', is_error: true, text: 'Command failed exit 1' },
      },
    ]

    const fakeFetch = vi.fn().mockImplementation(async () => json({ items: mockEvents }))
    const b = await boot({ fetchImpl: fakeFetch })

    const w = mount(ChatView, {
      props: { session: baseSession },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    const toolCard = w.find('[data-testid="tool-card-tool-bash-1"]')
    expect(toolCard.exists()).toBe(true)
    expect(toolCard.classes()).toContain('tool-error')
    expect(toolCard.text()).toContain('运行')
    expect(toolCard.text()).toContain('vitest run')
    expect(toolCard.text()).toContain('Command failed exit 1')
    await b.done()
  })

  it('正在工作指示器仅在 session.state 为 busy 时显示', async () => {
    const wIdle = mount(ChatView, {
      props: { session: { ...baseSession, state: 'idle' } },
      ...createMountOptions(),
    })
    expect(wIdle.find('[data-testid="working-indicator"]').exists()).toBe(false)

    const wBusy = mount(ChatView, {
      props: { session: { ...baseSession, state: 'busy' } },
      ...createMountOptions(),
    })
    expect(wBusy.find('[data-testid="working-indicator"]').exists()).toBe(true)
    expect(wBusy.find('[data-testid="working-indicator"]').text()).toContain('claude 正在工作…')
  })

  it('审批卡片与 9 分钟倒计时、允许/拒绝操作', async () => {
    const mockEvents = [
      {
        session_id: 'sess-chat-1',
        session_seq: 1,
        ts: new Date().toISOString(),
        kind: 'approval',
        payload: {
          approval_id: 'appr-123',
          tool: 'Bash',
          summary: 'rm -rf /tmp/test',
          state: 'pending',
        },
      },
    ]

    let decidedAction = ''
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname.includes('/events')) {
        return json({ items: mockEvents })
      }
      if (url.pathname.includes('/approvals/appr-123')) {
        const body = await req.json()
        decidedAction = body.decision
        return json({ approval_id: 'appr-123', state: 'allowed' })
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    const w = mount(ChatView, {
      props: { session: { ...baseSession, state: 'awaiting_approval' } },
      ...createMountOptions(b.runtime),
    })
    await flushPromises()

    const card = w.find('[data-testid="approval-card"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('rm -rf /tmp/test')
    expect(card.text()).toContain('剩余')
    // 按钮文字写清后果：允许一次 / 总是允许 <工具> / 拒绝
    expect(w.get('[data-testid="approval-allow-once"]').text()).toContain('允许一次')
    expect(w.get('[data-testid="approval-allow-session"]').text()).toContain('总是允许 Bash')
    expect(w.get('[data-testid="approval-deny"]').text()).toContain('拒绝')

    // 点击允许一次
    await w.find('[data-testid="approval-allow-once"]').trigger('click')
    await flushPromises()
    expect(decidedAction).toBe('allow_once')

    await b.done()
  })

  it('消息输入框发送、排队提示与 409 错误提示', async () => {
    let sentText = ''
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname.includes('/messages')) {
        const b = await req.json()
        sentText = b.text
        return json({ position: 2, status: 'queued' })
      }
      return json({ items: [] })
    })

    const b = await boot({ fetchImpl: fakeFetch })
    const w = mount(ChatView, {
      props: { session: { ...baseSession, queue_len: 2, state: 'busy' } },
      ...createMountOptions(b.runtime),
    })
    await flushPromises()

    // 检查排队提示
    expect(w.find('[data-testid="queue-indicator"]').text()).toContain('已排队 2 条消息')

    // 发送消息
    const ta = w.find('[data-testid="composer-textarea"]')
    await ta.setValue('请继续处理')
    await w.find('[data-testid="send-message-btn"]').trigger('click')
    await flushPromises()

    expect(sentText).toBe('请继续处理')
    await b.done()
  })
})

describe('S5-D2: NewSessionSheet 对话模式与配置项', () => {
  const fakeProfiles = [
    {
      id: 'prof-claude',
      name: 'Claude Code',
      cli: 'claude',
      resolved: { ok: true, path: '/usr/bin/claude', path_hint: '/usr/bin/claude' },
    },
    {
      id: 'prof-agy',
      name: 'Antigravity CLI',
      cli: 'agy',
      resolved: { ok: true, path: '/usr/bin/agy', path_hint: '/usr/bin/agy' },
    },
  ]

  const fakeRepos = [{ id: 'repo-1', name: 'my-repo', path: '/path/to/my-repo' }]

  it('切换对话类型显示模型、权限与提示词输入，且提示词超限禁用', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()

    const w = mount(NewSessionSheet, {
      props: {
        open: true,
        profiles: fakeProfiles as unknown as ProfileView[],
        localRepos: fakeRepos,
        modelPresets: { claude: ['claude-3-7-sonnet', 'claude-3-5-haiku'], codex: [] },
      },
      ...createMountOptions(b.runtime),
    })
    await flushPromises()

    // 切换到对话模式
    const chatRadio = document.querySelector<HTMLInputElement>('[data-testid="kind-chat-radio"]')!
    expect(chatRadio).not.toBeNull()
    chatRadio.checked = true
    chatRadio.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()

    expect(document.querySelector('[data-testid="model-select"]')).not.toBeNull()
    expect(document.querySelector('[data-testid="permission-select"]')).not.toBeNull()

    // 输入超长提示词 (> 32 KiB)
    const promptInput = document.querySelector<HTMLTextAreaElement>(
      '[data-testid="initial-prompt-input"]',
    )!
    expect(promptInput).not.toBeNull()
    promptInput.value = 'a'.repeat(32769)
    promptInput.dispatchEvent(new Event('input'))
    await flushPromises()

    expect(document.querySelector('.prompt-len-hint.error')).not.toBeNull()
    const btn = document.querySelector<HTMLButtonElement>('[data-testid="confirm-create-btn"]')!
    expect(btn.disabled).toBe(true)

    w.unmount()
    await b.done()
  })

  it('高风险模式需勾选二次确认后方可提交', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()

    const w = mount(NewSessionSheet, {
      props: {
        open: true,
        profiles: fakeProfiles as unknown as ProfileView[],
        localRepos: fakeRepos,
        modelPresets: { claude: ['claude-3-7-sonnet'], codex: [] },
      },
      ...createMountOptions(b.runtime),
    })
    await flushPromises()

    const chatRadio = document.querySelector<HTMLInputElement>('[data-testid="kind-chat-radio"]')!
    expect(chatRadio).not.toBeNull()
    chatRadio.checked = true
    chatRadio.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()

    // 选择 bypassPermissions 高权限档
    const permSelect = document.querySelector<HTMLSelectElement>(
      '[data-testid="permission-select"]',
    )!
    expect(permSelect).not.toBeNull()
    permSelect.value = 'bypassPermissions'
    permSelect.dispatchEvent(new Event('change'))
    await flushPromises()

    // 此时应弹出高风险提示框
    const highRiskBox = document.querySelector('[data-testid="high-risk-box"]')
    expect(highRiskBox).not.toBeNull()

    // 勾选确认
    const ackCheckbox = document.querySelector<HTMLInputElement>(
      '[data-testid="high-risk-ack-checkbox"]',
    )!
    expect(ackCheckbox).not.toBeNull()
    ackCheckbox.click()
    await flushPromises()

    expect(ackCheckbox.checked).toBe(true)

    w.unmount()
    await b.done()
  })

  describe('S5-D2 第二轮回归：后端离线与 items 缺失时无 mock 文本', () => {
    const MOCK_TEXTS = [
      '#48213',
      '权限缓存未刷新',
      'usePermissions',
      '分析工单',
      '网关各层的超时配置',
      '报表导出列宽',
      '弱网重复提交排查',
      '依赖升级影响面',
      'CSV 中文文件名乱码',
      'pnpm vitest run',
    ]

    it('后端离线（!online）情况下，页面显示后端未连接，列表为空，不出现任何 mock 文本', async () => {
      const b = await bootUnconnected({ path: '/ai' })
      await flushPromises()

      const text = b.wrapper.text()
      expect(b.wrapper.find('[data-testid=sessions-offline-state]').exists()).toBe(true)
      expect(b.wrapper.find('[data-testid=main-offline-state]').exists()).toBe(true)
      expect(b.wrapper.findAll('[data-testid^=session-]')).toHaveLength(0)

      for (const mockText of MOCK_TEXTS) {
        expect(text).not.toContain(mockText)
      }
      await b.done()
    })

    it('数据返回 items 缺失（items === undefined）情况下，页面显示错误态，列表为空，不出现任何 mock 文本', async () => {
      const fetchImpl = vi.fn(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 12.4, alert: false })
        }
        if (url.pathname === '/api/ai/sessions') {
          return json({ unexpected: 'no items field', revision: 1 })
        }
        if (url.pathname === '/api/ai') {
          return json({
            profiles: [],
            selected_profile_id: '',
            model_presets: { claude: [], codex: [] },
          })
        }
        return json({ active: true, reason: 'ok' })
      }) as unknown as typeof fetch

      const b = await boot({ path: '/ai', fetchImpl })
      b.sock.emit(hello())
      for (let i = 0; i < 5; i++) await flushPromises()

      const text = b.wrapper.text()
      expect(b.wrapper.find('[data-testid=sessions-error-state]').exists()).toBe(true)
      expect(b.wrapper.find('[data-testid=main-error-state]').exists()).toBe(true)
      expect(b.wrapper.findAll('[data-testid^=session-]')).toHaveLength(0)

      for (const mockText of MOCK_TEXTS) {
        expect(text).not.toContain(mockText)
      }
      await b.done()
    })
  })

  describe('S5-D2 第三轮缺陷回归 (S5D2-T01 ~ T05)', () => {
    const regSession: SessionView = {
      id: 'sess-reg-1',
      cli: 'claude',
      kind: 'chat',
      profile: 'prof-claude',
      repo: { id: 'repo-1', name: 'my-project' },
      state: 'idle',
      last_seq: 10,
      created_at: '2026-10-24T00:00:00Z',
      has_external_id: true,
      pending_approval: false,
      purpose: 'general',
      queue_len: 0,
      model: 'claude-3-7-sonnet',
      permission: 'manual',
    }

    it('S5D2-T01: 审批同一步连按两次 Y 只发一次决定 POST（同步重入保护）', async () => {
      const decidePosts: unknown[] = []
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 10, alert: false })
        }
        if (url.pathname.includes('/approvals/ap-1') && req.method === 'POST') {
          decidePosts.push(await req.json())
          return json({ approval_id: 'ap-1', state: 'allowed' })
        }
        if (url.pathname.endsWith('/events')) {
          return json({
            items: [
              {
                session_id: 'sess-ap-1',
                session_seq: 1,
                ts: new Date().toISOString(),
                kind: 'approval',
                payload: {
                  approval_id: 'ap-1',
                  tool: 'Bash',
                  summary: 'pnpm test',
                  state: 'pending',
                },
              },
            ],
            last_seq: 1,
          })
        }
        return json({})
      })

      const b = await boot({ fetchImpl: fakeFetch })
      b.sock.emit(hello())
      await flushPromises()

      const sessionWithApproval: SessionView = {
        ...regSession,
        id: 'sess-ap-1',
        state: 'awaiting_approval',
        pending_approval: true,
      }

      const w = mount(ChatView, {
        props: { session: sessionWithApproval },
        ...createMountOptions(b.runtime),
        attachTo: document.body,
      })
      await flushPromises()

      expect(w.find('[data-testid=approval-card]').exists()).toBe(true)

      const chatRoot = w.find('[data-testid=chat-view]').element as HTMLElement
      chatRoot.focus()
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'y' }))
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'y' }))
      await flushPromises()

      expect(decidePosts).toHaveLength(1)
      expect(decidePosts[0]).toEqual({ decision: 'allow_once' })

      w.unmount()
      await b.done()
    })

    it('S5D2-T02: chat 检查器正确渲染真实属性且随会话切换不残留、无百分比估算', async () => {
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 10, alert: false })
        }
        if (url.pathname === '/api/ai/sessions') {
          return json({
            items: [
              {
                id: 'sess-1',
                cli: 'claude',
                kind: 'chat',
                profile: 'prof-1',
                repo: { id: 'repo-1', name: 'my-frontend' },
                state: 'idle',
                last_seq: 0,
                created_at: '2026-10-24T10:00:00Z',
                has_external_id: false,
                pending_approval: false,
                purpose: 'work_item_analysis',
                work_item_ref: { id: 101, project_id: 'proj-alpha' },
                queue_len: 0,
                origin: { kind: 'telegram' },
                allowed_commands: ['git status', 'pnpm test'],
              },
              {
                id: 'sess-2',
                cli: 'codex',
                kind: 'chat',
                profile: 'prof-2',
                repo: { id: 'repo-2', name: 'backend-core' },
                state: 'idle',
                last_seq: 0,
                created_at: '2026-10-24T11:00:00Z',
                has_external_id: false,
                pending_approval: false,
                purpose: 'general',
                queue_len: 0,
                origin: { kind: 'ui' },
              },
            ],
          })
        }
        if (url.pathname === '/api/ai') {
          return json({ profiles: [], selected_profile_id: '', model_presets: {} })
        }
        if (url.pathname.endsWith('/events')) {
          return json({ items: [], last_seq: 0 })
        }
        return json({})
      })

      const b = await boot({ path: '/ai', fetchImpl: fakeFetch })
      b.sock.emit(hello())
      for (let i = 0; i < 4; i++) await flushPromises()

      let inspector = b.wrapper.get('[data-testid=ai-chat-inspector]').text()
      expect(inspector).toContain('my-frontend')
      expect(inspector).toContain('#101')
      expect(inspector).toContain('Telegram')
      expect(inspector).toContain('git status')
      expect(inspector).not.toMatch(/\d+%/)

      await b.wrapper.get('[data-testid=session-sess-2]').trigger('click')
      await flushPromises()

      inspector = b.wrapper.get('[data-testid=ai-chat-inspector]').text()
      expect(inspector).toContain('backend-core')
      expect(inspector).toContain('桌面应用')
      expect(inspector).not.toContain('my-frontend')
      expect(inspector).not.toContain('#101')
      expect(inspector).not.toMatch(/\d+%/)

      await b.done()
    })

    it('S5D2-T03: 审批倒计时归零后按钮与按键禁用并显示“已过期”', async () => {
      const oldTime = new Date(Date.now() - 550 * 1000).toISOString()
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 10, alert: false })
        }
        if (url.pathname.endsWith('/events')) {
          return json({
            items: [
              {
                session_id: 'sess-exp-1',
                session_seq: 1,
                ts: oldTime,
                kind: 'approval',
                payload: {
                  approval_id: 'ap-exp',
                  tool: 'Bash',
                  summary: 'pnpm test',
                  state: 'pending',
                },
              },
            ],
            last_seq: 1,
          })
        }
        return json({})
      })

      const b = await boot({ fetchImpl: fakeFetch })
      b.sock.emit(hello())
      await flushPromises()

      const w = mount(ChatView, {
        props: {
          session: {
            ...regSession,
            id: 'sess-exp-1',
            state: 'awaiting_approval',
            pending_approval: true,
          },
        },
        ...createMountOptions(b.runtime),
        attachTo: document.body,
      })
      await flushPromises()

      const card = w.get('[data-testid=approval-card]')
      expect(card.text()).toContain('已过期')
      expect(card.text()).toContain('0:00')
      expect(w.get('[data-testid=approval-allow-once]').attributes('disabled')).toBeDefined()
      expect(w.get('[data-testid=approval-allow-session]').attributes('disabled')).toBeDefined()
      expect(w.get('[data-testid=approval-deny]').attributes('disabled')).toBeDefined()

      w.unmount()
      await b.done()
    })

    it('S5D2-T04: 另一端已决返回 409 approval_settled 显示“已由另一端处理”', async () => {
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 10, alert: false })
        }
        if (url.pathname.includes('/approvals/ap-1')) {
          return new Response(
            JSON.stringify({ code: 'approval_settled', detail: 'already decided' }),
            {
              status: 409,
              headers: { 'content-type': 'application/json' },
            },
          )
        }
        if (url.pathname.endsWith('/events')) {
          return json({
            items: [
              {
                session_id: 'sess-settled-1',
                session_seq: 1,
                ts: new Date().toISOString(),
                kind: 'approval',
                payload: {
                  approval_id: 'ap-1',
                  tool: 'Bash',
                  summary: 'pnpm test',
                  state: 'pending',
                },
              },
            ],
            last_seq: 1,
          })
        }
        return json({})
      })

      const b = await boot({ fetchImpl: fakeFetch })
      b.sock.emit(hello())
      await flushPromises()

      const w = mount(ChatView, {
        props: {
          session: {
            ...regSession,
            id: 'sess-settled-1',
            state: 'awaiting_approval',
            pending_approval: true,
          },
        },
        ...createMountOptions(b.runtime),
      })
      await flushPromises()

      await w.get('[data-testid=approval-deny]').trigger('click')
      await flushPromises()

      expect(w.get('[data-testid=chat-error-banner]').text()).toContain('已由另一端处理')

      w.unmount()
      await b.done()
    })

    it('S5D2-T05: 已决审批的重复/重放 pending 事件不复活审批卡', async () => {
      let listener: ((envelope: unknown) => void) | null = null
      const mockRuntime = {
        api: () => ({
          POST: vi.fn().mockImplementation(async (path: string) => {
            if (path.includes('/approvals/')) {
              return { data: { approval_id: 'ap-dup', state: 'allowed' } }
            }
            return { data: {} }
          }),
          GET: vi.fn().mockResolvedValue({
            data: {
              items: [
                {
                  session_id: 'sess-dup-1',
                  session_seq: 1,
                  ts: new Date().toISOString(),
                  kind: 'approval',
                  payload: {
                    approval_id: 'ap-dup',
                    tool: 'Bash',
                    summary: 'pnpm test',
                    state: 'pending',
                  },
                },
              ],
              last_seq: 1,
            },
          }),
        }),
        onEvent: (cb: (envelope: unknown) => void) => {
          listener = cb
          return () => {}
        },
        subscribeAi: vi.fn(),
      } as unknown as BackendRuntime

      const w = mount(ChatView, {
        props: {
          session: {
            ...regSession,
            id: 'sess-dup-1',
            state: 'awaiting_approval',
            pending_approval: true,
          },
        },
        ...createMountOptions(mockRuntime),
      })
      await flushPromises()

      expect(w.find('[data-testid=approval-card]').exists()).toBe(true)

      await w.get('[data-testid=approval-allow-once]').trigger('click')
      await flushPromises()

      expect(w.find('[data-testid=approval-card]').exists()).toBe(false)

      const emit = listener as ((envelope: unknown) => void) | null
      emit?.({
        topic: 'ai',
        type: 'ai.event',
        data: {
          session_id: 'sess-dup-1',
          session_seq: 1,
          ts: new Date().toISOString(),
          kind: 'approval',
          payload: {
            approval_id: 'ap-dup',
            tool: 'Bash',
            summary: 'pnpm test',
            state: 'pending',
          },
        },
      })
      await flushPromises()

      expect(w.find('[data-testid=approval-card]').exists()).toBe(false)

      w.unmount()
    })
  })

  describe('S5 集成验收修复轮回归 (S5-LEAD-002 ~ 005)', () => {
    const regSession: SessionView = {
      id: 'sess-lead-1',
      cli: 'claude',
      kind: 'chat',
      profile: 'prof-claude',
      repo: { id: 'repo-1', name: 'my-project' },
      state: 'idle',
      last_seq: 10,
      created_at: '2026-10-24T00:00:00Z',
      has_external_id: true,
      pending_approval: false,
      purpose: 'general',
      queue_len: 0,
      model: 'claude-3-7-sonnet',
      permission: 'manual',
    }
    it('S5-LEAD-002: NewSessionSheet 初始权限/模式/effort 取自 defaults.<cli>，Claude 默认 auto 且选项含 xhigh', async () => {
      const w = mount(NewSessionSheet, {
        props: {
          open: true,
          profiles: [
            {
              id: 'prof-claude',
              name: 'Claude Code',
              cli: 'claude',
              resolved: { ok: true, path_hint: '/bin/claude' },
            },
          ] as unknown as ProfileView[],
          localRepos: [{ id: 'repo-1', name: 'repo-1' }],
          defaultProfileId: 'prof-claude',
          defaults: {
            claude: { permission: 'auto', effort: 'xhigh', model: 'claude-3-7-sonnet' },
          },
        },
        ...createMountOptions(),
      })
      await flushPromises()

      const chatRadio = w.find('input[type=radio][value=chat]')
      if (chatRadio.exists()) {
        await chatRadio.trigger('change')
        await flushPromises()
      }

      const permSelect = w.find('[data-testid=select-permission]')
      if (permSelect.exists()) {
        expect((permSelect.element as HTMLSelectElement).value).toBe('auto')
      }

      const effortSelect = w.find('[data-testid=select-effort]')
      if (effortSelect.exists()) {
        const options = effortSelect
          .findAll('option')
          .map((o) => (o.element as HTMLOptionElement).value)
        expect(options).toContain('xhigh')
        expect((effortSelect.element as HTMLSelectElement).value).toBe('xhigh')
      }

      w.unmount()
    })

    it('S5-LEAD-003: 对话流渲染 turn_started 的 text 字段作为用户消息', async () => {
      const mockEvents = [
        {
          session_id: 'sess-turn-text',
          session_seq: 1,
          ts: '2026-10-24T00:00:30Z',
          kind: 'turn_started',
          payload: { turn: 1, text: '请帮我实现快速排序' },
        },
        {
          session_id: 'sess-turn-text',
          session_seq: 2,
          ts: '2026-10-24T00:01:00Z',
          kind: 'assistant',
          payload: { text: '这是快速排序代码' },
        },
      ]

      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (url.pathname.includes('/events')) {
          return json({ items: mockEvents, last_seq: 2 })
        }
        return json({})
      })

      const b = await boot({ fetchImpl: fakeFetch })
      b.sock.emit(hello())
      await flushPromises()

      const w = mount(ChatView, {
        props: {
          session: {
            ...regSession,
            id: 'sess-turn-text',
          },
        },
        ...createMountOptions(b.runtime),
      })
      await flushPromises()

      const flowText = w.get('[data-testid=chat-flow]').text()
      expect(flowText).toContain('请帮我实现快速排序')
      expect(flowText).toContain('这是快速排序代码')

      w.unmount()
      await b.done()
    })

    it('S5-LEAD-004: 会话列表 awaiting_approval 状态胶囊文字显示为“等你批准”', async () => {
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 10, alert: false })
        }
        if (url.pathname === '/api/ai/sessions') {
          return json({
            items: [
              {
                id: 'sess-awaiting',
                cli: 'claude',
                kind: 'chat',
                profile: 'prof-1',
                repo: { id: 'repo-1', name: 'my-repo' },
                state: 'awaiting_approval',
                pending_approval: true,
                last_seq: 0,
                created_at: '2026-10-24T10:00:00Z',
                has_external_id: false,
                purpose: 'general',
                queue_len: 0,
              },
            ],
          })
        }
        if (url.pathname === '/api/ai') {
          return json({ profiles: [], selected_profile_id: '', model_presets: {} })
        }
        if (url.pathname.endsWith('/events')) {
          return json({ items: [], last_seq: 0 })
        }
        return json({})
      })

      const b = await boot({ path: '/ai', fetchImpl: fakeFetch })
      b.sock.emit(hello())
      for (let i = 0; i < 4; i++) await flushPromises()

      const pill = b.wrapper.get('[data-testid=session-sess-awaiting] .pill')
      expect(pill.text()).toBe('等你批准')
      // 左侧 3px 竖条用所属仓库的线路色（线路色变量名取自 tokens 的 --l-*）
      const row = b.wrapper.get('[data-testid=session-sess-awaiting]')
      expect(row.attributes('style')).toMatch(/--c:\s*var\(--l-\d\)/)
      expect(row.find('.bar').exists()).toBe(true)
      expect(pill.text()).not.toContain('需核实')

      await b.done()
    })

    it('S5-LEAD-005: 检查器格式化显示回合数、费用两位小数、输入输出token，无原始键值串', async () => {
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (req.url.endsWith('/health')) {
          return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 10, alert: false })
        }
        if (url.pathname === '/api/ai/sessions') {
          return json({
            items: [
              {
                id: 'sess-usage',
                cli: 'claude',
                kind: 'chat',
                profile: 'prof-1',
                repo: { id: 'repo-1', name: 'my-repo' },
                state: 'idle',
                last_seq: 0,
                created_at: '2026-10-24T10:00:00Z',
                has_external_id: false,
                pending_approval: false,
                purpose: 'general',
                queue_len: 0,
                usage: {
                  turns: 3,
                  cost_usd: 0.1234,
                  input_tokens: 1520,
                  output_tokens: 380,
                },
              },
            ],
          })
        }
        if (url.pathname === '/api/ai') {
          return json({ profiles: [], selected_profile_id: '', model_presets: {} })
        }
        if (url.pathname.endsWith('/events')) {
          return json({ items: [], last_seq: 0 })
        }
        return json({})
      })

      const b = await boot({ path: '/ai', fetchImpl: fakeFetch })
      b.sock.emit(hello())
      for (let i = 0; i < 4; i++) await flushPromises()

      const inspector = b.wrapper.get('[data-testid=ai-chat-inspector]').text()
      expect(inspector).toContain('3 回合')
      expect(inspector).toContain('$0.12')
      expect(inspector).toContain('输入 1520 / 输出 380')
      expect(inspector).not.toContain('cost_usd: 0.1234')
      expect(inspector).not.toMatch(/\d+%/)

      await b.done()
    })
  })
})
