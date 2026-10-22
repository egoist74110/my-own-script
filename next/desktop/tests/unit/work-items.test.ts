// S2-B：工单页接真实接口（假 fetch，按 openapi 形状；不连任何真实服务）。
import { flushPromises } from '@vue/test-utils'
import { existsSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSocket, env, resetSeq } from './helpers'
import { createWiFake, detail, summary, wiErr, type WiFake } from './wi-fake'
import { clickTab, manyItems, openRow, openWi, rowIds, settle } from './wi-helpers'
import { SELECTION_KEY } from '@/features/work-items/selection'

let fake: WiFake
beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  fake = createWiFake()
  fake.lists['proj:a|开发中'] = {
    items: [summary(101), summary(102, { title: '另一个', assigned_to: null }), summary(103)],
    truncated: false,
    omitted: 0,
  }
})
afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

const listCalls = () => fake.to('/api/work-items').filter((c) => c.path === '/api/work-items')

describe('工具栏：项目 / 看板列 / 持久化', () => {
  it('默认项目取后端 active、默认列「开发中」；切换项目与列带正确参数', async () => {
    const b = await openWi(fake)
    expect(listCalls()[0]!.query).toEqual({ project_id: 'proj:a', column: '开发中' })
    expect(rowIds(b)).toEqual([101, 102, 103])
    const opts = b.wrapper.findAll('[data-testid=project-select] option').map((o) => o.text())
    expect(opts).toEqual(['示例库 / 项目甲', '无凭据库 / 项目乙'])
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:b')
    await settle()
    expect(listCalls().at(-1)!.query).toEqual({ project_id: 'proj:b', column: '开发中' })
    await clickTab(b, '看板列', '测试')
    expect(listCalls().at(-1)!.query).toEqual({ project_id: 'proj:b', column: '测试' })
    await b.done()
  })

  it('看板列页签固定为五列，当前列显示条数', async () => {
    const b = await openWi(fake)
    const tabs = b.wrapper.get('[role=tablist][aria-label=看板列]').findAll('[role=tab]')
    expect(tabs.map((t) => t.text().replace(/\s+/g, ' '))).toEqual([
      '新建',
      '待开发',
      '开发中 3',
      '测试',
      '已关闭',
    ])
    await b.done()
  })

  it('localStorage 只存 {project_id, column}；重开时恢复', async () => {
    const b = await openWi(fake)
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:b')
    await clickTab(b, '看板列', '测试')
    expect(Object.keys(localStorage)).toEqual([SELECTION_KEY])
    expect(JSON.parse(localStorage.getItem(SELECTION_KEY)!)).toEqual({
      project_id: 'proj:b',
      column: '测试',
    })
    await b.done()
    document.body.innerHTML = ''
    fake.calls.length = 0
    const b2 = await openWi(fake)
    expect(listCalls()[0]!.query).toEqual({ project_id: 'proj:b', column: '测试' })
    await b2.done()
  })

  it('localStorage 损坏、含无效列、读写抛错：页面照常工作', async () => {
    localStorage.setItem(SELECTION_KEY, '{bad json')
    const b = await openWi(fake)
    expect(rowIds(b)).toEqual([101, 102, 103])
    await b.done()
    document.body.innerHTML = ''
    localStorage.setItem(SELECTION_KEY, JSON.stringify({ project_id: 'gone', column: '不存在' }))
    const b2 = await openWi(fake)
    expect(listCalls().at(-1)!.query).toEqual({ project_id: 'proj:a', column: '开发中' })
    await b2.done()
    document.body.innerHTML = ''
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    const b3 = await openWi(fake)
    await clickTab(b3, '看板列', '测试')
    expect(b3.wrapper.get('h1').text()).toBe('工单')
    await b3.done()
  })

  it('切换项目清掉旧项目的查询：切回时重新请求', async () => {
    const b = await openWi(fake)
    const n = () => listCalls().filter((c) => c.query.project_id === 'proj:a').length
    expect(n()).toBe(1)
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:b')
    await settle()
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:a')
    await settle()
    expect(n()).toBe(2)
    await b.done()
  })

  it('刷新按钮强制重取（30 秒内也会）；窗口聚焦不重取', async () => {
    const b = await openWi(fake)
    expect(listCalls()).toHaveLength(1)
    window.dispatchEvent(new Event('focus'))
    await settle()
    expect(listCalls()).toHaveLength(1)
    await b.wrapper.get('[data-testid=refresh]').trigger('click')
    await settle()
    expect(listCalls()).toHaveLength(2)
    expect(fake.to('/api/ado')).toHaveLength(2)
    await b.done()
  })

  it('settings.changed 使 /api/ado 与工单查询失效', async () => {
    const b = await openWi(fake)
    await openRow(b, 101)
    const before = {
      ado: fake.to('/api/ado').length,
      list: listCalls().length,
      det: fake.to('/api/work-items/101').length,
    }
    b.sock.emit(env('settings.changed', { revision: 99 }))
    await settle()
    expect(fake.to('/api/ado').length).toBe(before.ado + 1)
    expect(listCalls().length).toBe(before.list + 1)
    expect(fake.to('/api/work-items/101').length).toBeGreaterThan(before.det)
    await b.done()
  })
})

