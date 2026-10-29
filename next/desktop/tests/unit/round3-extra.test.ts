// 第三轮改版的补充测试：补齐时间/姓名格式化、工单看板列回退、发布命令选择器的禁用原因与请求体、设置页时间与 token 不外泄。
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import CommandPickerSheet from '@/features/tasks/CommandPickerSheet.vue'
import type { CommandView, ReleaseView } from '@/features/tasks/api'
import { fmtLocal } from '@/features/settings/format'
import { formatMonthDay, formatShort, initials } from '@/features/work-items/format'
import { SELECTION_KEY } from '@/features/work-items/selection'
import { boot, json } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { createFake, makeCreds } from './settings-fake'
import { createWiFake, wiErr, type WiFake } from './wi-fake'
import { clickTab, settle } from './wi-helpers'

const pad = (n: number) => String(n).padStart(2, '0')
/** 独立于被测实现的本地时间展示：MM-DD HH:mm。 */
function localMMDDHHmm(iso: string): string {
  const d = new Date(iso)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function localMMDD(iso: string): string {
  const d = new Date(iso)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
})

// ───────────────────────── settings/format.ts：fmtLocal ─────────────────────────

describe('设置页时间 fmtLocal', () => {
  it('带 Z 的 ISO：按本地时区输出 MM-DD HH:mm，不露 ISO 原文', () => {
    const out = fmtLocal('2026-10-22T10:05:00Z')
    expect(out).toBe(localMMDDHHmm('2026-10-22T10:05:00Z'))
    expect(out).toMatch(/^\d{2}-\d{2} \d{2}:\d{2}$/)
    expect(out).not.toContain('T')
    expect(out).not.toContain('Z')
  })

  it('带偏移的 ISO 与同一瞬间的 UTC 输出相同（+08:00 的 10:05 就是 02:05Z）', () => {
    expect(fmtLocal('2026-10-22T10:05:00+08:00')).toBe(fmtLocal('2026-10-22T02:05:00Z'))
    expect(fmtLocal('2026-10-22T10:05:00-05:00')).toBe(fmtLocal('2026-10-22T15:05:00Z'))
  })

  it('不带时区的 ISO 按本地时间读取，字段原样显示', () => {
    expect(fmtLocal('2026-10-22T10:05:00')).toBe('10-22 10:05')
    expect(fmtLocal('2026-01-03T00:00:00')).toBe('01-03 00:00')
  })

  it('数字按秒处理（与后端 checked_at 一致）：1700000000 等于 2023-11-14T22:13:20Z', () => {
    expect(fmtLocal(1700000000)).toBe(fmtLocal('2023-11-14T22:13:20Z'))
    expect(fmtLocal(1700000000)).toBe(localMMDDHHmm('2023-11-14T22:13:20Z'))
  })

  it('空值（null / undefined / 空串）返回占位，可自定义占位文字', () => {
    expect(fmtLocal(null)).toBe('—')
    expect(fmtLocal(undefined)).toBe('—')
    expect(fmtLocal('')).toBe('—')
    expect(fmtLocal(null, '从未')).toBe('从未')
  })

  it('非法字符串原样返回；非法数字（NaN）返回占位', () => {
    expect(fmtLocal('not-a-date')).toBe('not-a-date')
    expect(fmtLocal(Number.NaN)).toBe('—')
    expect(fmtLocal(Number.NaN, '无')).toBe('无')
  })
})

// ───────────────────────── work-items/format.ts ─────────────────────────

