import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import { boot } from '../unit/boot'
import { env, FakeSocket, hello, resetSeq } from '../unit/helpers'

type S = components['schemas']
type Call = { method: string; path: string; query: Record<string, string>; body?: unknown }
const tokenSecret = '777777777:AbCdEfGhIjKlMnOpQrStUvWxYz_1234567890'

function telegram(over: Partial<S['TelegramView']> = {}): S['TelegramView'] {
  return {
    revision: 41,
    warnings: [],
    bot: {
      bot_id: '777777777',
      username: 'SafeBot',
      credential: { present: false, source: 'manual' },
    },
    control: { enabled: false, bot_id: null, enabled_at: null },
    owner: { bound: false, chat_id: null, source: null },
    notify: { include_details: false, ui_runs_to_owner: true },
    poller: {
      state: 'disabled',
      since: '2026-10-23T10:00:00Z',
      last_poll_at: null,
      last_error_category: null,
      consecutive_failures: 0,
    },
    acl: { groups: [], members: [], legacy_whitelist: [] },
    ...over,
  }
}

function baseResponse(path: string, currentTelegram: S['TelegramView']): unknown {
  if (path === '/health') return { status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false }
  if (path === '/api/settings')
    return {
      app_version: '1',
      data_dir: '/tmp/data',
      legacy_config_dir: '/tmp/legacy',
      revision: 41,
      schema_version: 2,
      store_state: 'ok',
      import: { state: 'completed' },
    } satisfies S['SettingsResponse']
  if (path === '/api/ado')
    return {
      active_library_id: null,
      active_project_id: null,
      libraries: [],
      local_repos: [],
      projects: [],
      revision: 41,
    } satisfies S['AdoResponse']
  if (path === '/api/credentials') return [] satisfies S['CredentialStatus'][]
  if (path === '/api/telegram') return currentTelegram
  if (path === '/api/tasks') return { items: [], revision: 41 } satisfies S['TaskListResponse']
  if (path === '/api/telegram/activity') return { items: [] } satisfies S['ActivityResponse']
  return { revision: 42 }
}

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

async function openTelegram(b: Awaited<ReturnType<typeof boot>>) {
  b.sock.emit(hello())
  await flushPromises()
  const tab = b.wrapper.findAll('button').find((button) => button.text().trim() === 'Telegram')
  if (!tab) throw new Error('Telegram settings tab was not rendered')
  await tab.trigger('mousedown')
  await flushPromises()
  await flushPromises()
}

