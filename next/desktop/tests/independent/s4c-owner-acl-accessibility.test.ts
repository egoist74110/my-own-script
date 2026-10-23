import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import TelegramEnableSheet from '@/features/settings/TelegramEnableSheet.vue'
import TelegramGroupEditSheet from '@/features/settings/TelegramGroupEditSheet.vue'
import { boot } from '../unit/boot'
import { FakeSocket, hello, resetSeq } from '../unit/helpers'

type S = components['schemas']
const tg: S['TelegramView'] = {
  revision: 7,
  warnings: [],
  bot: { bot_id: '123456', username: 'AuditBot', credential: { present: true, source: 'manual' } },
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
}
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
function base(path: string) {
  if (path === '/health') return { status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false }
  if (path === '/api/settings')
    return {
      app_version: '1',
      data_dir: '/tmp/data',
      legacy_config_dir: '/tmp/legacy',
      revision: 7,
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
      revision: 7,
    } satisfies S['AdoResponse']
  if (path === '/api/credentials') return [] satisfies S['CredentialStatus'][]
  if (path === '/api/telegram') return tg
  if (path === '/api/tasks') return { items: [], revision: 7 } satisfies S['TaskListResponse']
  if (path === '/api/telegram/activity') return { items: [] } satisfies S['ActivityResponse']
  return { revision: 8 }
}

async function openTab(b: Awaited<ReturnType<typeof boot>>) {
  b.sock.emit(hello())
  await flushPromises()
  const tab = b.wrapper.findAll('[role="tab"]').find((el) => el.text().includes('Telegram'))
  if (!tab) throw new Error('Telegram settings tab was not rendered')
  await tab.trigger('mousedown')
  await flushPromises()
  await flushPromises()
}

describe('S4-C 独立接管确认、owner 生命周期与 ACL 会话检查', () => {
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

  it('接管确认先确认旧 Bot 让出，再次确认后才允许删除 Webhook', async () => {
    const wrapper = mount(TelegramEnableSheet, {
      props: { open: true, webhookSet: true },
      attachTo: document.body,
    })
    await flushPromises()
    const dialog = document.querySelector('[data-testid="enable-telegram-dialog"]')!
    expect(dialog.textContent).toContain('单独测试 Bot')
    expect(dialog.textContent).toContain('my-own-script')
    expect(dialog.textContent).toContain('telegram_bot_token')
    expect(dialog.textContent).toContain('三个 AI 机器人')
    expect(dialog.textContent).toContain('回退')
    const confirm = document.querySelector(
      '[data-testid="confirm-enable-btn"]',
    ) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    ;(
      document.querySelector('[data-testid="ack-old-bot-stopped-checkbox"]') as HTMLInputElement
    ).click()
    await flushPromises()
    expect(confirm.disabled).toBe(true)
    ;(
      document.querySelector('[data-testid="confirm-delete-webhook-checkbox"]') as HTMLInputElement
    ).click()
    await flushPromises()
    expect(confirm.disabled).toBe(false)
    confirm.click()
    await flushPromises()
    expect(wrapper.emitted('confirm')?.[0]?.[0]).toEqual({
      ackOldBotStopped: true,
      deleteWebhook: true,
    })
    wrapper.unmount()
  })

  it('owner 绑定码六位、十分钟后可重生，卸载时清除倒计时', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-23T10:00:00Z'))
    const calls: string[] = []
    const fetchImpl = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/owner/bind-code') {
        calls.push(url.pathname)
        return json({ code: '654321', expires_at: new Date(Date.now() + 600_000).toISOString() })
      }
      return json(base(url.pathname))
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl, path: '/settings' })
    await openTab(b)
    await b.wrapper.get('[data-testid="create-bind-code-btn"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-testid="bind-code-display"]')?.textContent).toBe('654321')
    expect(document.querySelector('[data-testid="bind-code-countdown"]')?.textContent).toContain(
      '10:00',
    )
    await vi.advanceTimersByTimeAsync(600_000)
    await flushPromises()
    expect(document.querySelector('[data-testid="bind-code-countdown"]')?.textContent).toContain(
      '已过期',
    )
    await b.wrapper.get('[data-testid="regen-bind-code-btn"]').trigger('click')
    await flushPromises()
    expect(calls).toHaveLength(2)
    expect(document.querySelector('[data-testid="bind-code-countdown"]')?.textContent).toContain(
      '10:00',
    )
    const clearSpy = vi.spyOn(globalThis, 'clearInterval')
    await b.done()
    expect(clearSpy).toHaveBeenCalled()
  })

  it('权限组编辑不能在空名称或无任务执行权限时提交', async () => {
    const wrapper = mount(TelegramGroupEditSheet, {
      props: { open: true, group: null, allTasks: [], submitting: false },
      attachTo: document.body,
    })
    await flushPromises()
    const nameInput = document.querySelector(
      '[data-testid="group-name-input"] input',
    ) as HTMLInputElement
    ;(document.querySelector('[data-testid="save-group-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(document.querySelector('[data-testid="group-validation-error"]')?.textContent).toContain(
      '组名称不能为空',
    )
    const runCheckbox = document.querySelector(
      '[data-testid="perm-can-run"] input',
    ) as HTMLInputElement
    runCheckbox.click()
    nameInput.value = '夜间发布组'
    nameInput.dispatchEvent(new Event('input', { bubbles: true }))
    const saveButton = document.querySelector('[data-testid="save-group-btn"]') as HTMLButtonElement
    saveButton.click()
    await flushPromises()
    expect(document.querySelector('[data-testid="group-validation-error"]')?.textContent).toContain(
      '至少选择一个任务',
    )
    expect(wrapper.emitted('save')).toBeUndefined()
    wrapper.unmount()
  })
})
