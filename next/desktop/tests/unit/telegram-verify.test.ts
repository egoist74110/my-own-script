// Telegram 设置页：Token 校验结果、机器人身份、启用引导与启用失败可见性（主 Bot + AI 专属 Bot）
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import type { Plugin } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import { backendRuntimeKey } from '@/app/backend-runtime'
import TelegramAiBotsCard from '@/features/settings/TelegramAiBotsCard.vue'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { json } from './settings-fake'

type S = components['schemas']

const OK_VERIFY: S['TokenVerification'] = {
  ok: true,
  code: null,
  message: 'Token 有效',
  has_webhook: false,
  checked_at: '2026-10-28T10:00:00Z',
}
const VERIFIED_BOT: S['VerifiedBot'] = {
  id: '8123456789',
  username: 'wesker_code_bot',
  first_name: 'Wesker',
  verified_at: '2026-10-28T10:00:00Z',
}

function makeView(over: Partial<S['TelegramView']> = {}): S['TelegramView'] {
  return {
    revision: 10,
    warnings: [],
    bot: { bot_id: null, username: null, credential: { present: false, source: 'unknown' } },
    control: { enabled: false, bot_id: null, enabled_at: null },
    owner: { bound: false, chat_id: null, source: null },
    notify: { include_details: false, ui_runs_to_owner: true },
    poller: {
      state: 'disabled',
      since: '2026-10-28T10:00:00Z',
      last_poll_at: null,
      last_error_category: null,
      consecutive_failures: 0,
    },
    acl: { groups: [], members: [], legacy_whitelist: [] },
    ...over,
  }
}

/** 已保存 Token、尚未校验（旧数据）。 */
const unverifiedView = () =>
  makeView({
    bot: { bot_id: null, username: null, credential: { present: true, source: 'imported' } },
  })

interface Fake {
  view: S['TelegramView']
  calls: { method: string; path: string; body: unknown }[]
  /** 导入/校验返回的 verify。 */
  verifyResult: S['TokenVerification']
  /** 导入成功后写入的已验证身份。 */
  importBot: S['VerifiedBot'] | null
  enableError: { status: number; code: string; message: string } | null
  enableToState: S['PollerView']['state']
  fetch: typeof fetch
}

function createFake(view: S['TelegramView']): Fake {
  const f: Fake = {
    view,
    calls: [],
    verifyResult: OK_VERIFY,
    importBot: VERIFIED_BOT,
    enableError: null,
    enableToState: 'polling',
    fetch: undefined as unknown as typeof fetch,
  }
  const applyVerify = () => {
    f.view.revision++
    f.view.bot.verify = f.verifyResult
    f.view.control.token_verify = f.verifyResult
    if (f.verifyResult.ok && f.importBot) {
      f.view.bot.verified_bot = f.importBot
      f.view.control.verified_bot = f.importBot
      f.view.bot.bot_id = f.importBot.id
      f.view.bot.username = f.importBot.username ?? null
    }
  }
  f.fetch = vi.fn(async (input: Request) => {
    const url = new URL(input.url)
    const raw = input.method === 'GET' || input.method === 'DELETE' ? '' : await input.text()
    const body = raw ? JSON.parse(raw) : undefined
    if (url.pathname === '/health')
      return json({ status: 'ok', version: '0.1.0', pid: 1, uptime_s: 1, alert: false })
    f.calls.push({ method: input.method, path: url.pathname, body })
    const p = url.pathname
    if (input.method === 'GET') {
      if (p === '/api/settings')
        return json({
          app_version: '0.1.0',
          data_dir: '/tmp/d',
          legacy_config_dir: '/tmp/l',
          revision: f.view.revision,
          schema_version: 2,
          store_state: 'ok',
          import: { state: 'completed' },
        })
      if (p === '/api/ado')
        return json({
          active_library_id: null,
          active_project_id: null,
          libraries: [],
          local_repos: [],
          projects: [],
          revision: f.view.revision,
        })
      if (p === '/api/credentials') return json([])
      if (p === '/api/telegram') return json(f.view)
      if (p === '/api/tasks') return json({ items: [], revision: f.view.revision })
      if (p === '/api/telegram/activity') return json({ items: [] })
      if (p === '/api/telegram/ai-bots') return json({ items: [], revision: 1, warnings: [] })
    }
    if (input.method === 'POST' && p === '/api/telegram/token/import-legacy') {
      f.view.bot.credential = { present: true, source: 'imported' }
      applyVerify()
      return json({ revision: f.view.revision, verify: f.verifyResult })
    }
    if (input.method === 'POST' && p === '/api/telegram/token/verify') {
      applyVerify()
      return json({ revision: f.view.revision, verify: f.verifyResult })
    }
    if (input.method === 'POST' && p === '/api/telegram/control/enable') {
      if (f.enableError)
        return json(
          { detail: { code: f.enableError.code, message: f.enableError.message } },
          f.enableError.status,
        )
      f.view.control.enabled = true
      f.view.poller.state = f.enableToState
      f.view.revision++
      return json({ revision: f.view.revision })
    }
    return json({ revision: f.view.revision })
  }) as unknown as typeof fetch
  return f
}