describe('S4-C 独立状态时序与敏感信息验证', () => {
  beforeEach(() => {
    FakeSocket.reset()
    resetSeq()
    localStorage.clear()
    sessionStorage.clear()
    document.body.innerHTML = ''
  })
  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('WS telegram.status 在 GET /api/telegram 在途时到达，旧 GET 完成不得覆盖较新的状态', async () => {
    let resolveTelegram!: (value: Response) => void
    let telegramRequests = 0
    let holdSecondGet = false
    const oldView = telegram()
    const fetchImpl = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram') {
        telegramRequests++
        if (holdSecondGet && telegramRequests === 2) {
          return new Promise<Response>((resolve) => {
            resolveTelegram = resolve
          })
        }
      }
      return response(baseResponse(url.pathname, oldView))
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl, path: '/settings' })
    await openTelegram(b)
    expect(telegramRequests).toBe(1)
    expect(document.querySelector('[data-poller-state]')?.getAttribute('data-poller-state')).toBe(
      'disabled',
    )

    holdSecondGet = true
    b.sock.emit(env('settings.changed', { revision: 42 }))
    await flushPromises()
    expect(telegramRequests).toBe(2)
    b.sock.emit(env('telegram.status', { state: 'conflict', since: '2026-10-23T10:01:00Z' }))
    await flushPromises()
    expect(document.querySelector('[data-poller-state]')?.textContent).toContain('轮询冲突')

    resolveTelegram(response(oldView))
    await flushPromises()
    expect(document.querySelector('[data-poller-state]')?.textContent).toContain('轮询冲突')
    await b.done()
  })

  it('Token 422 后不回显，且 Token 不进入浏览器存储、URL、console、DOM 或 Pinia 状态', async () => {
    const calls: Call[] = []
    const view = telegram()
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {})
    const fetchImpl = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      const raw = req.method === 'GET' || req.method === 'DELETE' ? '' : await req.text()
      let body: unknown
      try {
        body = raw ? JSON.parse(raw) : undefined
      } catch {
        body = undefined
      }
      calls.push({
        method: req.method,
        path: url.pathname,
        query: Object.fromEntries(url.searchParams),
        body,
      })
      if (url.pathname === '/api/telegram/token' && req.method === 'PUT') {
        return response({ detail: { code: 'validation_error', message: 'Token 格式不正确' } }, 422)
      }
      return response(baseResponse(url.pathname, view))
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl, path: '/settings' })
    await openTelegram(b)
    const input = b.wrapper.get('[data-testid="token-input"]')
    await input.setValue(tokenSecret)
    await b.wrapper.get('[data-testid="save-token-btn"]').trigger('click')
    await flushPromises()

    expect((input.element as HTMLInputElement).value).toBe('')
    expect(document.body.textContent).not.toContain(tokenSecret)
    expect(document.body.innerHTML).not.toContain(tokenSecret)
    const storageValues = (storage: Storage) =>
      Array.from(
        { length: storage.length },
        (_, i) => `${storage.key(i)}=${storage.getItem(storage.key(i) ?? '')}`,
      ).join('\n')
    expect(`${storageValues(localStorage)}\n${storageValues(sessionStorage)}`).not.toContain(
      tokenSecret,
    )
    expect(location.href).not.toContain(tokenSecret)
    expect(JSON.stringify(b.store.$state)).not.toContain(tokenSecret)
    expect(JSON.stringify([errorSpy.mock.calls, logSpy.mock.calls])).not.toContain(tokenSecret)
    expect(calls.find((c) => c.path === '/api/telegram/token')?.body).toEqual({
      revision: 41,
      token: tokenSecret,
    })
    expect(calls.filter((c) => c.path.includes(tokenSecret))).toHaveLength(0)
    await b.done()
  })

  it('最近活动只呈现 ActivityItem 字段，忽略额外正文；空列表给出空态', async () => {
    const bodyText = 'PRIVATE_TELEGRAM_MESSAGE_BODY'
    let rows: S['ActivityItem'][] = []
    const fetchImpl = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      const result = baseResponse(url.pathname, telegram())
      if (url.pathname === '/api/telegram/activity')
        return response({ items: rows.map((x) => ({ ...x, message_text: bodyText })) })
      return response(result)
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl, path: '/settings' })
    await openTelegram(b)
    expect(document.querySelector('[data-testid="activity-table"]')?.textContent).toContain(
      '暂无活动记录',
    )
    rows = [
      {
        received_at: '2026-10-23T10:02:00Z',
        kind: 'message',
        command: '/status',
        chat_id: '9001',
        status: 'handled',
        reason: null,
      },
    ]
    await b.wrapper.get('[data-testid="refresh-activity-btn"]').trigger('click')
    await flushPromises()
    const table = document.querySelector('[data-testid="activity-table"]')?.textContent ?? ''
    expect(table).toContain('/status')
    expect(table).toContain('9001')
    expect(table).not.toContain(bodyText)
    await b.done()
  })

  it('测试消息在未绑定所有者时保持禁用', async () => {
    const view = telegram({
      control: { enabled: true, bot_id: '777777777', enabled_at: '2026-10-23T00:00:00Z' },
    })
    const fetchImpl = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      return response(baseResponse(url.pathname, view))
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl, path: '/settings' })
    await openTelegram(b)
    expect(
      (b.wrapper.get('[data-testid="send-test-message-btn"]').element as HTMLButtonElement)
        .disabled,
    ).toBe(true)
    await b.done()
  })
})
