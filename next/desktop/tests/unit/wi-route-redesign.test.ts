// 方向 A「线路图」：工单页的看板列线路（列来自接口、条数来自已读列表）、详情站点线路、不折行的分页句子。
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, afterEach, describe, expect, it } from 'vitest'
import BoardLine from '@/features/work-items/BoardLine.vue'
import { FakeSocket, hello, resetSeq } from './helpers'
import { json } from './settings-fake'
import { createWiFake, detail, summary, type WiFake } from './wi-fake'
import { boot } from './boot'
import { clickTab, openRow, settle } from './wi-helpers'

let fake: WiFake
beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
  fake = createWiFake()
})
afterEach(() => {
  document.body.innerHTML = ''
})

// 接口给的看板列与默认列（和内置五列不同，证明线路以接口为准）
const COLS = ['待处理', '处理中', '验收', '完成']
function withColumns(f: WiFake) {
  const inner = f.fetch
  f.fetch = (async (input: Request) => {
    if (new URL(input.url).pathname === '/api/work-items/columns')
      return json({ columns: COLS, default: '处理中' })
    return (inner as (r: Request) => Promise<Response>)(input)
  }) as unknown as typeof fetch
}
async function open() {
  const b = await boot({ path: '/work-items', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  for (let i = 0; i < 4; i++) await flushPromises()
  return b
}

describe('看板列线路（列表顶部）', () => {
  it('站点就是接口返回的看板列；默认列取接口 default；当前站显示条数', async () => {
    withColumns(fake)
    fake.lists['proj:a|处理中'] = {
      items: [summary(1), summary(2)],
      truncated: false,
      omitted: 0,
    }
    const b = await open()
    const tabs = b.wrapper.get('[role=tablist][aria-label=看板列]').findAll('[role=tab]')
    expect(tabs.map((t) => t.text().replace(/\s+/g, ' '))).toEqual([
      '待处理',
      '处理中 2',
      '验收',
      '完成',
    ])
    expect(tabs[1]!.attributes('aria-selected')).toBe('true')
    expect(
      fake.to('/api/work-items').filter((c) => c.path === '/api/work-items')[0]!.query,
    ).toEqual({ project_id: 'proj:a', column: '处理中' })
    await b.done()
  })

  it('点站切换列；去过的列条数留在站点上，没去过的不猜数', async () => {
    withColumns(fake)
    fake.lists['proj:a|处理中'] = { items: [summary(1)], truncated: false, omitted: 0 }
    fake.lists['proj:a|验收'] = {
      items: [summary(5), summary(6), summary(7)],
      truncated: true,
      omitted: 0,
    }
    const b = await open()
    await clickTab(b, '看板列', '验收')
    await settle()
    const tabs = b.wrapper.get('[role=tablist][aria-label=看板列]').findAll('[role=tab]')
    expect(tabs.map((t) => t.text().replace(/\s+/g, ' '))).toEqual([
      '待处理',
      '处理中 1',
      '验收 3+',
      '完成',
    ])
    expect(tabs[2]!.attributes('aria-selected')).toBe('true')
    await b.done()
  })

  it('接口读不到看板列时退回内置五列', async () => {
    const b = await open()
    const tabs = b.wrapper.get('[role=tablist][aria-label=看板列]').findAll('[role=tab]')
    expect(tabs).toHaveLength(5)
    await b.done()
  })
})

describe('工单详情的站点线路与元信息', () => {
  it('已过的站实心、当前站带光晕、之后的站虚线灰', async () => {
    withColumns(fake)
    fake.lists['proj:a|处理中'] = { items: [summary(1)], truncated: false, omitted: 0 }
    fake.details[1] = detail(1, { board_column: '验收', priority: 1 })
    const b = await open()
    await openRow(b, 1)
    const stns = b.wrapper.findAll('section[aria-label=工单详情] .route .stn')
    expect(stns.map((s) => s.attributes('data-state'))).toEqual(['done', 'done', 'here', 'wait'])
    expect(stns[2]!.attributes('aria-current')).toBe('step')
    await b.done()
  })

  it('元信息用图标分隔，不用中点拼接；工具条有 AI 分析与在 ADO 打开', async () => {
    fake.lists['proj:a|开发中'] = { items: [summary(1)], truncated: false, omitted: 0 }
    fake.details[1] = detail(1, { priority: 1 })
    const b = await open()
    await openRow(b, 1)
    const meta = b.wrapper.get('[data-testid=wi-meta]')
    expect(meta.text()).not.toContain('·')
    expect(meta.findAll('svg').length).toBeGreaterThanOrEqual(4)
    expect(meta.text()).toContain('P1')
    expect(b.wrapper.get('[data-testid=ai-analysis-btn]').text()).toContain('AI 分析')
    expect(b.wrapper.get('[data-testid=open-web]').text()).toBe('在 ADO 打开')
    // 窄时次要操作进「⋯」
    const menu = b.wrapper.get('section[aria-label=工单详情] [role=menu]')
    expect(menu.find('[data-testid=copy-prompt-menu-item]').exists()).toBe(true)
    expect(menu.find('[data-testid=open-web-menu-item]').exists()).toBe(true)
    await b.done()
  })

  it('BoardLine：当前列不在站点里时不画线路', () => {
    const w = mount(BoardLine, { props: { columns: COLS, current: '不存在' } })
    expect(w.find('.route').exists()).toBe(false)
    const w2 = mount(BoardLine, { props: { columns: COLS, current: null } })
    expect(w2.find('.route').exists()).toBe(false)
  })
})

describe('分页句子', () => {
  it('写成不折行的正常句子，不用中点', async () => {
    fake.lists['proj:a|开发中'] = {
      items: Array.from({ length: 120 }, (_, i) => summary(1000 + i)),
      truncated: false,
      omitted: 0,
    }
    const b = await open()
    const info = b.wrapper.get('[data-testid=page-info]')
    expect(info.text()).toBe('第 1 / 3 页，共 120 条')
    expect(info.text()).not.toContain('·')
    await b.done()
  })
})
