import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ApprovalBar from '@/components/ApprovalBar.vue'
import { FakeSocket, resetSeq } from './helpers'
import { boot } from './boot'
import { createWiFake, summary } from './wi-fake'
import { openWi } from './wi-helpers'

const src = (p: string) => readFileSync(join(process.cwd(), 'src', p), 'utf8')

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('可访问性', () => {
  for (const path of ['/tasks', '/work-items', '/ai']) {
    it(`${path}：所有无文字的按钮都有 aria-label；可点击元素都是原生可聚焦元素`, async () => {
      const b = await boot({ path })
      await flushPromises()
      const buttons = b.wrapper.findAll('button')
      expect(buttons.length).toBeGreaterThan(path === '/tasks' ? 0 : 5)
      for (const btn of buttons) {
        const name = btn.attributes('aria-label') || btn.text().trim()
        expect(name, btn.html()).not.toBe('')
      }
      // 图标按钮（只含 svg）必须有 aria-label
      for (const btn of buttons.filter((x) => x.text().trim() === '')) {
        expect(btn.attributes('aria-label'), btn.html()).toBeTruthy()
      }
      await b.done()
    })
  }

  it('Tab 遍历顺序：侧栏导航 -> 列表搜索 -> 列表行 -> 顶栏检查器开关', async () => {
    const fake = createWiFake()
    fake.lists['proj:a|开发中'] = { items: [summary(1), summary(2)], truncated: false, omitted: 0 }
    const b = await openWi(fake)
    const focusables = Array.from(
      document.body.querySelectorAll<HTMLElement>(
        'a[href], button, input, select, textarea, [tabindex="0"]',
      ),
    ).filter((e) => !e.hasAttribute('disabled'))
    const idx = (sel: string) => focusables.findIndex((e) => e.matches(sel))
    const nav = idx('nav a[href="/tasks"]')
    const search = idx('input[type=search]')
    const row = idx('[data-testid=wi-row-1]')
    const toggle = idx('[data-testid=inspector-toggle]')
    expect(nav).toBeGreaterThanOrEqual(0)
    expect(nav).toBeLessThan(search)
    expect(search).toBeLessThan(row)
    expect(row).toBeLessThan(toggle)
    // 禁用的导航项不进入 Tab 序列
    expect(document.querySelector('[aria-disabled=true][tabindex]')).toBeNull()
    await b.done()
  })

  it('审批条在 Tab 序列里：三个按钮可聚焦', async () => {
    const w = mount(ApprovalBar, {
      props: { command: 'pnpm test' },
      attachTo: document.body,
    })
    const bar = w.get('[data-testid=approval-bar]')
    const btns = bar.findAll('button')
    expect(btns).toHaveLength(3)
    for (const x of btns) {
      ;(x.element as HTMLElement).focus()
      expect(document.activeElement).toBe(x.element)
    }
    w.unmount()
  })

  it('可点击目标 >= 28px：按钮、工具栏按钮、导航项、分段控件、输入框的样式约定', () => {
    expect(src('components/Button.vue')).toMatch(/min-height:\s*var\(--ctl-h\)/)
    expect(src('components/Button.vue')).toMatch(/min-width:\s*var\(--target-min\)/)
    const tb = src('components/ToolbarButton.vue')
    expect(tb).toMatch(/width:\s*var\(--target-min\)/)
    expect(tb).toMatch(/height:\s*var\(--ctl-h\)/)
    // 方向 A：导航项 32px 高，不低于 28px 的点击目标
    expect(src('components/Sidebar.vue')).toMatch(/min-height:\s*(var\(--ctl-h\)|3\d+px)/)
    expect(src('components/SegmentedControl.vue')).toMatch(/min-width:\s*var\(--target-min\)/)
    expect(src('components/SearchField.vue')).toMatch(/min-height:\s*var\(--ctl-h\)/)
    expect(src('components/TextField.vue')).toMatch(/min-height:\s*var\(--ctl-h\)/)
    expect(src('components/ApprovalBar.vue')).toMatch(/min-height:\s*var\(--ctl-h\)/)
    expect(src('design/tokens.css')).toMatch(/--target-min:\s*28px/)
    expect(src('design/tokens.css')).toMatch(/--ctl-h:\s*28px/)
  })

  it('动效约定：只有状态点运行中的脉冲与 Sheet 进出；prefers-reduced-motion 下全部关闭', () => {
    const files = ['components/StatusDot.vue', 'components/StatusPill.vue', 'components/Sheet.vue']
    const used = files.flatMap((f) => (src(f).match(/animation:\s*([a-z-]+)/g) ?? []).map((m) => m))
    expect(used.length).toBeGreaterThan(0)
    expect(used.every((m) => /pulse|sheet-in|sheet-out/.test(m))).toBe(true)
    for (const f of [
      'features/tasks/TasksPage.vue',
      'features/ai/AiSessionsPage.vue',
      'features/work-items/WorkItemsPage.vue',
      'components/ApprovalBar.vue',
      'components/Banner.vue',
    ]) {
      expect(src(f)).not.toMatch(/animation:/)
    }
    expect(src('design/ui.css')).toMatch(
      /prefers-reduced-motion: reduce\)\s*{[^]*animation: none !important/,
    )
  })
})
