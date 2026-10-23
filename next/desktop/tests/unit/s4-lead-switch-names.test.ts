// 主控集成 S4 时发现：Telegram 分区的开关没有可访问名称（读屏只念“开关”）。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

type S = components['schemas']

const telegram: S['TelegramView'] = {
  revision: 3,
  warnings: [],
  bot: {
    bot_id: '123456789',
    username: 'FakeBot',
    credential: { present: true, source: 'manual' },
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
}

const settings: S['SettingsResponse'] = {
  app_version: '0.1.0',
  data_dir: '/tmp/fake-data',
  legacy_config_dir: '/tmp/fake-legacy',
  revision: 3,
  schema_version: 2,
  store_state: 'ok',
  import: { state: 'completed' },
}

const routes: Record<string, unknown> = {
  '/health': { status: 'ok', version: '0.1.0', pid: 1, uptime_s: 1, alert: false },
  '/api/settings': settings,
  '/api/ado': {
    active_library_id: null,
    active_project_id: null,
    libraries: [],
    local_repos: [],
    projects: [],
    revision: 3,
  },
  '/api/credentials': [],
  '/api/telegram': telegram,
  '/api/telegram/activity': { items: [] },
  '/api/tasks': { items: [], revision: 3 },
}

const fakeFetch = (async (input: Request) => {
  const body = routes[new URL(input.url).pathname] ?? { revision: 3 }
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}) as unknown as typeof fetch

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

it('Telegram 分区的每个开关都有可访问名称', async () => {
  const b = await boot({ path: '/settings', fetchImpl: fakeFetch })
  b.sock.emit(hello())
  await flushPromises()
  const tab = b.wrapper.findAll('[role=tab]').find((t) => t.text().includes('Telegram'))!
  await tab.trigger('mousedown')
  await flushPromises()
  await flushPromises()

  const switches = b.wrapper.findAll('[role=switch]')
  expect(switches.length).toBe(3)
  expect(switches.map((s) => s.attributes('aria-label'))).toEqual([
    '启用 Telegram 控制',
    '包含详细信息',
    'UI 触发运行通知所有者',
  ])
})