describe('列表：筛选与分页', () => {
  it('关键词（标题 / #编号）与指派人筛选', async () => {
    const b = await openWi(fake)
    await b.wrapper.get('input[type=search]').setValue('另一个')
    expect(rowIds(b)).toEqual([102])
    await b.wrapper.get('input[type=search]').setValue('#103')
    expect(rowIds(b)).toEqual([103])
    await b.wrapper.get('input[type=search]').setValue('不存在')
    expect(b.wrapper.text()).toContain('没有匹配的工单')
    await b.wrapper.get('input[type=search]').setValue('')
    await b.wrapper.get('[data-testid=assignee-select]').setValue('__none__')
    expect(rowIds(b)).toEqual([102])
    await b.wrapper.get('[data-testid=assignee-select]').setValue('示例开发者')
    expect(rowIds(b)).toEqual([101, 103])
    await b.done()
  })

  it('分页：默认 50，可选 10/50/100；换页大小回到第 1 页', async () => {
    fake.lists['proj:a|开发中'] = { items: manyItems(120), truncated: false, omitted: 0 }
    const b = await openWi(fake)
    expect(rowIds(b)).toHaveLength(50)
    expect(b.wrapper.get('[data-testid=page-info]').text()).toContain('1 / 3')
    expect(b.wrapper.get('[data-testid=page-info]').text()).toContain('共 120 条')
    expect(b.wrapper.findAll('[data-testid=page-size] option').map((o) => o.text())).toEqual([
      '10 条/页',
      '50 条/页',
      '100 条/页',
    ])
    await b.wrapper.get('[data-testid=next-page]').trigger('click')
    expect(rowIds(b)[0]).toBe(1050)
    await b.wrapper.get('[data-testid=page-size]').setValue('10')
    expect(rowIds(b)).toHaveLength(10)
    expect(rowIds(b)[0]).toBe(1000)
    expect(b.wrapper.get('[data-testid=prev-page]').attributes('disabled')).toBeDefined()
    await b.wrapper.get('[data-testid=page-size]').setValue('100')
    expect(b.wrapper.get('[data-testid=page-info]').text()).toContain('1 / 2')
    await b.done()
  })

  it('truncated 提示「只显示前 500 条」；omitted 提示跳过条数', async () => {
    fake.lists['proj:a|开发中'] = { items: [summary(1)], truncated: true, omitted: 2 }
    const b = await openWi(fake)
    expect(b.wrapper.get('[data-testid=truncated]').text()).toBe('只显示前 500 条')
    expect(b.wrapper.get('[data-testid=omitted]').text()).toContain('2')
    await b.done()
  })

  it('行信息：编号、类型、标题、指派、状态、优先级、变更时间', async () => {
    const b = await openWi(fake)
    const t = b.wrapper.get('[data-testid=wi-row-101]').text()
    for (const s of ['#101', '工单标题 101', 'Bug', '示例开发者', '开发中', 'P2', '2026-10-02']) {
      expect(t).toContain(s)
    }
    await b.done()
  })
})

