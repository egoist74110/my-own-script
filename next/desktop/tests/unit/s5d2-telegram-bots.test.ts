import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import type { Plugin } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backendRuntimeKey, type BackendRuntime } from '@/app/backend-runtime'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import { json } from './settings-fake'
import TelegramAiBotsCard from '@/features/settings/TelegramAiBotsCard.vue'
import TelegramAiBotEnableSheet from '@/features/settings/TelegramAiBotEnableSheet.vue'
import type { AIBotsView } from '@/features/ai/api'

function createMountOptions(runtime?: BackendRuntime) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]] as unknown as (
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

const FAKE_AI_BOTS_RESPONSE: AIBotsView = {
  revision: 5,
  warnings: [],
  items: [
    {
      ai_id: 'claude_code',
      slot: 'ai:claude_code',
      bot: {
        credential: { present: true, source: 'manual' },
        bot_id: '1001',
        username: 'claude_helper_bot',
      },
      poller: {
        state: 'disabled',
        consecutive_failures: 0,
        last_error_category: null,
        since: '2026-10-24T00:00:00Z',
      },
      control: {
        enabled: false,
        bot_id: '1001',
        enabled_at: null,
      },
      owner: { bound: true, chat_id: '6001', source: 'bound' },
    },
    {
      ai_id: 'codex',
      slot: 'ai:codex',
      bot: {
        credential: { present: false, source: 'unknown' },
        bot_id: null,
        username: null,
      },
      poller: {
        state: 'disabled',
        consecutive_failures: 0,
        last_error_category: null,
        since: '2026-10-24T00:00:00Z',
      },
      control: {
        enabled: false,
        bot_id: null,
        enabled_at: null,
      },
      owner: { bound: false, chat_id: null, source: null },
    },
    {
      ai_id: 'gemini',
      slot: 'ai:gemini',
      bot: {
        credential: { present: true, source: 'imported' },
        bot_id: '1003',
        username: 'gemini_bot',
      },
      poller: {
        state: 'conflict',
        consecutive_failures: 1,
        last_error_category: 'conflict_409',
        since: '2026-10-24T00:00:00Z',
      },
      control: {
        enabled: true,
        bot_id: '1003',
        enabled_at: '2026-10-24T00:00:00Z',
      },
      owner: { bound: true, chat_id: '6001', source: 'bound' },
    },
  ],
}

describe('S5-D2: Telegram AI 专属机器人卡片组', () => {
  it('正确渲染 3 个 AI 机器人与凭据状态', async () => {
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/ai-bots') {
        return json(FAKE_AI_BOTS_RESPONSE)
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(TelegramAiBotsCard, {
      props: { busy: false, writable: true },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    // 验证卡片渲染
    expect(w.find('[data-testid="ai-bot-card-claude_code"]').exists()).toBe(true)
    expect(w.find('[data-testid="ai-bot-card-codex"]').exists()).toBe(true)
    expect(w.find('[data-testid="ai-bot-card-gemini"]').exists()).toBe(true)

    // 凭据状态
    expect(w.find('[data-testid="ai-bot-credential-status-claude_code"]').text()).toContain(
      '已保存',
    )
    expect(w.find('[data-testid="ai-bot-credential-status-codex"]').text()).toContain('未配置')

    w.unmount()
    await b.done()
  })

  it('Token 输入校验格式，提交后清空输入框并发送 PUT 请求', async () => {
    let sentTokenBody: Record<string, unknown> | null = null
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/ai-bots') {
        return json(FAKE_AI_BOTS_RESPONSE)
      }
      if (url.pathname === '/api/telegram/ai-bots/codex/token' && req.method === 'PUT') {
        sentTokenBody = await req.json()
        return json({ revision: 6 })
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(TelegramAiBotsCard, {
      props: { busy: false, writable: true },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    const input = w.find('[data-testid="ai-bot-token-input-codex"]')

    // 1. 输入非法 Token 格式
    await input.setValue('invalid-token')
    await w.find('[data-testid="save-ai-bot-token-btn-codex"]').trigger('click')
    await flushPromises()

    expect(w.find('[data-testid="ai-bot-token-error"]').text()).toContain('需为 <数字id>:<字符串>')

    // 2. 输入合法 Token 格式并提交
    await input.setValue('123456789:ABCdefGhIjkLmNoPqRsTuVwXyZ123456')
    await w.find('[data-testid="save-ai-bot-token-btn-codex"]').trigger('click')
    await flushPromises()

    expect(sentTokenBody).toBeTruthy()
    expect(sentTokenBody!.token).toBe('123456789:ABCdefGhIjkLmNoPqRsTuVwXyZ123456')
    expect(sentTokenBody!.revision).toBe(5)

    // 输入框已被清空，不泄漏
    expect((input.element as HTMLInputElement).value).toBe('')

    w.unmount()
    await b.done()
  })

  it('从旧应用导入 Token 与删除 Token 确认 Sheet', async () => {
    let importedAiId = ''
    let deletedAiId = ''
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/ai-bots') {
        return json(FAKE_AI_BOTS_RESPONSE)
      }
      if (url.pathname.includes('/token/import-legacy')) {
        importedAiId = 'codex'
        return json({ revision: 6 })
      }
      if (url.pathname === '/api/telegram/ai-bots/claude_code/token' && req.method === 'DELETE') {
        deletedAiId = 'claude_code'
        return json({ revision: 7 })
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(TelegramAiBotsCard, {
      props: { busy: false, writable: true },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    // 导入旧应用 Token
    await w.find('[data-testid="import-legacy-ai-bot-token-btn-codex"]').trigger('click')
    await flushPromises()
    expect(importedAiId).toBe('codex')

    // 删除 Token
    await w.find('[data-testid="delete-ai-bot-token-btn-claude_code"]').trigger('click')
    await flushPromises()

    // 弹出确认 Sheet (portalled to document.body)
    const confirmDeleteBtn = document.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-delete-ai-bot-token-btn"]',
    )!
    expect(confirmDeleteBtn).not.toBeNull()
    confirmDeleteBtn.click()
    await flushPromises()

    expect(deletedAiId).toBe('claude_code')
    w.unmount()
    await b.done()
  })

  it('启用开关展示 4 步说明与必须确认 ack_old_bot_cleared', async () => {
    let enabledRequest: Record<string, unknown> | null = null
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/ai-bots') {
        return json(FAKE_AI_BOTS_RESPONSE)
      }
      if (url.pathname === '/api/telegram/ai-bots/claude_code/control/enable') {
        enabledRequest = await req.json()
        return json({ revision: 6 })
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(TelegramAiBotsCard, {
      props: { busy: false, writable: true },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    // 点击切换开关
    await w.find('[data-testid="ai-bot-switch-claude_code"]').trigger('click')
    await flushPromises()

    // 打开 4 步说明 Sheet (portalled to document.body)
    const sheet = document.querySelector('[data-testid="ai-bot-enable-sheet"]')!
    expect(sheet).not.toBeNull()
    expect(sheet.textContent).toContain('步骤 1：录入 Token')
    expect(sheet.textContent).toContain('步骤 2：清除旧版绑定')
    expect(sheet.textContent).toContain('步骤 3：确认并启用')
    expect(sheet.textContent).toContain('步骤 4：冲突与回滚')
    expect(sheet.textContent).toContain('回滚说明')

    // 未勾选前确认按钮禁用
    const confirmBtn = document.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-enable-ai-bot-btn"]',
    )!
    expect(confirmBtn).not.toBeNull()
    expect(confirmBtn.disabled).toBe(true)

    // 勾选确认
    const ackBox = document.querySelector<HTMLInputElement>(
      '[data-testid="ack-old-cleared-checkbox"]',
    )!
    expect(ackBox).not.toBeNull()
    ackBox.click()
    await flushPromises()

    expect(confirmBtn.disabled).toBe(false)
    confirmBtn.click()
    await flushPromises()

    expect(enabledRequest).toBeTruthy()
    expect(enabledRequest!.ack_old_bot_cleared).toBe(true)
    expect(enabledRequest!.revision).toBe(5)

    w.unmount()
    await b.done()
  })

  it('接收 WS telegram.status 且 slot 匹配时实时驱动胶囊状态', async () => {
    const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/ai-bots') {
        return json(FAKE_AI_BOTS_RESPONSE)
      }
      return json({})
    })

    const b = await boot({ fetchImpl: fakeFetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const w = mount(TelegramAiBotsCard, {
      props: { busy: false, writable: true },
      ...createMountOptions(b.runtime),
    })

    await flushPromises()
    await flushPromises()

    const sock = FakeSocket.last()
    expect(sock).toBeTruthy()

    // claude_code 初始状态为 disabled
    const pill = w.find('[data-testid="ai-bot-card-claude_code"] [data-poller-state]')
    expect(pill.attributes('data-poller-state')).toBe('disabled')

    // 模拟服务端推一条 telegram.status 事件（带 slot: 'ai:claude_code'）
    b.sock.emit(
      env(
        'telegram.status',
        {
          slot: 'ai:claude_code',
          state: 'polling',
          since: new Date().toISOString(),
          last_error_category: null,
        },
        { topic: 'telegram' },
      ),
    )

    await flushPromises()

    // 检查胶囊状态已被 live 驱动更新为 polling
    expect(
      w
        .find('[data-testid="ai-bot-card-claude_code"] [data-poller-state]')
        .attributes('data-poller-state'),
    ).toBe('polling')

    w.unmount()
    await b.done()
  })

  describe('S5 集成验收修复轮回归 (S5-LEAD-005 机器人标题与警告)', () => {
    it('第三张 AI 机器人卡标题为“Antigravity 机器人”', async () => {
      const fakeFetch = vi.fn().mockImplementation(async (req: Request) => {
        const url = new URL(req.url)
        if (url.pathname === '/api/telegram/ai-bots') {
          return json(FAKE_AI_BOTS_RESPONSE)
        }
        return json({})
      })

      const b = await boot({ fetchImpl: fakeFetch })
      b.sock.emit(hello())
      await flushPromises()
      await flushPromises()

      const w = mount(TelegramAiBotsCard, {
        props: { busy: false, writable: true },
        ...createMountOptions(b.runtime),
      })
      await flushPromises()
      await flushPromises()

      const geminiCard = w.find('[data-testid="ai-bot-card-gemini"]')
      expect(geminiCard.exists()).toBe(true)
      expect(geminiCard.text()).toContain('Antigravity 机器人')
      expect(geminiCard.text()).not.toContain('Gemini (agy) 机器人')

      w.unmount()
      await b.done()
    })

    it('AI 机器人启用 Sheet 包含“切换后，旧应用主机器人对该 AI 的‘MCP 分析’将不再可用（会话输出会丢失），请改用新应用”提示', async () => {
      const w = mount(TelegramAiBotEnableSheet, {
        props: {
          open: true,
          aiTitle: 'Claude Code 机器人',
          submitting: false,
        },
      })
      await flushPromises()

      const text = document.body.textContent || w.text()
      expect(text).toContain(
        '切换后，旧应用主机器人对该 AI 的‘MCP 分析’将不再可用（会话输出会丢失），请改用新应用',
      )

      w.unmount()
    })
  })
})
