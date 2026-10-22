import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { FakeSocket, alertEvent, hello, resetSeq } from './helpers'
import { boot } from './boot'
import { createWiFake, detail, summary } from './wi-fake'
import { openRow, openWi, settle } from './wi-helpers'

const press = (key: string, target: EventTarget = window) =>
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear() // 工单页会把项目/列写入 localStorage
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('任务页', () => {
  it('常态：工具栏、任务表（名称/目标/阶段条/状态/耗时/印章）、检查器、统计', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
    const w = b.wrapper
    expect(w.get('h1').text()).toBe('任务')
    expect(w.findAll('thead th').map((t) => t.text())).toEqual([
      '任务',
      '目标',
      '阶段',
      '状态',
      '耗时',
      '结果',
      '操作',
    ])
    expect(w.findAll('tbody tr')).toHaveLength(7)
    const r1 = w.get('[data-testid=task-row-t1]')
    expect(r1.findAll('.seg').map((s) => s.attributes('data-state'))).toEqual([
      'done',
      'run',
      'pending',
      'pending',
    ])
    expect(r1.text()).toContain('运行中')
    expect(r1.attributes('data-alert')).toBeUndefined()
    expect(w.get('[data-testid=task-row-t4]').text()).toContain('CLEAR')
    expect(w.get('[data-testid=task-row-t6]').text()).toContain('FAILED')
    expect(w.get('[data-testid=task-row-t7]').text()).toContain('ROLLBACK')
    // 检查器（经 Teleport 进入壳的检查器容器）
    const insp = w.get('[data-testid=inspector]')
    expect(insp.find('[data-testid=task-inspector]').exists()).toBe(true)
    expect(insp.text()).toContain('web-portal 发布')
    expect(insp.find('[role=log]').exists()).toBe(true)
    expect(insp.find('[role=meter]').exists()).toBe(true)
    expect(w.text()).toContain('Runs/wk')
    expect(w.find('[data-testid=task-inspector]').attributes('data-alert')).toBeUndefined()
    await b.done()
  })

  it('行可聚焦；Enter 与点击选中，检查器随之切换', async () => {
    const b = await boot()
    const rows = b.wrapper.findAll('tbody tr')
    expect(rows.every((r) => r.attributes('tabindex') === '0')).toBe(true)
    const r4 = b.wrapper.get('[data-testid=task-row-t4]')
    await r4.trigger('keydown', { key: 'Enter' })
    expect(r4.attributes('aria-selected')).toBe('true')
    expect(b.wrapper.get('[data-testid=task-inspector]').text()).toContain('admin-console 仅发布')
    await b.wrapper.get('[data-testid=task-row-t5]').trigger('click')
    expect(b.wrapper.get('[data-testid=task-inspector]').text()).toContain('docs-site 发布')
    expect(b.wrapper.get('[data-testid=task-row-t4]').attributes('aria-selected')).toBe('false')
    await b.done()
  })

  it('行内按钮点击不会改变选中行', async () => {
    const b = await boot()
    await b.wrapper
      .get('[data-testid=task-row-t3]')
      .find('button[aria-label=运行]')
      .trigger('click')
    expect(b.wrapper.get('[data-testid=task-row-t1]').attributes('aria-selected')).toBe('true')
    await b.done()
  })

  it('视图 Tabs 过滤；搜索过滤；⌘K 聚焦搜索框；新建任务追加一行', async () => {
    const b = await boot()
    const tabs = b.wrapper.findAll('[role=tab]')
    await tabs[1]!.trigger('mousedown', { button: 0 })
    await flushPromises()
    expect(b.wrapper.findAll('tbody tr')).toHaveLength(1)
    await tabs[0]!.trigger('mousedown', { button: 0 })
    await flushPromises()
    expect(b.wrapper.findAll('tbody tr')).toHaveLength(7)

    const input = b.wrapper.get('input[type=search]')
    press('k', window)
    expect(document.activeElement).not.toBe(input.element) // 无修饰键
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
    expect(document.activeElement).toBe(input.element)
    await input.setValue('docs')
    expect(b.wrapper.findAll('tbody tr')).toHaveLength(1)
    await input.setValue('')
    await b.wrapper.get('[data-testid=add-task]').trigger('click')
    expect(b.wrapper.findAll('tbody tr')).toHaveLength(8)
    expect(b.wrapper.get('[data-testid=task-summary]').text()).toContain('8 个任务')
    await b.done()
  })

  it('告警态：横幅、出错行、检查器带告警标记，导航角标 !；按钮仍可点击', async () => {
    const b = await boot()
    b.sock.emit(hello())
    await flushPromises()
    b.sock.emit(alertEvent(true, 'staging-a 被环境拒绝'))
    await flushPromises()
    const w = b.wrapper
    expect(w.get('[data-testid=alert-banner]').text()).toContain('staging-a 被环境拒绝')
    const row = w.get('[data-testid=task-row-t1]')
    expect(row.attributes('data-alert')).toBe('true')
    expect(row.text()).toContain('失败')
    expect(row.text()).toContain('FAILED')
    expect(row.findAll('.seg').map((s) => s.attributes('data-state'))).toContain('fail')
    // 其他行不受影响
    expect(w.findAll('tbody tr[data-alert=true]')).toHaveLength(1)
    expect(w.get('[data-testid=task-inspector]').attributes('data-alert')).toBe('true')
    expect(w.get('[data-testid=task-inspector]').text()).toContain('HALT')
    expect(w.get('[data-testid=nav-alert-badge]').text()).toBe('!')

    // 工作区仍可交互：按钮、行选择、键盘、⌘K
    await w.get('[data-testid=add-task]').trigger('click')
    expect(w.findAll('tbody tr')).toHaveLength(8)
    await w.get('[data-testid=task-row-t2]').trigger('click')
    expect(w.get('[data-testid=task-row-t2]').attributes('aria-selected')).toBe('true')
    expect(w.get('[data-testid=task-inspector]').attributes('data-alert')).toBeUndefined()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
    expect(document.activeElement).toBe(w.get('input[type=search]').element)

    b.sock.emit(alertEvent(false))
    await flushPromises()
    expect(w.find('tbody tr[data-alert=true]').exists()).toBe(false)
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
    for (const btn of w.get('[data-testid=wi-ai]').findAll('button')) {
      expect(btn.attributes('disabled')).toBeDefined()
    }
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
  it('会话列表 | 对话 + 审批条 | 检查器（上下文、工具调用统计）', async () => {
    const b = await boot({ path: '/ai' })
    const w = b.wrapper
    expect(w.get('h1').text()).toBe('AI 会话')
    expect(w.findAll('[data-testid^=session-]')).toHaveLength(6)
    expect(w.get('[data-testid=approval-bar]').text()).toContain('pnpm vitest run')
    const insp = w.get('[data-testid=ai-inspector]')
    expect(insp.text()).toContain('Context')
    expect(insp.text()).toContain('工具调用统计')
    expect(insp.find('[role=meter]').exists()).toBe(true)
    await b.done()
  })

  it('筛选 Tabs 按 AI 过滤会话', async () => {
    const b = await boot({ path: '/ai' })
    const tabs = b.wrapper.get('[role=tablist][aria-label=按\\ AI\\ 筛选]').findAll('[role=tab]')
    await tabs[2]!.trigger('mousedown', { button: 0 })
    await flushPromises()
    expect(b.wrapper.findAll('[data-testid^=session-]')).toHaveLength(2)
    await b.done()
  })

  it('审批快捷键 Y：改变 mock 状态（会话转运行中、审批条消失、记录一条决定）', async () => {
    const b = await boot({ path: '/ai' })
    press('y')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=decision-log]').text()).toContain('已允许一次')
    expect(b.wrapper.get('[data-testid=session-s1]').text()).toContain('运行中')
    // 已处理后再按键不会重复记录
    press('n')
    await flushPromises()
    expect(b.wrapper.findAll('[data-testid=decision-log]')).toHaveLength(1)
    await b.done()
  })

  it('审批快捷键 A / N 与按钮点击', async () => {
    const a = await boot({ path: '/ai' })
    press('a')
    await flushPromises()
    expect(a.wrapper.get('[data-testid=decision-log]').text()).toContain('本会话总是允许')
    await a.done()
    document.body.innerHTML = ''
    FakeSocket.reset()

    const n = await boot({ path: '/ai' })
    press('N')
    await flushPromises()
    expect(n.wrapper.get('[data-testid=decision-log]').text()).toContain('已拒绝')
    expect(n.wrapper.get('[data-testid=session-s1]').text()).toContain('已拒绝')
    await n.done()
    document.body.innerHTML = ''
    FakeSocket.reset()

    const c = await boot({ path: '/ai' })
    await c.wrapper.get('[data-act=once]').trigger('click')
    expect(c.wrapper.get('[data-testid=decision-log]').text()).toContain('已允许一次')
    await c.done()
  })

  it('输入框聚焦时 Y/A/N 不触发审批，并能正常输入', async () => {
    const b = await boot({ path: '/ai' })
    const ta = b.wrapper.get('textarea')
    ;(ta.element as HTMLTextAreaElement).focus()
    for (const k of ['y', 'a', 'n']) press(k, ta.element)
    await flushPromises()
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(false)
    await ta.setValue('继续')
    await b.wrapper.get('form').trigger('submit')
    expect(b.wrapper.text()).toContain('继续')
    await b.done()
  })

  it('告警态下审批条与按钮仍可用', async () => {
    const b = await boot({ path: '/ai' })
    b.sock.emit(hello())
    b.sock.emit(alertEvent(true, 'x'))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(true)
    press('y')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(true)
    await b.done()
  })

  it('选择别的会话时不显示审批条', async () => {
    const b = await boot({ path: '/ai' })
    await b.wrapper.get('[data-testid=session-s2]').trigger('click')
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    await b.done()
  })
})