describe('工单时间 formatMonthDay / formatShort', () => {
  it('formatMonthDay：ISO → MM-DD；带 Z 的按本地日期', () => {
    expect(formatMonthDay('2026-10-05T12:00:00')).toBe('10-05')
    expect(formatMonthDay('2026-10-05T12:00:00Z')).toBe(localMMDD('2026-10-05T12:00:00Z'))
    expect(formatMonthDay('2026-01-09T08:00:00')).toBe('01-09')
  })

  it('formatMonthDay：空值 → “—”；非法值原样返回', () => {
    expect(formatMonthDay(null)).toBe('—')
    expect(formatMonthDay(undefined)).toBe('—')
    expect(formatMonthDay('')).toBe('—')
    expect(formatMonthDay('昨天')).toBe('昨天')
  })

  it('formatShort：ISO → MM-DD HH:mm（评论时间）', () => {
    expect(formatShort('2026-10-05T09:07:00')).toBe('10-05 09:07')
    expect(formatShort('2026-10-05T23:59:00Z')).toBe(localMMDDHHmm('2026-10-05T23:59:00Z'))
  })

  it('formatShort：空值 → “—”；非法值原样返回，不抛错', () => {
    expect(formatShort(null)).toBe('—')
    expect(formatShort(undefined)).toBe('—')
    expect(formatShort('')).toBe('—')
    expect(formatShort('x')).toBe('x')
  })
})

describe('头像首字 initials', () => {
  it('按空格、下划线、点、横线分词取前两词首字并大写', () => {
    expect(initials('zhang san')).toBe('ZS')
    expect(initials('li_wei')).toBe('LW')
    expect(initials('a.b-c')).toBe('AB')
    expect(initials('bob smith jr')).toBe('BS')
    expect(initials('-x y')).toBe('XY')
  })

  it('单个词取前两个字符（大写）；中文按字符取', () => {
    expect(initials('ab')).toBe('AB')
    expect(initials('Wesker')).toBe('WE')
    expect(initials('x')).toBe('X')
    expect(initials('李 四')).toBe('李四')
  })

  it('空、纯空白、null、undefined → “?”', () => {
    expect(initials('')).toBe('?')
    expect(initials('   ')).toBe('?')
    expect(initials(null)).toBe('?')
    expect(initials(undefined)).toBe('?')
  })
})

// ───────────────────────── 工单页：看板列回退 ─────────────────────────

/** 替换 /api/work-items/columns 的响应；其余路径仍走工单假后端。 */
function withColumnsResponse(f: WiFake, make: () => Response) {
  const inner = f.fetch as unknown as (r: Request) => Promise<Response>
  f.fetch = (async (input: Request) => {
    if (new URL(input.url).pathname === '/api/work-items/columns') return make()
    return inner(input)
  }) as unknown as typeof fetch
}

const BUILTIN = ['新建', '待开发', '开发中', '测试', '已关闭']

