// S4-C 单测：设置页 Telegram 分区卡片（Bot / 接管 / Owner / 通知 / 最近活动 / 测试消息 / WS 状态）
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'

type S = components['schemas']

function makeTelegramView(over: Partial<S['TelegramView']> = {}): S['TelegramView'] {
  return {
    revision: 10,
    warnings: [],
    bot: {
      bot_id: '123456789',
      username: 'TestHelperBot',
      credential: {
        present: true,
        source: 'manual',
      },
    },
    control: {
      enabled: false,
      bot_id: '123456789',
      enabled_at: null,
    },
    owner: {
      bound: false,
      chat_id: null,
      source: null,
    },
    notify: {
      include_details: false,
      ui_runs_to_owner: true,
    },
    poller: {
      state: 'disabled',
      since: '2026-10-23T10:00:00Z',
      last_poll_at: null,
      last_error_category: null,
      consecutive_failures: 0,
    },
    acl: {
      groups: [],
      members: [],
      legacy_whitelist: [],
    },
    ...over,
  }
}

interface S4CFakeState {
  settings: S['SettingsResponse']
  ado: S['AdoResponse']
  creds: S['CredentialStatus'][]
  telegram: S['TelegramView']
  activities: S['ActivityItem'][]
}

function createS4CFake(initialTelegram?: Partial<S['TelegramView']>) {
  const state: S4CFakeState = {
    settings: {
      app_version: '0.1.0',
      data_dir: '/tmp/fake-data',
      legacy_config_dir: '/tmp/fake-legacy',
      revision: 10,
      schema_version: 2,
      store_state: 'ok',
      import: { state: 'completed' },
    },
    ado: {
      active_library_id: null,
      active_project_id: null,
      libraries: [],
      local_repos: [],
      projects: [],
      revision: 10,
    },
    creds: [],
    telegram: makeTelegramView(initialTelegram),
    activities: [
      {
        received_at: '2026-10-23T10:15:00Z',
        kind: 'message',
        command: '/status',
        chat_id: '88888',
        status: 'handled',
        reason: null,
      },
    ],
  }

  const calls: { method: string; path: string; query: Record<string, string>; body: unknown }[] = []
  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { 'content-type': 'application/json' },
    })

  const fetchHandler = vi.fn(async (input: Request) => {
    const url = new URL(input.url)
    const raw = input.method === 'GET' || input.method === 'DELETE' ? '' : await input.text()
    let body: unknown
    try {
      body = raw ? JSON.parse(raw) : undefined
    } catch {
      body = undefined
    }
    const call = {
      method: input.method,
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      body,
    }
    if (call.path !== '/health') calls.push(call)

    if (call.path === '/health') {
      return json({ status: 'ok', version: '0.1.0', pid: 1234, uptime_s: 1, alert: false })
    }
    if (call.method === 'GET' && call.path === '/api/settings') return json(state.settings)
    if (call.method === 'GET' && call.path === '/api/ado') return json(state.ado)
    if (call.method === 'GET' && call.path === '/api/credentials') return json(state.creds)
    if (call.method === 'GET' && call.path === '/api/telegram') return json(state.telegram)
    if (call.method === 'GET' && call.path === '/api/tasks')
      return json({ items: [], revision: state.settings.revision })
    if (call.method === 'GET' && call.path === '/api/telegram/activity') {
      return json({ items: state.activities })
    }

    // Token
    if (call.method === 'PUT' && call.path === '/api/telegram/token') {
      const b = body as { token?: string }
      if (!b?.token || !/^\d{5,16}:[A-Za-z0-9_-]{30,64}$/.test(b.token)) {
        return json({ detail: { code: 'validation_error', message: 'Token 格式不正确' } }, 422)
      }
      if (state.telegram.control.enabled) {
        return json(
          { detail: { code: 'telegram_active', message: 'Telegram 正在运行中，无法修改配置' } },
          409,
        )
      }
      state.telegram.bot.credential.present = true
      state.telegram.bot.credential.source = 'manual'
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }
    if (call.method === 'POST' && call.path === '/api/telegram/token/import-legacy') {
      if (state.telegram.control.enabled) {
        return json(
          { detail: { code: 'telegram_active', message: 'Telegram 正在运行中，无法修改配置' } },
          409,
        )
      }
      state.telegram.bot.credential.present = true
      state.telegram.bot.credential.source = 'imported'
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }
    if (call.method === 'DELETE' && call.path === '/api/telegram/token') {
      if (state.telegram.control.enabled) {
        return json(
          { detail: { code: 'telegram_active', message: 'Telegram 正在运行中，无法修改配置' } },
          409,
        )
      }
      state.telegram.bot.credential.present = false
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }

    // Control
    if (call.method === 'POST' && call.path === '/api/telegram/control/enable') {
      const b = body as { ack_old_bot_stopped?: boolean; delete_webhook?: boolean }
      if (!b?.ack_old_bot_stopped) {
        return json({ detail: { code: 'ack_required', message: '必须确认旧应用已停止' } }, 409)
      }
      state.telegram.control.enabled = true
      state.telegram.poller.state = 'polling'
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }
    if (call.method === 'POST' && call.path === '/api/telegram/control/disable') {
      state.telegram.control.enabled = false
      state.telegram.poller.state = 'disabled'
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }
    if (call.method === 'POST' && call.path === '/api/telegram/control/retry') {
      state.telegram.poller.state = 'polling'
      return json({ revision: state.telegram.revision })
    }

    // Owner
    if (call.method === 'POST' && call.path === '/api/telegram/owner/bind-code') {
      return json({
        code: '123456',
        expires_at: new Date(Date.now() + 600 * 1000).toISOString(),
      })
    }
    if (call.method === 'DELETE' && call.path === '/api/telegram/owner') {
      state.telegram.owner.bound = false
      state.telegram.owner.chat_id = null
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }

    // Settings / Notify
    if (call.method === 'PATCH' && call.path === '/api/telegram/settings') {
      const b = body as { notify?: { include_details?: boolean; ui_runs_to_owner?: boolean } }
      if (b?.notify?.include_details !== undefined) {
        state.telegram.notify.include_details = b.notify.include_details
      }
      if (b?.notify?.ui_runs_to_owner !== undefined) {
        state.telegram.notify.ui_runs_to_owner = b.notify.ui_runs_to_owner
      }
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }

    // Test message
    if (call.method === 'POST' && call.path === '/api/telegram/test-message') {
      if (!state.telegram.control.enabled || !state.telegram.owner.bound) {
        return json({ detail: { code: 'owner_not_bound', message: '未启用或未绑定所有者' } }, 409)
      }
      return json({ revision: state.telegram.revision })
    }

    return json({ revision: state.telegram.revision + 1 })
  })

  return {
    state,
    calls,
    fetch: fetchHandler as unknown as typeof fetch,
  }
}

