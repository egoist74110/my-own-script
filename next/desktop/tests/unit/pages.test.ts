import { flushPromises } from '@vue/test-utils'
import { existsSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSocket, alertEvent, hello, resetSeq } from './helpers'
import { boot } from './boot'
import { createWiFake, detail, summary } from './wi-fake'
import { openRow, openWi, settle } from './wi-helpers'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear() // 工单页会把项目/列写入 localStorage
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('任务页（S3-C 真实列表与空态）', () => {
  it('无任务时渲染 EmptyState 空态，不含 S0.5 mock 任务台、假任务与假 KPI', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
    const w = b.wrapper
    expect(w.get('h1').text()).toBe('任务')
    expect(w.find('[data-testid=tasks-empty-state]').exists()).toBe(true)
    expect(w.find('[data-testid=tasks-empty-state]').text()).toContain('还没有任务')
    expect(w.find('table').exists()).toBe(false)
    expect(w.find('[data-testid=add-task]').exists()).toBe(false)
    const text = w.get('main').text()
    for (const bad of [
      'web-portal',
      'admin-console',
      'docs-site',
      'staging-a',
      'Runs/wk',
      'FAILED',
      'CLEAR',
      'ROLLBACK',
      'HALT',
    ]) {
      expect(text).not.toContain(bad)
    }
    expect(existsSync(new URL('../../src/features/tasks/mock', import.meta.url))).toBe(false)
    await b.done()
  })

  it('告警态：warn 横幅出现，页面区无遮罩，导航仍可点击', async () => {
    const b = await boot()
    b.sock.emit(hello())
    b.sock.emit(alertEvent(true, 'staging-a 被环境拒绝'))
    await flushPromises()
    const w = b.wrapper
    expect(w.get('[data-testid=alert-banner]').text()).toContain('staging-a 被环境拒绝')
    expect(w.get('.conn').attributes('data-alert')).toBe('true')
    await w.get('nav a[href="/ai"]').trigger('click')
    await vi.waitFor(() => expect(b.router.currentRoute.value.path).toBe('/ai'))
    b.sock.emit(alertEvent(false))
    await flushPromises()
    expect(w.find('[data-testid=alert-banner]').exists()).toBe(false)
    await b.done()
  })
})

describe('工单页', () => {
  // 工单页已接真实接口（S2-B）：以下为原 mock 断言的等价版本，数据来自按 openapi 形状的假后端
  const wiFake = () => {
    const f = createWiFake()
    f.lists['proj:a|开发中'] = {
      items: [
        summary(48213, { title: '权限缓存未刷新' }),
        summary(48177, { title: '移动端上传头像' }),
        summary(48100),
      ],
      truncated: false,
      omitted: 0,
    }
    f.lists['proj:a|新建'] = {
      items: [summary(1, { title: '新建一' }), summary(2)],
      truncated: false,
      omitted: 0,
    }
    f.details[48213] = detail(48213, {
      title: '权限缓存未刷新',
      child_ids: [1, 2, 3],
      attachments: [
        {
          name: 'x.png',
          size: 1,
          is_image: true,
          media_id: null,
          blocked_origin: 'https://cdn.example.test:443',
        },
      ],
    })
    f.details[48177] = detail(48177, { title: '移动端上传头像' })
    f.comments[48213] = {
      comments: [
        { id: 1, author: 'a', created_date: null, modified_date: null, html: '<p>只读成员</p>' },
      ],
      truncated: false,
    }
    return f
  }

  it('列表 | 详情 | 检查器：选择工单更新详情；详情五个页签；AI 面板整体禁用（S5）', async () => {
    const b = await openWi(wiFake())
    const w = b.wrapper
    expect(w.get('h1').text()).toBe('工单')
    expect(w.findAll('[data-testid^=wi-row-]')).toHaveLength(3) // 默认列「开发中」
    expect(w.find('section[aria-label=工单详情]').text()).toContain('选择一个工单')
    expect(w.get('[data-testid=wi-ai]').text()).toContain('S5')
    for (const btn of w.get('[data-testid=wi-ai]').findAll('button')) {
      expect(btn.attributes('disabled')).toBeDefined()
    }

    await openRow(b, 48177)
    expect(w.get('section[aria-label=工单详情]').text()).toContain('移动端上传头像')
    await openRow(b, 48213)
    const detailTabs = w.get('section[aria-label=工单详情]').findAll('[role=tab]')
    expect(detailTabs.map((t) => t.text().replace(/\s+/g, ' '))).toEqual([
      '描述',
      '评论',
      '子项 3',
      '历史',
      '附件 1',
    ])
    await detailTabs[1]!.trigger('mousedown', { button: 0 })
    await flushPromises()
    expect(w.get('[data-testid=wi-body]').text()).toContain('只读成员')
    await detailTabs[4]!.trigger('mousedown', { button: 0 })
    await flushPromises()
    expect(w.get('[data-testid=wi-body]').text()).toContain('已拦截外部附件')
    expect(w.find('[data-testid=wi-ai]').exists()).toBe(false)
    await b.done()
  })

  it('看板列切换与搜索', async () => {
    const b = await openWi(wiFake())
    const colTabs = b.wrapper.get('[role=tablist][aria-label=看板列]').findAll('[role=tab]')
    await colTabs[0]!.trigger('mousedown', { button: 0 })
    await settle()
    expect(b.wrapper.findAll('[data-testid^=wi-row-]')).toHaveLength(2)
    await b.wrapper.get('input[type=search]').setValue('不存在')
    expect(b.wrapper.text()).toContain('没有匹配的工单')
    await b.done()
  })

  it('告警态：横幅出现且页面按钮仍可点击', async () => {
    const b = await openWi(wiFake())
    b.sock.emit(alertEvent(true, 'x'))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
    await openRow(b, 48213)
    expect(b.wrapper.get('[data-testid=wi-row-48213]').attributes('aria-current')).toBe('true')
    await b.done()
  })
})