async function openWorkItems(fake: WiFake) {
  const b = await boot({ path: '/work-items', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await settle(5)
  return b
}
/** 站点的名字（去掉条数）。 */
function stationNames(b: Awaited<ReturnType<typeof openWorkItems>>): string[] {
  return b.wrapper
    .get('[role=tablist][aria-label=看板列]')
    .findAll('[role=tab]')
    .map((t) => t.text().split(/\s+/)[0]!)
}
function selectedStation(b: Awaited<ReturnType<typeof openWorkItems>>): string {
  const t = b.wrapper
    .get('[role=tablist][aria-label=看板列]')
    .findAll('[role=tab]')
    .find((x) => x.attributes('aria-selected') === 'true')
  return t ? t.text().split(/\s+/)[0]! : ''
}

describe('工单看板列回退（BoardRoute 的数据来源）', () => {
  it('接口返回空数组列：站点退回内置五列', async () => {
    const fake = createWiFake()
    withColumnsResponse(fake, () => json({ columns: [], default: '处理中' }))
    const b = await openWorkItems(fake)
    expect(stationNames(b)).toEqual(BUILTIN)
    expect(selectedStation(b)).toBe('开发中')
    await b.done()
  })

  it('接口返回的列含非字符串项：整组作废，退回内置五列', async () => {
    const fake = createWiFake()
    withColumnsResponse(fake, () => json({ columns: ['待处理', 42, null], default: '待处理' }))
    const b = await openWorkItems(fake)
    expect(stationNames(b)).toEqual(BUILTIN)
    await b.done()
  })

  it('接口响应没有 columns 数组（旧后端形状）：退回内置五列，忽略 default', async () => {
    const fake = createWiFake()
    withColumnsResponse(fake, () => json({ default: '处理中' }))
    const b = await openWorkItems(fake)
    expect(stationNames(b)).toEqual(BUILTIN)
    expect(selectedStation(b)).toBe('开发中')
    await b.done()
  })

  it('保存的列不在接口列里：退回接口 default 列，并把列写回存储', async () => {
    const fake = createWiFake()
    const COLS = ['待处理', '处理中', '验收', '完成']
    withColumnsResponse(fake, () => json({ columns: COLS, default: '处理中' }))
    localStorage.setItem(SELECTION_KEY, JSON.stringify({ project_id: 'proj:a', column: '已关闭' }))
    const b = await openWorkItems(fake)
    expect(stationNames(b)).toEqual(COLS)
    expect(selectedStation(b)).toBe('处理中')
    const lists = fake.to('/api/work-items').filter((c) => c.path === '/api/work-items')
    expect(lists.at(-1)!.query).toEqual({ project_id: 'proj:a', column: '处理中' })
    expect(JSON.parse(localStorage.getItem(SELECTION_KEY)!).column).toBe('处理中')
    await b.done()
  })

  it('保存的列不在接口列里、接口也没给 default：退回接口的第一列', async () => {
    const fake = createWiFake()
    const COLS = ['待处理', '处理中', '验收', '完成']
    withColumnsResponse(fake, () => json({ columns: COLS }))
    localStorage.setItem(SELECTION_KEY, JSON.stringify({ project_id: 'proj:a', column: '测试' }))
    const b = await openWorkItems(fake)
    expect(selectedStation(b)).toBe('待处理')
    await b.done()
  })

  it('接口读取失败（500）且保存的列不在内置五列里：存储读取时已丢弃，列回到内置默认「开发中」', async () => {
    // 读取 localStorage 时（selection.ts）无效列已被丢弃，所以接口失败也不会停在无效列上。
    const fake = createWiFake()
    withColumnsResponse(fake, () => wiErr(500, 'ado_request_failed'))
    localStorage.setItem(SELECTION_KEY, JSON.stringify({ project_id: 'proj:a', column: '不存在' }))
    const b = await openWorkItems(fake)
    expect(stationNames(b)).toEqual(BUILTIN)
    const lists = fake.to('/api/work-items').filter((c) => c.path === '/api/work-items')
    expect(lists.at(-1)!.query.column).toBe('开发中')
    await b.done()
  })

  it('点站切换列后，站点上的当前列与列表请求一致', async () => {
    const fake = createWiFake()
    withColumnsResponse(fake, () => json({ columns: ['待处理', '处理中'], default: '处理中' }))
    const b = await openWorkItems(fake)
    await clickTab(b, '看板列', '待处理')
    expect(selectedStation(b)).toBe('待处理')
    const lists = fake.to('/api/work-items').filter((c) => c.path === '/api/work-items')
    expect(lists.at(-1)!.query.column).toBe('待处理')
    await b.done()
  })
})

// ───────────────────────── 发布配置：命令选择器与预检请求体 ─────────────────────────

function releaseCfg(): ReleaseView {
  return {
    id: 'cfg-x',
    name: 'CG_Vue_Event',
    sort_order: 0,
    project_id: 'p1',
    repo_id: 'r1',
    repo_name: 'CG_Vue_Event',
    local_repo_path: '/repos/event',
    branches: [
      {
        id: 'b-main',
        build_branch: 'main',
        update_branches: ['main'],
        merges: [],
        push_branches: [],
      },
    ],
    warnings: [],
    targets: [
      { id: 'tg-1', name: 'Event 测试', enabled: true },
      { id: 'tg-2', name: 'Event 预发', enabled: true },
    ],
    commands: [
      cmd({ id: 'c-ok', name: '可选命令', target_ids: ['tg-1'] }),
      cmd({ id: 'c-running', name: '运行中命令', target_ids: ['tg-1'], active_run_id: 'run-7' }),
      cmd({ id: 'c-notarget', name: '无目标命令', target_ids: [] }),
      cmd({ id: 'c-off', name: '已停用命令', enabled: false, target_ids: ['tg-1'] }),
    ],
  }
}

function cmd(over: Partial<CommandView>): CommandView {
  return {
    id: 'c',
    name: '命令',
    enabled: true,
    sort_order: 0,
    tg_command: 'sync_build_event_test',
    tg_desc: '',
    branch_id: 'b-main',
    target_ids: [],
    active_run_id: null,
    last_run: null,
    ...over,
  } as CommandView
}

describe('发布配置：命令选择器的禁用原因', () => {
  async function mountPicker(config: ReleaseView) {
    const wrapper = mount(CommandPickerSheet, {
      attachTo: document.body,
      props: { open: true, config, operation: 'deploy_only' },
    })
    await flushPromises()
    return wrapper
  }
  const item = (id: string) =>
    document.querySelector<HTMLButtonElement>(`[data-testid="command-pick-${id}"]`)

  it('停用的命令不列出，并注明已隐藏几条', async () => {
    const w = await mountPicker(releaseCfg())
    expect(item('c-off')).toBeNull()
    expect(document.querySelector('[data-testid="command-picker"]')!.textContent).toContain(
      '另有 1 条已停用的命令没有列出',
    )
    w.unmount()
  })

  it('正在运行的命令禁用，并写明原因', async () => {
    const w = await mountPicker(releaseCfg())
    const running = item('c-running')!
    expect(running.disabled).toBe(true)
    expect(running.textContent).toContain('正在运行，等它结束后再选')
    w.unmount()
  })

  it('没有选发布目标的命令禁用，并写明去哪里补', async () => {
    const w = await mountPicker(releaseCfg())
    const notarget = item('c-notarget')!
    expect(notarget.disabled).toBe(true)
    expect(notarget.textContent).toContain('未选发布目标')
    expect(notarget.textContent).toContain('还没有选发布目标，先在“运行命令”里编辑它')
    w.unmount()
  })

  it('可选命令可点，点击只发出 pick 事件带命令本身；禁用的按钮点击不发事件', async () => {
    const w = await mountPicker(releaseCfg())
    expect(item('c-ok')!.disabled).toBe(false)
    expect(item('c-ok')!.textContent).toContain('main 分支，发布 Event 测试')
    item('c-running')!.click()
    item('c-notarget')!.click()
    expect(w.emitted('pick')).toBeUndefined()
    item('c-ok')!.click()
    const picked = w.emitted('pick')!
    expect(picked).toHaveLength(1)
    expect((picked[0]![0] as CommandView).id).toBe('c-ok')
    w.unmount()
  })

  it('没有任何可选命令时给出引导文案，不渲染列表', async () => {
    const cfg = releaseCfg()
    cfg.commands = [cmd({ id: 'only-off', enabled: false })]
    const w = await mountPicker(cfg)
    expect(document.querySelector('[data-testid="command-picker-empty"]')!.textContent).toContain(
      '这个配置还没有可用的运行命令',
    )
    expect(document.querySelector('.picker-list')).toBeNull()
    w.unmount()
  })
})

const PLAN = {
  plan_id: 'plan-1',
  revision: 7,
  task_summary: { id: 'cmd-1', name: 'CG_Vue_Event' },
  targets: [
    {
      target_index: 0,
      name: 'Event 测试',
      definition_id: 1,
      release_definition_id: 2,
      stage_ids: [1],
    },
  ],
  steps: [{ kind: 'release', target_index: 0 }],
  warnings: [],
  expires_at: '2026-10-23T10:05:00Z',
}

describe('发布配置：预检请求体不带目标字段', () => {
  it('选中命令后预检只带命令 id 相关的操作与版本，没有任何目标字段', async () => {
    const calls: { method: string; path: string; body: unknown }[] = []
    const cfg = releaseCfg()
    const fetchImpl = (async (input: Request) => {
      const url = new URL(input.url)
      const text = input.method === 'GET' ? '' : await input.clone().text()
      const body = text ? JSON.parse(text) : null
      calls.push({ method: input.method, path: url.pathname, body })
      if (url.pathname === '/health')
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      if (url.pathname === '/api/tasks') return json({ items: [], revision: 7 })
      if (url.pathname === '/api/release-configs') return json({ items: [cfg], revision: 7 })
      if (url.pathname === '/api/runs') return json({ items: [], cursor: null })
      if (/\/preflight$/.test(url.pathname)) return json(PLAN)
      return json({})
    }) as unknown as typeof fetch

    const b = await boot({ path: '/tasks', fetchImpl })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    await b.wrapper.get('[data-testid="run-task-btn"]').trigger('click')
    await flushPromises()
    document.querySelector<HTMLButtonElement>('[data-testid="command-pick-c-ok"]')!.click()
    await flushPromises()
    await flushPromises()

    const pre = calls.find((c) => c.path === '/api/tasks/c-ok/preflight')
    expect(pre, '预检请求发往所选命令').toBeTruthy()
    expect(pre!.body).toMatchObject({ operation: 'sync_build_release', revision: 7 })
    const keys = Object.keys(pre!.body as object)
    for (const k of keys) expect(k).not.toMatch(/target/i)
    await b.done()
  })
})

// ───────────────────────── 设置页：凭据时间、token 不外泄 ─────────────────────────

async function openSettingsTab(fake: ReturnType<typeof createFake>, label: string) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()
  const t = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith(label))
  expect(t, `tab ${label}`).toBeTruthy()
  await t!.trigger('mousedown')
  await flushPromises()
  await flushPromises()
  return b
}