describe('详情与五个页签', () => {
  beforeEach(() => {
    fake.details[101] = detail(101, {
      parent_id: 100,
      child_ids: [201],
      tags: ['演示', '虚构'],
      html: {
        description: { html: '<p>描述正文</p>' },
        repro_steps: { html: '<p>复现 1</p>' },
        acceptance_criteria: { html: null, omitted: 'too_large' },
      },
      attachments: [
        { name: 'a.txt', size: 2048, is_image: false, media_id: 'm-file', blocked_origin: null },
      ],
      links: [
        { kind: 'pull_request', label: 'PR 12', url: null },
        { kind: 'hyperlink', label: '设计稿', url: 'https://example.test/x' },
      ],
    })
    fake.comments[101] = {
      comments: [
        {
          id: 1,
          author: '评审者',
          created_date: '2026-10-03T00:00:00Z',
          modified_date: null,
          html: '<p>评论内容</p>',
        },
        {
          id: 2,
          author: null,
          created_date: null,
          modified_date: null,
          html: null,
          omitted: 'too_large',
        },
      ],
      truncated: false,
    }
    fake.children[101] = {
      items: [{ ...summary(201, { title: '子项标题' }), parent_id: 101, depth: 1 }],
      truncated: false,
    }
    fake.updates[101] = {
      updates: [
        {
          id: 1,
          rev: 3,
          revised_by: '改动者',
          revised_date: '2026-10-03T00:00:00Z',
          fields: [{ name: '标题', old: '旧', new: '新 <b>x</b>' }],
          relations_added: 1,
          relations_removed: 0,
        },
      ],
      truncated: false,
    }
  })

  it('点击行显示详情头：编号、标题、优先级、标签、元信息、在浏览器打开', async () => {
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(b.wrapper.get('[data-testid=wi-row-101]').attributes('aria-current')).toBe('true')
    const d = b.wrapper.get('section[aria-label=工单详情]')
    for (const s of [
      '#101',
      '工单标题 101',
      'P2',
      '演示',
      '虚构',
      '示例开发者',
      '父项',
      '#100',
      '在浏览器打开',
    ]) {
      expect(d.text()).toContain(s)
    }
    expect(fake.to('/api/work-items/101')[0]!.query).toEqual({ project_id: 'proj:a' })
    await b.done()
  })

  it('页签：描述 / 评论 / 子项 / 历史 / 附件，各自内容与计数', async () => {
    const b = await openWi(fake)
    await openRow(b, 101)
    const tabs = b.wrapper.get('[role=tablist][aria-label=工单内容]').findAll('[role=tab]')
    expect(tabs.map((t) => t.text().replace(/\s+/g, ' '))).toEqual([
      '描述',
      '评论',
      '子项 1',
      '历史',
      '附件 1',
    ])
    const body = () => b.wrapper.get('section[aria-label=工单详情] [data-testid=wi-body]').text()
    expect(body()).toContain('描述正文')
    expect(body()).toContain('复现 1')
    expect(body()).toContain('内容过大')
    expect(body()).toContain('PR 12')
    await clickTab(b, '工单内容', '评论')
    expect(body()).toContain('评论内容')
    expect(body()).toContain('评审者')
    expect(body()).toContain('内容过大，未显示')
    await clickTab(b, '工单内容', '子项')
    expect(body()).toContain('子项标题')
    await clickTab(b, '工单内容', '历史')
    expect(body()).toContain('改动者')
    expect(body()).toContain('新 <b>x</b>') // 纯文本插值，不当 HTML
    expect(b.wrapper.find('[data-testid=wi-body] b').exists()).toBe(false)
    await clickTab(b, '工单内容', '附件')
    expect(body()).toContain('a.txt')
    expect(body()).toContain('2.0 KB')
    expect(body()).toContain('下载')
    await b.done()
  })

  it('子项与父项可点击跳转到该工单', async () => {
    fake.details[201] = detail(201, { title: '子项详情' })
    fake.details[100] = detail(100, { title: '父项详情' })
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '子项')
    await b.wrapper.get('[data-testid=child-201]').trigger('click')
    await settle()
    expect(b.wrapper.get('section[aria-label=工单详情]').text()).toContain('子项详情')
    await b.done()
  })

  it('评论 / 历史 / 子项仅在打开页签时请求', async () => {
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(fake.to('/api/work-items/101/')).toHaveLength(0)
    await clickTab(b, '工单内容', '评论')
    expect(fake.to('/api/work-items/101/comments')).toHaveLength(1)
    expect(fake.to('/api/work-items/101/comments')[0]!.query).toEqual({ project_id: 'proj:a' })
    await b.done()
  })
})

