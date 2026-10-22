import { flushPromises } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { FakeSocket, resetSeq } from './helpers'
import { boot } from './boot'

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
      expect(buttons.length).toBeGreaterThan(5)
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

  it('Tab 遍历顺序：导航 -> 工具栏 -> 表格行（tabindex=0）-> 状态栏按钮', async () => {
    const b = await boot()
    const focusables = Array.from(
      document.body.querySelectorAll<HTMLElement>(
        'a[href], button, input, select, textarea, [tabindex="0"]',
      ),
    ).filter((e) => !e.hasAttribute('disabled'))
    const idx = (sel: string) => focusables.findIndex((e) => e.matches(sel))
    const nav = idx('nav a[href="/tasks"]')
    const search = idx('input[type=search]')
    const add = idx('[data-testid=add-task]')
    const row = idx('tbody tr')
    const toggle = idx('[data-testid=inspector-toggle]')
    expect(nav).toBeGreaterThanOrEqual(0)
    expect(nav).toBeLessThan(search)
    expect(search).toBeLessThan(add)
    expect(add).toBeLessThan(row)
    expect(row).toBeLessThan(toggle)
    // 禁用的导航项不进入 Tab 序列
    expect(document.querySelector('[aria-disabled=true][tabindex]')).toBeNull()
    await b.done()
  })

  it('审批条在 Tab 序列里：三个按钮可聚焦', async () => {
    const b = await boot({ path: '/ai' })
    const bar = b.wrapper.get('[data-testid=approval-bar]')
    const btns = bar.findAll('button')
    expect(btns).toHaveLength(3)
    for (const x of btns) {
      ;(x.element as HTMLElement).focus()
      expect(document.activeElement).toBe(x.element)
    }
    await b.done()
  })

  it('可点击目标 >= 32px：按钮、图标按钮、导航项、页签、输入框的样式约定', () => {
    expect(src('components/AppButton.vue')).toMatch(/min-height:\s*var\(--target-min\)/)
    const ib = src('components/IconButton.vue')
    expect(ib).toMatch(/width:\s*var\(--target-min\)/)
    expect(ib).toMatch(/height:\s*var\(--target-min\)/)
    expect(src('components/SidebarNav.vue')).toMatch(/min-height:\s*var\(--target-min\)/)
    expect(src('components/AppTabs.vue')).toMatch(/min-height:\s*var\(--target-min\)/)
    expect(src('components/SearchBox.vue')).toMatch(/min-height:\s*var\(--target-min\)/)
    expect(src('components/TextInput.vue')).toMatch(/min-height:\s*var\(--target-min\)/)
    expect(src('components/ApprovalBar.vue')).toMatch(/min-height:\s*var\(--target-min\)/)
    expect(src('design/tokens.css')).toMatch(/--target-min:\s*32px/)
  })

  it('动效约定：只在运行中/待审批/告警使用；页面里没有其他 animation', () => {
    const files = [
      'components/StageBar.vue',
      'components/StatusDot.vue',
      'components/ApprovalBar.vue',
      'components/AlertBanner.vue',
      'design/ui.css',
    ]
    const used = files.flatMap((f) => (src(f).match(/animation:\s*([a-z-]+)/g) ?? []).map((m) => m))
    expect(
      used.filter((m) => !/none/.test(m)).every((m) => /flow|pulse|slidein|nudge/.test(m)),
    ).toBe(true)
    for (const f of ['features/tasks/TasksPage.vue', 'features/ai/AiSessionsPage.vue']) {
      expect(src(f)).not.toMatch(/animation:/)
    }
  })
})