describe('设置页：时间与 token 不外泄', () => {
  it('凭据表「更新于」显示本地 MM-DD HH:mm，不出现 ISO 原文', async () => {
    const fake = createFake()
    const b = await openSettingsTab(fake, '凭据')
    const text = b.wrapper.get('[data-testid=credentials-table]').text()
    const iso = makeCreds()[0]!.updated_at!
    expect(iso).toBe('2026-10-22T10:00:00Z')
    expect(text).not.toContain('2026-10-22T10:00:00Z')
    expect(text).not.toContain('T10:00:00')
    expect(text).toContain(localMMDDHHmm(iso))
    // 没有时间的凭据显示占位
    const row = b.wrapper.get('[data-testid="cred-ado_pat:lib:gone"]').text()
    expect(row).toContain('—')
    await b.done()
  })

  it('凭据表：接口多带的密钥字段不渲染到 DOM', async () => {
    const fake = createFake()
    const secret = 'fake-cred-VALUE-round3-0000'
    fake.state.creds = fake.state.creds.map((c) => ({ ...c, value: secret, secret })) as never
    const b = await openSettingsTab(fake, '凭据')
    expect(b.wrapper.get('[data-testid=credentials-table]').text()).toContain('ADO PAT')
    expect(document.documentElement.outerHTML).not.toContain(secret)
    await b.done()
  })

  it('Telegram 页：接口带的 Bot token 明文不渲染；最近活动时间本地化、不露 ISO 原文', async () => {
    const fake = createFake()
    const TOKEN = '123456789:FAKE-ROUND3-TOKEN-abcdefghijklmnopqrstuvwxyz'
    const ACT_ISO = '2026-10-23T10:15:00Z'
    fake.handlers.push((c) => {
      if (c.method === 'GET' && c.path === '/api/telegram') {
        return json({
          revision: 10,
          warnings: [],
          bot: {
            bot_id: '123456789',
            username: 'TestHelperBot',
            token: TOKEN,
            credential: { present: true, source: 'manual' },
          },
          control: { enabled: false, bot_id: '123456789', enabled_at: null },
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
        })
      }
      if (c.method === 'GET' && c.path === '/api/telegram/activity') {
        return json({
          items: [
            {
              received_at: ACT_ISO,
              kind: 'message',
              command: '/status',
              chat_id: '88888',
              status: 'handled',
              reason: null,
            },
          ],
        })
      }
      return undefined
    })
    const b = await openSettingsTab(fake, 'Telegram')
    await flushPromises()
    expect(b.wrapper.get('[data-testid="bot-username"]').text()).toBe('@TestHelperBot')
    expect(document.documentElement.outerHTML).not.toContain(TOKEN)
    expect(document.documentElement.outerHTML).not.toContain('FAKE-ROUND3-TOKEN')
    expect(document.documentElement.outerHTML).not.toContain(ACT_ISO)
    expect(document.body.textContent).toContain(localMMDDHHmm(ACT_ISO))
    await b.done()
  })
})