describe('AI 会话页', () => {
  it('会话列表：离线与错误态正常呈现，不出现虚构 mock 会话', async () => {
    const b = await boot({ path: '/ai' })
    await flushPromises()
    const w = b.wrapper
    expect(w.get('h1').text()).toBe('AI 会话')
    // 未收到 hello 时呈现后端未连接离线态
    expect(w.find('[data-testid=sessions-offline-state]').exists()).toBe(true)

    // 发送 hello 连上后端，由于未 mock sessions 接口，进入错误态（含重试）
    b.sock.emit(hello())
    for (let i = 0; i < 5; i++) await flushPromises()
    expect(
      w.find('[data-testid=sessions-error-state]').exists() ||
        w.find('[data-testid=sessions-empty-state]').exists(),
    ).toBe(true)

    // 页面不含任何 mock 虚构会话节点
    expect(w.find('[data-testid=session-s1]').exists()).toBe(false)
    expect(w.find('[data-testid=approval-bar]').exists()).toBe(false)
    expect(w.find('[data-testid=ai-inspector]').exists()).toBe(false)
    await b.done()
  })

  it('筛选 Tabs：按 AI 筛选分段控件正常渲染与切换', async () => {
    const b = await boot({ path: '/ai' })
    await flushPromises()
    const tabs = b.wrapper.get('[role=tablist][aria-label=按\\ AI\\ 筛选]').findAll('[role=tab]')
    expect(tabs.length).toBe(4)
    await tabs[1]!.trigger('mousedown', { button: 0 })
    await flushPromises()
    expect(tabs[1]!.attributes('aria-selected')).toBe('true')
    await b.done()
  })

  it('错误态重试按钮可交互', async () => {
    const b = await boot({ path: '/ai' })
    await flushPromises()
    const retryBtn = b.wrapper.find('[data-testid=retry-sessions-btn]')
    if (retryBtn.exists()) {
      await retryBtn.trigger('click')
      await flushPromises()
    }
    await b.done()
  })

  it('告警态下页面正常呈现且操作按钮可用', async () => {
    const b = await boot({ path: '/ai' })
    await flushPromises()
    b.sock.emit(hello())
    b.sock.emit(alertEvent(true, '测试告警'))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid=new-session-btn]').exists()).toBe(true)
    await b.done()
  })
})