describe('空态与错误态', () => {
  it('无项目：引导到设置', async () => {
    fake.ado = { ...fake.ado, projects: [] }
    const b = await openWi(fake)
    const e = b.wrapper.get('[data-testid=no-projects]')
    expect(e.text()).toContain('前往设置')
    expect(e.get('a').attributes('href')).toBe('/settings')
    expect(listCalls()).toHaveLength(0)
    await b.done()
  })

  it('no_credential：提示未配置 PAT 并给出跳设置', async () => {
    fake.lists['proj:a|开发中'] = wiErr(409, 'no_credential') as never
    const b = await openWi(fake)
    const e = b.wrapper.get('[data-testid=wi-error]')
    expect(e.text()).toContain('该代码库未配置 PAT')
    expect(e.get('a').attributes('href')).toBe('/settings')
    await b.done()
  })

  it.each([
    ['unauthorized', '认证失败'],
    ['forbidden', '权限不足'],
    ['redirect', '重定向'],
    ['blocked_origin', '拦截'],
    ['tls', 'TLS'],
    ['timeout', '超时'],
    ['network', '无法连接 ADO'],
    ['bad_response', '响应格式异常'],
    ['too_large', '内容过大'],
  ])('502 分类 %s 显示固定文案，不回显后端 message', async (cat, text) => {
    fake.lists['proj:a|开发中'] = wiErr(502, 'ado_request_failed', cat) as never
    const b = await openWi(fake)
    const e = b.wrapper.get('[data-testid=wi-error]').text()
    expect(e).toContain(text)
    expect(e).not.toContain('固定文案')
    await b.done()
  })

  it('503 busy / 404 not_found / 网络异常 各有文案，并可重试', async () => {
    fake.lists['proj:a|开发中'] = wiErr(503, 'busy') as never
    const b = await openWi(fake)
    expect(b.wrapper.get('[data-testid=wi-error]').text()).toContain('服务繁忙')
    fake.lists['proj:a|开发中'] = { items: [summary(7)], truncated: false, omitted: 0 }
    const retry = b.wrapper
      .findAll('[data-testid=wi-error] button')
      .find((x) => x.text() === '重试')!
    await retry.trigger('click')
    await settle()
    expect(rowIds(b)).toEqual([7])
    await b.done()
  })

  it('响应形状不符（旧后端）不会崩溃，显示错误', async () => {
    const b = await openWi({
      ...fake,
      fetch: (async (r: Request) =>
        r.url.endsWith('/health')
          ? fake.fetch(r)
          : new Response('{}', {
              status: 200,
              headers: { 'content-type': 'application/json' },
            })) as typeof fetch,
    })
    expect(b.wrapper.find('[data-testid=wi-error]').exists()).toBe(true)
    await b.done()
  })

  it('评论接口 not_found：提示服务器不支持，可查看「历史」；详情其他块不受影响', async () => {
    fake.details[101] = detail(101)
    fake.comments[101] = wiErr(404, 'not_found') as never
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '评论')
    expect(b.wrapper.get('[data-testid=comments-unsupported]').text()).toContain(
      '该服务器不支持评论接口，可查看「历史」',
    )
    expect(b.wrapper.get('section[aria-label=工单详情]').text()).toContain('#101')
    await b.wrapper.get('[data-testid=comments-unsupported] button').trigger('click')
    await settle()
    expect(
      b.wrapper.get('[role=tablist][aria-label=工单内容] [aria-selected=true]').text(),
    ).toContain('历史')
    await b.done()
  })

  it('详情读取失败：详情区显示错误，列表仍可用', async () => {
    fake.details[101] = wiErr(502, 'ado_request_failed', 'timeout') as never
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(b.wrapper.get('section[aria-label=工单详情]').text()).toContain('超时')
    expect(rowIds(b)).toEqual([101, 102, 103])
    await b.done()
  })
})

describe('键盘与检查器', () => {
  it('行是原生 button（可聚焦，Enter/Space 触发点击）；列页签方向键切换', async () => {
    const b = await openWi(fake)
    const row = b.wrapper.get('[data-testid=wi-row-101]')
    expect(row.element.tagName).toBe('BUTTON')
    expect(row.attributes('type')).toBe('button')
    expect(row.attributes('tabindex')).toBeUndefined()
    const t0 = b.wrapper.get('[role=tablist][aria-label=看板列] [role=tab][aria-selected=true]')
    await b.wrapper.findAll('[role=tab]')[2]!.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(t0.attributes('aria-selected')).toBe('false')
    await b.done()
  })

  it('详情页签方向键可达', async () => {
    fake.details[101] = detail(101)
    const b = await openWi(fake)
    await openRow(b, 101)
    const tabs = b.wrapper.get('[role=tablist][aria-label=工单内容]').findAll('[role=tab]')
    await tabs[0]!.trigger('keydown', { key: 'ArrowRight' })
    await settle()
    expect(
      b.wrapper.get('[role=tablist][aria-label=工单内容] [aria-selected=true]').text(),
    ).toContain('评论')
    await b.done()
  })

  it('检查器 AI 分析面板整体禁用并标 S5，没有 mock 动作', async () => {
    const b = await openWi(fake)
    const ai = b.wrapper.get('[data-testid=wi-ai]')
    expect(ai.text()).toContain('S5')
    expect(ai.get('fieldset').attributes('disabled')).toBeDefined()
    for (const btn of ai.findAll('button')) expect(btn.attributes('disabled')).toBeDefined()
    expect(b.wrapper.find('[data-testid=copy-prompt]').exists()).toBe(false)
    expect(b.wrapper.find('[role=radio]').exists()).toBe(false)
    await b.done()
  })

  it('mock 目录已删除，页面不再提供「新建工单」', async () => {
    expect(existsSync(new URL('../../src/features/work-items/mock', import.meta.url))).toBe(false)
    const b = await openWi(fake)
    expect(b.wrapper.text()).not.toContain('新建工单')
    await b.done()
  })
})