async function openTab(f: Fake) {
  const b = await boot({ path: '/settings', fetchImpl: f.fetch })
  b.sock.emit(hello())
  await flushPromises()
  const tab = b.wrapper.findAll('[role=tab]').find((t) => t.text().includes('Telegram'))!
  await tab.trigger('mousedown')
  await flushPromises()
  await flushPromises()
  return b
}

const q = (sel: string) => document.body.querySelector(sel) as HTMLElement | null
function check(sel: string) {
  const el = q(sel) as HTMLInputElement
  el.checked = true
  el.dispatchEvent(new Event('change'))
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

describe('主 Bot：导入后校验与身份', () => {
  it('导入后显示 @username 与 Bot ID、Token 有效提示，不再是“—”', async () => {
    const f = createFake(unverifiedView())
    const b = await openTab(f)
    await b.wrapper.find('[data-testid="import-legacy-token-btn"]').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(b.wrapper.find('[data-testid="bot-username"]').text()).toBe('@wesker_code_bot')
    expect(b.wrapper.find('[data-testid="bot-id"]').text()).toBe('8123456789')
    expect(b.wrapper.find('[data-testid="token-verify-ok"]').text()).toContain('@wesker_code_bot')
    const notice = b.wrapper.find('[data-testid="settings-notice"]').text()
    expect(notice).toContain('已从旧应用导入 Bot Token')
    expect(notice).toContain('Token 有效：@wesker_code_bot')
    await b.done()
  })

  it('未校验：身份显示“未校验”并提供“检查 Token”，点击后调用 verify 并带 revision 显示身份', async () => {
    const f = createFake(unverifiedView())
    const b = await openTab(f)
    expect(b.wrapper.find('[data-testid="bot-username"]').text()).toBe('未校验')
    expect(b.wrapper.find('[data-testid="bot-id"]').text()).toBe('未校验')
    expect(b.wrapper.find('[data-testid="token-verify-unchecked"]').exists()).toBe(true)
    const btn = b.wrapper.find('[data-testid="verify-token-btn"]')
    expect(btn.text()).toBe('检查 Token')

    await btn.trigger('click')
    await flushPromises()
    await flushPromises()
    const call = f.calls.find((c) => c.path === '/api/telegram/token/verify')!
    expect(call.body).toEqual({ revision: 10 })
    expect(b.wrapper.find('[data-testid="bot-username"]').text()).toBe('@wesker_code_bot')
    expect(b.wrapper.find('[data-testid="bot-id"]').text()).toBe('8123456789')
    await b.done()
  })

  it('校验失败：显示后端原因、重新录入提示与“重新检查”，且不出现启用引导', async () => {
    const f = createFake(unverifiedView())
    f.verifyResult = {
      ok: false,
      code: 'token_invalid',
      message: 'Token 无效或已被撤销',
      has_webhook: null,
      checked_at: '2026-10-28T10:00:00Z',
    }
    const b = await openTab(f)
    await b.wrapper.find('[data-testid="verify-token-btn"]').trigger('click')
    await flushPromises()
    await flushPromises()

    const err = b.wrapper.find('[data-testid="token-verify-error"]').text()
    expect(err).toContain('Token 无效或已被撤销')
    expect(err).toContain('重新录入')
    expect(b.wrapper.find('[data-testid="verify-token-btn"]').text()).toBe('重新检查')
    expect(b.wrapper.find('[data-testid="enable-guide-banner"]').exists()).toBe(false)
    await b.done()
  })

  it('网络类校验失败：提示稍后重新检查', async () => {
    const f = createFake(unverifiedView())
    f.verifyResult = {
      ok: false,
      code: 'telegram_unreachable',
      message: '无法连接 Telegram',
      has_webhook: null,
      checked_at: '2026-10-28T10:00:00Z',
    }
    const b = await openTab(f)
    await b.wrapper.find('[data-testid="verify-token-btn"]').trigger('click')
    await flushPromises()
    await flushPromises()
    const err = b.wrapper.find('[data-testid="token-verify-error"]').text()
    expect(err).toContain('无法连接 Telegram')
    expect(err).toContain('重新检查')
    await b.done()
  })

  it('has_webhook=true：提示启用时会询问是否删除，启用 Sheet 直接要求二次确认', async () => {
    const f = createFake(unverifiedView())
    f.verifyResult = { ...OK_VERIFY, has_webhook: true }
    const b = await openTab(f)
    await b.wrapper.find('[data-testid="verify-token-btn"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(b.wrapper.find('[data-testid="token-webhook-note"]').text()).toContain(
      '这个 Bot 设置了 webhook，启用时会询问是否删除',
    )
    await b.wrapper.find('[data-testid="enable-guide-btn"]').trigger('click')
    await flushPromises()
    expect(q('[data-testid="webhook-set-banner"]')).toBeTruthy()
    expect(q('[data-testid="confirm-delete-webhook-checkbox"]')).toBeTruthy()
    await b.done()
  })
})

describe('主 Bot：启用引导与启用结果', () => {
  const verifiedView = () =>
    makeView({
      bot: {
        bot_id: VERIFIED_BOT.id,
        username: VERIFIED_BOT.username ?? null,
        credential: { present: true, source: 'imported' },
        verified_bot: VERIFIED_BOT,
        verify: OK_VERIFY,
      },
      control: {
        enabled: false,
        bot_id: null,
        enabled_at: null,
        verified_bot: VERIFIED_BOT,
        token_verify: OK_VERIFY,
      },
    })

  it('已校验未启用：顶部出现“启用远程控制”横幅，点击打开启用 Sheet', async () => {
    const b = await openTab(createFake(verifiedView()))
    const banner = b.wrapper.find('[data-testid="enable-guide-banner"]')
    expect(banner.text()).toContain('Token 已验证（@wesker_code_bot）')
    expect(banner.text()).toContain('机器人现在不会响应任何命令')
    expect(q('[data-testid="enable-telegram-dialog"]')).toBeNull()
    await b.wrapper.find('[data-testid="enable-guide-btn"]').trigger('click')
    await flushPromises()
    expect(q('[data-testid="enable-telegram-dialog"]')).toBeTruthy()
    await b.done()
  })

  it('已启用：不显示启用引导横幅', async () => {
    const v = verifiedView()
    v.control.enabled = true
    v.poller.state = 'polling'
    const b = await openTab(createFake(v))
    expect(b.wrapper.find('[data-testid="enable-guide-banner"]').exists()).toBe(false)
    await b.done()
  })

  const ERRORS: [string, number, string, string][] = [
    ['ack_required', 409, '需要确认旧应用已停止轮询', '必须确认旧应用已停止轮询'],
    ['revision_conflict', 409, '配置已被修改', '已刷新为最新内容'],
    ['telegram_active', 409, 'Telegram 正在运行中', '请先在“远程控制”里停用'],
    ['telegram_request_failed', 502, 'Telegram 请求失败', '点“确认启用”重试'],
    ['telegram_unreachable', 502, '无法连接 Telegram', '点“确认启用”重试'],
    ['token_invalid', 401, 'Token 无效', '重新录入 Token'],
    ['webhook_set', 409, '已设置 Webhook', '二次确认删除 Webhook'],
  ]
  for (const [code, status, message, expected] of ERRORS) {
    it(`启用失败 ${code}：Sheet 内显示原因与下一步，Sheet 保持打开`, async () => {
      const f = createFake(verifiedView())
      f.enableError = { status, code, message }
      const b = await openTab(f)
      await b.wrapper.find('[data-testid="enable-guide-btn"]').trigger('click')
      await flushPromises()
      check('[data-testid="ack-old-bot-stopped-checkbox"]')
      await flushPromises()
      q('[data-testid="confirm-enable-btn"]')!.click()
      await flushPromises()
      await flushPromises()
      expect(q('[data-testid="enable-error-banner"]')?.textContent).toContain(expected)
      expect(q('[data-testid="enable-telegram-dialog"]')).toBeTruthy()
      await b.done()
    })
  }

  it('启用成功：Sheet 关闭，连接状态与引导横幅即时刷新', async () => {
    const f = createFake(verifiedView())
    const b = await openTab(f)
    await b.wrapper.find('[data-testid="enable-guide-btn"]').trigger('click')
    await flushPromises()
    check('[data-testid="ack-old-bot-stopped-checkbox"]')
    await flushPromises()
    q('[data-testid="confirm-enable-btn"]')!.click()
    await flushPromises()
    await flushPromises()
    expect(q('[data-testid="enable-telegram-dialog"]')).toBeNull()
    expect(b.wrapper.find('[data-testid="poller-status-pill"]').text()).toContain('轮询中')
    expect(b.wrapper.find('[data-testid="enable-guide-banner"]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid="bot-username"]').text()).toBe('@wesker_code_bot')
    await b.done()
  })

  it('启用后进入 conflict：页面提示冲突原因与下一步，并可重试接管', async () => {
    const f = createFake(verifiedView())
    f.enableToState = 'conflict'
    const b = await openTab(f)
    await b.wrapper.find('[data-testid="enable-guide-btn"]').trigger('click')
    await flushPromises()
    check('[data-testid="ack-old-bot-stopped-checkbox"]')
    await flushPromises()
    q('[data-testid="confirm-enable-btn"]')!.click()
    await flushPromises()
    await flushPromises()
    const notice = b.wrapper.find('[data-testid="settings-notice"]').text()
    expect(notice).toContain('已启用，但连接状态为“轮询冲突”')
    expect(notice).toContain('旧应用')
    expect(b.wrapper.find('[data-testid="poller-state-desc-banner"]').text()).toContain('重试接管')
    expect(b.wrapper.find('[data-testid="retry-poller-btn"]').exists()).toBe(true)
    await b.done()
  })
})

describe('AI 专属机器人：身份、校验与启用引导', () => {
  function aiBot(over: Partial<S['AIBotView']> = {}): S['AIBotView'] {
    return {
      ai_id: 'claude_code',
      slot: 'ai:claude_code',
      bot: { credential: { present: true, source: 'imported' }, bot_id: null, username: null },
      poller: {
        state: 'disabled',
        consecutive_failures: 0,
        last_error_category: null,
        since: '2026-10-28T10:00:00Z',
      },
      control: { enabled: false, bot_id: null, enabled_at: null },
      owner: { bound: false, chat_id: null, source: null },
      ...over,
    }
  }

  async function mountCard(
    bot: S['AIBotView'],
    handler: (req: Request, path: string) => Response | undefined,
  ) {
    const calls: { method: string; path: string; body: unknown }[] = []
    let current = bot
    const fetchImpl = vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname
      const raw = req.method === 'GET' ? '' : await req.text()
      if (path !== '/health')
        calls.push({ method: req.method, path, body: raw ? JSON.parse(raw) : undefined })
      if (path === '/api/telegram/ai-bots') return json({ items: [current], revision: 5 })
      const r = handler(req, path)
      if (r) return r
      return json({ revision: 6 })
    })
    const b = await boot({ fetchImpl: fetchImpl as unknown as typeof fetch })
    b.sock.emit(hello())
    await flushPromises()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const w = mount(TelegramAiBotsCard, {
      props: { busy: false, writable: true },
      global: {
        plugins: [[VueQueryPlugin, { queryClient }]] as unknown as (
          Plugin | [Plugin, ...unknown[]]
        )[],
        provide: { [backendRuntimeKey as symbol]: b.runtime },
      },
    })
    await flushPromises()
    await flushPromises()
    return { w, b, calls, setBot: (nb: S['AIBotView']) => (current = nb) }
  }

  it('未校验显示“未校验”+“检查 Token”；检查成功后显示 @username 与 Bot ID 及启用引导', async () => {
    const ctx = await mountCard(aiBot(), (_req, path) => {
      if (path === '/api/telegram/ai-bots/claude_code/token/verify') {
        ctx.setBot(
          aiBot({
            bot: {
              credential: { present: true, source: 'imported' },
              bot_id: '777',
              username: 'cc_bot',
              verified_bot: { id: '777', username: 'cc_bot', verified_at: 'x' },
              verify: OK_VERIFY,
            },
          }),
        )
        return json({ revision: 6, verify: OK_VERIFY })
      }
      return undefined
    })
    const { w } = ctx
    expect(w.find('[data-testid="ai-bot-username-claude_code"]').text()).toBe('未校验')
    expect(w.find('[data-testid="ai-bot-id-claude_code"]').text()).toBe('未校验')
    const btn = w.find('[data-testid="verify-ai-bot-token-btn-claude_code"]')
    expect(btn.text()).toBe('检查 Token')
    await btn.trigger('click')
    await flushPromises()
    await flushPromises()
    expect(ctx.calls.find((c) => c.path.endsWith('/token/verify'))!.body).toEqual({ revision: 5 })
    expect(w.find('[data-testid="ai-bot-username-claude_code"]').text()).toBe('@cc_bot')
    expect(w.find('[data-testid="ai-bot-id-claude_code"]').text()).toBe('777')
    expect(w.find('[data-testid="ai-bot-enable-guide-claude_code"]').text()).toContain(
      'Token 已验证（@cc_bot）',
    )
    w.unmount()
    await ctx.b.done()
  })

  it('导入后校验失败：显示原因与“重新检查”', async () => {
    const bad: S['TokenVerification'] = {
      ok: false,
      code: 'token_invalid',
      message: 'Token 无效或已被撤销',
      has_webhook: null,
      checked_at: 'x',
    }
    const ctx = await mountCard(aiBot(), (_req, path) =>
      path.endsWith('/token/import-legacy') ? json({ revision: 6, verify: bad }) : undefined,
    )
    const { w } = ctx
    await w.find('[data-testid="import-legacy-ai-bot-token-btn-claude_code"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(w.find('[data-testid="ai-bot-verify-error-claude_code"]').text()).toContain(
      'Token 无效或已被撤销',
    )
    expect(w.find('[data-testid="verify-ai-bot-token-btn-claude_code"]').text()).toBe('重新检查')
    expect(w.find('[data-testid="ai-bot-enable-guide-claude_code"]').exists()).toBe(false)
    w.unmount()
    await ctx.b.done()
  })

  it('webhook 提示；启用引导打开 Sheet；启用失败原因在 Sheet 内可见', async () => {
    const v: S['TokenVerification'] = { ...OK_VERIFY, has_webhook: true }
    const ctx = await mountCard(
      aiBot({
        bot: {
          credential: { present: true, source: 'manual' },
          bot_id: '777',
          username: 'cc_bot',
          verified_bot: { id: '777', username: 'cc_bot', verified_at: 'x' },
          verify: v,
        },
      }),
      (_req, path) =>
        path.endsWith('/control/enable')
          ? json({ detail: { code: 'telegram_request_failed', message: 'x' } }, 502)
          : undefined,
    )
    const { w } = ctx
    expect(w.find('[data-testid="ai-bot-webhook-note-claude_code"]').text()).toContain(
      '这个 Bot 设置了 webhook，启用时会询问是否删除',
    )
    await w.find('[data-testid="ai-bot-enable-guide-btn-claude_code"]').trigger('click')
    await flushPromises()
    expect(q('[data-testid="ai-bot-enable-sheet"]')).toBeTruthy()
    expect(q('[data-testid="ai-delete-webhook-checkbox"]')).toBeTruthy()
    check('[data-testid="ack-old-cleared-checkbox"]')
    check('[data-testid="ai-delete-webhook-checkbox"]')
    await flushPromises()
    q('[data-testid="confirm-enable-ai-bot-btn"]')!.click()
    await flushPromises()
    await flushPromises()
    expect(q('[data-testid="enable-error-banner"]')?.textContent).toContain('点“确认启用”重试')
    expect(
      (
        ctx.calls.find((c) => c.path.endsWith('/control/enable'))!.body as {
          delete_webhook: boolean
        }
      ).delete_webhook,
    ).toBe(true)
    w.unmount()
    await ctx.b.done()
  })
})