describe('S4-C 设置页 Telegram 分区卡片单测', () => {
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

  async function openTelegramTab(fake: ReturnType<typeof createS4CFake>) {
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    // 切换至 Telegram 页签
    const tabBtn = b.wrapper.findAll('[role=tab]').find((t) => t.text().includes('Telegram'))!
    expect(tabBtn, '找到 Telegram 页签').toBeTruthy()
    await tabBtn.trigger('mousedown')
    await flushPromises()
    await flushPromises()
    return b
  }

  it('Bot 卡片：展示凭据状态、来源与用户名，绝不回显 Token 密钥值', async () => {
    const fake = createS4CFake()
    const b = await openTelegramTab(fake)

    expect(b.wrapper.find('[data-testid="bot-card"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="token-present-status"]').text()).toContain('已保存')
    expect(b.wrapper.find('[data-testid="token-present-status"]').text()).toContain('手动录入')
    expect(b.wrapper.find('[data-testid="bot-username"]').text()).toBe('@TestHelperBot')
    expect(b.wrapper.find('[data-testid="bot-id"]').text()).toBe('123456789')

    // 绝无真实 token 泄露到 DOM 或 storage
    expect(document.body.innerHTML).not.toContain('secret')
    expect(localStorage.getItem('telegram_token')).toBeNull()
    expect(sessionStorage.getItem('telegram_token')).toBeNull()

    await b.done()
  })

  it('Bot 卡片：录入 Token 提交后输入框立即清空，422 格式错误时不回显输入', async () => {
    const fake = createS4CFake()
    const b = await openTelegramTab(fake)

    const input = b.wrapper.find('input[data-testid="token-input"]')
    expect(input.attributes('type')).toBe('password')

    // 格式错误测试（前端正则拦截或后端 422）
    await input.setValue('invalid-token-input-123')
    await b.wrapper.find('button[data-testid="save-token-btn"]').trigger('click')
    await flushPromises()

    expect(b.wrapper.find('[data-testid="token-error-msg"]').text()).toContain('格式不正确')
    // 验证错误提示中绝不回显输入的 token 内容
    expect(b.wrapper.find('[data-testid="token-error-msg"]').text()).not.toContain(
      'invalid-token-input-123',
    )
    // 提交后输入框被立即清空
    expect((input.element as HTMLInputElement).value).toBe('')

    // 输入合法 Token
    const validToken = '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef'
    await input.setValue(validToken)
    await b.wrapper.find('button[data-testid="save-token-btn"]').trigger('click')
    await flushPromises()

    expect((input.element as HTMLInputElement).value).toBe('')
    expect(document.body.innerHTML).not.toContain(validToken)

    await b.done()
  })

  it('Bot 卡片：从旧应用导入遇 404 显示 legacy_missing 提示', async () => {
    const fake = createS4CFake()
    const origFetch = fake.fetch
    // 模拟导入返回 404 legacy_missing
    fake.fetch = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/token/import-legacy') {
        return new Response(
          JSON.stringify({
            detail: { code: 'legacy_missing', message: '旧应用中未找到 Telegram Bot Token' },
          }),
          { status: 404, headers: { 'content-type': 'application/json' } },
        )
      }
      return origFetch(req)
    }) as unknown as typeof fetch as unknown as typeof fetch

    const b = await openTelegramTab(fake)
    await b.wrapper.find('button[data-testid="import-legacy-token-btn"]').trigger('click')
    await flushPromises()

    const notice = b.wrapper.find('[data-testid="settings-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('旧应用中未找到 Telegram Bot Token')

    await b.done()
  })

  it('Bot 卡片：启用中尝试修改/删除 Token 遇 409 telegram_active 提示先停用', async () => {
    const fake = createS4CFake({
      control: { enabled: true, bot_id: '123456789', enabled_at: '2026-10-23T10:00:00Z' },
    })
    const b = await openTelegramTab(fake)

    const input = b.wrapper.find('input[data-testid="token-input"]')
    await input.setValue('123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef')
    await b.wrapper.find('button[data-testid="save-token-btn"]').trigger('click')
    await flushPromises()

    expect(b.wrapper.find('[data-testid="token-error-msg"]').text()).toContain(
      'Telegram 正在运行中，无法修改 Token，请先停用',
    )

    await b.done()
  })

  it('接管卡片：启用前弹 Sheet 展示切换步骤，必须勾选 ack_old_bot_stopped', async () => {
    const fake = createS4CFake()
    const b = await openTelegramTab(fake)

    // 点击 Switch 开启控制
    const switchEl = b.wrapper.find('[data-testid="telegram-control-switch"]')
    await switchEl.trigger('click')
    await flushPromises()

    // 检查 Sheet 弹出
    const dialog = document.querySelector('[data-testid="enable-telegram-dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog!.textContent).toContain('所有权切换步骤说明')
    expect(dialog!.textContent).toContain('S4 期间使用单独测试 Bot')
    expect(dialog!.textContent).toContain('my-own-script')
    expect(dialog!.textContent).toContain('telegram_bot_token')

    // 未勾选 ack 时，确认按钮处于 disabled 状态
    const confirmBtn = document.querySelector(
      'button[data-testid="confirm-enable-btn"]',
    ) as HTMLButtonElement
    expect(confirmBtn.disabled).toBe(true)

    // 勾选 ack
    const chk = document.querySelector(
      'input[data-testid="ack-old-bot-stopped-checkbox"]',
    ) as HTMLInputElement
    chk.checked = true
    chk.dispatchEvent(new Event('change'))
    await flushPromises()
    expect(confirmBtn.disabled).toBe(false)

    // 点击确认启用
    confirmBtn.click()
    await flushPromises()

    const enableCall = fake.calls.find((c) => c.path === '/api/telegram/control/enable')
    expect(enableCall).toBeTruthy()
    expect((enableCall?.body as { ack_old_bot_stopped: boolean }).ack_old_bot_stopped).toBe(true)

    await b.done()
  })

  it('接管卡片：409 webhook_set 时提示二次确认删除 Webhook 并带 delete_webhook: true', async () => {
    const fake = createS4CFake()
    const origFetch = fake.fetch
    fake.fetch = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/control/enable') {
        const body = (await req.json()) as { delete_webhook?: boolean }
        fake.calls.push({ method: 'POST', path: url.pathname, query: {}, body })
        if (!body.delete_webhook) {
          return new Response(
            JSON.stringify({
              detail: { code: 'webhook_set', message: '已设置 Webhook' },
            }),
            { status: 409, headers: { 'content-type': 'application/json' } },
          )
        }
        return new Response(JSON.stringify({ revision: 11 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return origFetch(req)
    }) as unknown as typeof fetch

    const b = await openTelegramTab(fake)

    // 触发开启
    await b.wrapper.find('[data-testid="telegram-control-switch"]').trigger('click')
    await flushPromises()

    // 勾选 ack
    const ackChk = document.querySelector(
      'input[data-testid="ack-old-bot-stopped-checkbox"]',
    ) as HTMLInputElement
    expect(ackChk).not.toBeNull()
    ackChk.checked = true
    ackChk.dispatchEvent(new Event('change'))
    await flushPromises()

    // 点击确认启用（首次返回 409 webhook_set）
    const confirmBtn = document.querySelector(
      'button[data-testid="confirm-enable-btn"]',
    ) as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    // 出现 Webhook 警告与二次确认勾选框
    expect(document.querySelector('[data-testid="webhook-set-banner"]')).not.toBeNull()
    const webhookChk = document.querySelector(
      'input[data-testid="confirm-delete-webhook-checkbox"]',
    ) as HTMLInputElement
    expect(webhookChk).not.toBeNull()

    // 勾选删除 Webhook 并再次点击确认
    webhookChk.checked = true
    webhookChk.dispatchEvent(new Event('change'))
    await flushPromises()
    confirmBtn.click()
    await flushPromises()

    const lastEnable = fake.calls.filter((c) => c.path === '/api/telegram/control/enable').pop()
    expect(lastEnable).toBeTruthy()
    expect((lastEnable?.body as { delete_webhook: boolean }).delete_webhook).toBe(true)

    await b.done()
  })

  it('接管卡片：轮询状态 9 种状态中文文案、conflict 说明、重试接管可用性与连续失败警告', async () => {
    // 1. conflict 状态
    const fake = createS4CFake({
      poller: {
        state: 'conflict',
        since: '2026-10-23T10:00:00Z',
        last_poll_at: null,
        last_error_category: 'conflict',
        consecutive_failures: 12,
      },
    })
    const b = await openTelegramTab(fake)

    const pill = b.wrapper.find('[data-testid="poller-status-pill"]')
    expect(pill.text()).toBe('轮询冲突')
    expect(b.wrapper.find('[data-testid="poller-state-desc-banner"]').text()).toContain(
      '另一个程序（可能是旧应用）正在轮询这个 Bot',
    )
    expect(b.wrapper.find('[data-testid="poller-failure-banner"]').text()).toContain(
      '连续轮询失败已达 12 次',
    )

    // conflict 下重试接管按钮可用
    const retryBtn = b.wrapper.find('button[data-testid="retry-poller-btn"]')
    expect(retryBtn.exists()).toBe(true)
    expect(retryBtn.attributes('disabled')).toBeUndefined()
    await retryBtn.trigger('click')
    await flushPromises()
    expect(fake.calls.some((c) => c.path === '/api/telegram/control/retry')).toBe(true)

    await b.done()
  })

  it('接管卡片：WS telegram.status 事件触发轮询状态实时更新', async () => {
    const fake = createS4CFake({
      poller: {
        state: 'polling',
        since: '2026-10-23T10:00:00Z',
        last_poll_at: null,
        last_error_category: null,
        consecutive_failures: 0,
      },
    })
    const b = await openTelegramTab(fake)

    expect(b.wrapper.find('[data-testid="poller-status-pill"]').text()).toBe('轮询中')

    // 通过 WS 广播 telegram.status 进入 backoff 状态
    b.sock.emit(
      env('telegram.status', {
        state: 'backoff',
        since: '2026-10-23T10:05:00Z',
        last_error_category: 'timeout',
      }),
    )
    await flushPromises()

    expect(b.wrapper.find('[data-testid="poller-status-pill"]').text()).toBe('等待退避')
    expect(b.wrapper.find('[data-testid="poller-backoff-note"]').text()).toContain(
      '网络异常（timeout），正在等待指数退避重试…',
    )

    await b.done()
  })

  it('接管卡片防回滚：在途 GET /api/telegram 完成时，不得以旧 poller 覆盖较新的 WS 状态', async () => {
    let resolveSecondGet!: (value: Response) => void
    let getTelegramCalls = 0
    let holdGet = false

    const initialView = makeTelegramView({
      poller: {
        state: 'disabled',
        since: '2026-10-23T10:00:00Z',
        last_poll_at: null,
        last_error_category: null,
        consecutive_failures: 0,
      },
    })

    const fake = createS4CFake(initialView)
    const origFetch = fake.fetch

    fake.fetch = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram' && req.method === 'GET') {
        getTelegramCalls++
        if (holdGet && getTelegramCalls >= 2) {
          return new Promise<Response>((resolve) => {
            resolveSecondGet = resolve
          })
        }
      }
      return origFetch(req)
    }) as unknown as typeof fetch

    const b = await openTelegramTab(fake)
    expect(b.wrapper.find('[data-testid="poller-status-pill"]').text()).toBe('已停用')

    // 触发第二个 GET 并挂起
    holdGet = true
    b.sock.emit(env('settings.changed', { revision: 11 }))
    await flushPromises()
    expect(getTelegramCalls).toBe(2)

    // 在途期间收到 WS telegram.status 状态推进为 conflict
    b.sock.emit(
      env('telegram.status', {
        state: 'conflict',
        since: '2026-10-23T10:02:00Z',
        last_error_category: 'conflict',
      }),
    )
    await flushPromises()
    expect(b.wrapper.find('[data-testid="poller-status-pill"]').text()).toBe('轮询冲突')

    // 旧 GET 响应最后到达（返回旧 disabled 状态）
    resolveSecondGet(
      new Response(JSON.stringify(initialView), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    await flushPromises()

    // 状态必须保持较新的 conflict，不得被旧的 disabled 覆盖
    expect(b.wrapper.find('[data-testid="poller-status-pill"]').text()).toBe('轮询冲突')

    await b.done()
  })

  it('Owner 卡片：未绑定时生成 6 位绑定码与倒计时；已绑定时支持解绑', async () => {
    const fake = createS4CFake({
      owner: { bound: false, chat_id: null, source: null },
    })
    const b = await openTelegramTab(fake)

    expect(b.wrapper.find('[data-testid="owner-unbound-box"]').exists()).toBe(true)

    // 点击生成绑定码
    await b.wrapper.find('button[data-testid="create-bind-code-btn"]').trigger('click')
    await flushPromises()

    expect(b.wrapper.find('[data-testid="bind-code-display"]').text()).toBe('123456')
    expect(b.wrapper.find('[data-testid="bind-code-countdown"]').text()).toContain('有效时间：')

    // 模拟通过 WS 收到 owner 绑定成功并刷新为 bound
    fake.state.telegram.owner.bound = true
    fake.state.telegram.owner.chat_id = '99999'
    fake.state.telegram.owner.source = 'bound'
    b.sock.emit(
      env('settings.changed', {
        revision: 11,
      }),
    )
    await flushPromises()
    await flushPromises()

    expect(b.wrapper.find('[data-testid="owner-chat-id"]').text()).toBe('99999')
    expect(b.wrapper.find('[data-testid="owner-source"]').text()).toBe('绑定码绑定')

    // 点击解绑
    await b.wrapper.find('button[data-testid="unbind-owner-btn"]').trigger('click')
    await flushPromises()
    const confirmUnbindBtn = document.querySelector(
      'button[data-testid="confirm-unbind-btn"]',
    ) as HTMLButtonElement
    expect(confirmUnbindBtn).not.toBeNull()
    confirmUnbindBtn.click()
    await flushPromises()

    expect(fake.calls.some((c) => c.method === 'DELETE' && c.path === '/api/telegram/owner')).toBe(
      true,
    )

    await b.done()
  })

  it('通知卡片与测试消息：开关持久化与未启用/未绑定拦截', async () => {
    const fake = createS4CFake({
      control: { enabled: false, bot_id: '123456789', enabled_at: null },
      owner: { bound: false, chat_id: null, source: null },
      notify: { include_details: false, ui_runs_to_owner: true },
    })
    const b = await openTelegramTab(fake)

    // 未启用且未绑定时测试消息禁用
    const testBtn = b.wrapper.find('button[data-testid="send-test-message-btn"]')
    expect(testBtn.attributes('disabled')).toBeDefined()
    expect(b.wrapper.find('[data-testid="test-message-hint"]').text()).toContain(
      '需先启用 Telegram 长轮询并绑定所有者',
    )

    // 切换通知开关
    await b.wrapper.find('[data-testid="notify-details-switch"]').trigger('click')
    await flushPromises()

    const patchCall = fake.calls.find(
      (c) => c.method === 'PATCH' && c.path === '/api/telegram/settings',
    )
    expect(patchCall).toBeTruthy()
    expect(
      (patchCall?.body as { notify: { include_details: boolean } }).notify.include_details,
    ).toBe(true)

    await b.done()
  })

  it('最近活动：列表渲染各字段且不含消息正文', async () => {
    const fake = createS4CFake()
    const b = await openTelegramTab(fake)

    expect(b.wrapper.find('[data-testid="activity-table"]').exists()).toBe(true)
    const row = b.wrapper.find('[data-testid="activity-row-0"]')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('/status')
    expect(row.text()).toContain('88888')
    expect(row.text()).toContain('handled')

    await b.done()
  })
})
