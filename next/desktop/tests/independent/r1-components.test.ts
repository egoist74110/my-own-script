// R1 独立验证：新组件行为（合同 R1 验收第 4 条）。从接口说明推导，不复用既有 components.test.ts 的写法。
import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import ListRow from '@/components/ListRow.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import Sheet from '@/components/Sheet.vue'
import StatusPill from '@/components/StatusPill.vue'
import type { PillState } from '@/components/pill'
import { INSPECTOR_KEY } from '@/stores/ui'

afterEach(() => {
  document.body.innerHTML = ''
  localStorage.clear()
  vi.restoreAllMocks()
})

const key = (el: Element | null, k: string, init: KeyboardEventInit = {}) =>
  el?.dispatchEvent(
    new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init }),
  )

describe('SegmentedControl', () => {
  const items = [
    { value: 'a', label: '甲', count: 3 },
    { value: 'b', label: '乙', count: 12 },
    { value: 'c', label: '丙' },
  ]

  /** 受控包装：用 v-model 语义把选中值放进 ref，便于断言。 */
  async function harness(orientation: 'horizontal' | 'vertical' = 'horizontal') {
    const value = ref('a')
    const wrapper = mount(
      defineComponent({
        setup: () => () =>
          h(SegmentedControl, {
            modelValue: value.value,
            'onUpdate:modelValue': (v: string) => (value.value = v),
            items,
            label: '分段测试',
            orientation,
          }),
      }),
      { attachTo: document.body },
    )
    // Reka 的 roving focus 项在挂载后的下一轮才注册；未等待就发键会被忽略（测试时序问题，非产品缺陷）
    await flushPromises()
    await flushPromises()
    const triggers = () => wrapper.findAll('[role=tab]')
    return { wrapper, value, triggers }
  }

  it('横向：左右方向键切换选中项，选中项同步到 v-model', async () => {
    const h1 = await harness('horizontal')
    ;(h1.triggers()[0]!.element as HTMLElement).focus()
    key(document.activeElement, 'ArrowRight')
    await flushPromises()
    expect(h1.value.value).toBe('b')
    key(document.activeElement, 'ArrowLeft')
    await flushPromises()
    expect(h1.value.value).toBe('a')
    h1.wrapper.unmount()
  })

  it('竖向：上下方向键切换；左右方向键不切换', async () => {
    const h1 = await harness('vertical')
    ;(h1.triggers()[0]!.element as HTMLElement).focus()
    key(document.activeElement, 'ArrowRight')
    await flushPromises()
    expect(h1.value.value).toBe('a')
    key(document.activeElement, 'ArrowDown')
    await flushPromises()
    expect(h1.value.value).toBe('b')
    h1.wrapper.unmount()
  })

  it('Home / End 跳到首尾项', async () => {
    const h1 = await harness('horizontal')
    ;(h1.triggers()[0]!.element as HTMLElement).focus()
    key(document.activeElement, 'End')
    await flushPromises()
    expect(h1.value.value).toBe('c')
    key(document.activeElement, 'Home')
    await flushPromises()
    expect(h1.value.value).toBe('a')
    h1.wrapper.unmount()
  })

  it('计数随项显示；没有 count 的项不显示计数', async () => {
    const h1 = await harness()
    const [t0, t1, t2] = h1.triggers()
    expect(t0!.text()).toContain('甲')
    expect(t0!.text()).toContain('3')
    expect(t1!.text()).toContain('12')
    expect(t2!.find('.count').exists()).toBe(false)
    h1.wrapper.unmount()
  })
})

describe('ListRow', () => {
  it('选中行带 aria-current="true" 与 data-selected；未选中行没有 aria-current', () => {
    const sel = mount(ListRow, { props: { title: '工单甲', meta: '08:00', selected: true } })
    expect(sel.attributes('aria-current')).toBe('true')
    expect(sel.attributes('data-selected')).toBe('true')
    const off = mount(ListRow, { props: { title: '工单乙', selected: false } })
    expect(off.attributes('aria-current')).toBeUndefined()
    expect(off.attributes('data-selected')).toBe('false')
  })

  it('选中态的强调底只在列表聚焦（.b-list:focus-within）时出现，未聚焦为灰底', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/design/ui.css'), 'utf8')
    // 聚焦：强调底 + 白字
    expect(css).toMatch(
      /\.b-list:focus-within\s+\.b-row\[data-selected='true'\]\s*\{[^}]*background:\s*var\(--row-sel-bg\)/,
    )
    // 未聚焦：默认选中行走灰底令牌（不是强调底）
    const base = css.match(/\.b-row\[data-selected='true'\]\s*\{([^}]*)\}/)
    expect(base, '未聚焦的选中行规则').toBeTruthy()
    expect(base![1]).toMatch(/var\(--sel-blur\)/)
    expect(base![1]).not.toMatch(/var\(--row-sel-bg\)/)
  })
})

describe('Sheet（Reka Dialog）', () => {
  it('open=true 时渲染 role=dialog，标题可见', async () => {
    mount(Sheet, {
      props: { open: true, title: '确认删除', description: '此操作不可撤销' },
      attachTo: document.body,
    })
    await flushPromises()
    const dlg = document.querySelector('[role=dialog]')
    expect(dlg).toBeTruthy()
    expect(dlg!.textContent).toContain('确认删除')
    expect(dlg!.textContent).toContain('此操作不可撤销')
  })

  it('Esc 关闭：发出 update:open=false', async () => {
    const onUpdate = vi.fn()
    mount(Sheet, {
      props: { open: true, title: '确认', 'onUpdate:open': onUpdate },
      attachTo: document.body,
    })
    await flushPromises()
    const dlg = document.querySelector('[role=dialog]') as HTMLElement
    key(dlg, 'Escape')
    await flushPromises()
    expect(onUpdate).toHaveBeenCalledWith(false)
  })

  it('焦点陷阱：打开后焦点在对话框内；把焦点移到外部按钮会被拉回对话框', async () => {
    const outside = document.createElement('button')
    outside.textContent = '外部'
    document.body.appendChild(outside)
    mount(Sheet, {
      props: { open: true, title: '确认', 'onUpdate:open': () => {} },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    const dlg = document.querySelector('[role=dialog]') as HTMLElement
    expect(dlg.contains(document.activeElement)).toBe(true)
    outside.focus()
    await flushPromises()
    expect(dlg.contains(document.activeElement)).toBe(true)
  })

  it('actions 插槽的按钮可点击', async () => {
    const onClick = vi.fn()
    mount(Sheet, {
      props: { open: true, title: '确认' },
      slots: { actions: () => h('button', { class: 'go', onClick }, '确定') },
      attachTo: document.body,
    })
    await flushPromises()
    ;(document.querySelector('.sheet .go') as HTMLButtonElement).click()
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})

describe('EmptyState', () => {
  it('动作插槽渲染并可点击；无动作插槽时不渲染动作区', async () => {
    const onAct = vi.fn()
    const w = mount(EmptyState, {
      props: { title: '没有项目', description: '请先添加' },
      slots: { actions: () => h('button', { class: 'act', onClick: onAct }, '前往设置') },
    })
    expect(w.get('h2').text()).toBe('没有项目')
    await w.get('.act').trigger('click')
    expect(onAct).toHaveBeenCalledTimes(1)

    const bare = mount(EmptyState, { props: { title: '空' } })
    expect(bare.find('.actions').exists()).toBe(false)
  })
})

describe('StatusPill 八态文案', () => {
  const EXPECT: Record<PillState, string> = {
    queued: '排队中',
    running: '运行中',
    stopping: '停止中',
    success: '成功',
    failed: '失败',
    cancelled: '已取消',
    verify: '需核实',
    disabled: '已停用',
  }
  for (const [state, text] of Object.entries(EXPECT) as [PillState, string][]) {
    it(`状态 ${state} 显示「${text}」且带 data-state`, () => {
      const w = mount(StatusPill, { props: { state } })
      expect(w.text()).toBe(text)
      expect(w.attributes('data-state')).toBe(state)
    })
  }
})

describe('Inspector 开关（InspectorToggle）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('aria-pressed 随开合变化，点击切换', async () => {
    const w = mount(InspectorToggle)
    const btn = w.get('[data-testid=inspector-toggle]')
    const before = btn.attributes('aria-pressed')
    await btn.trigger('click')
    expect(btn.attributes('aria-pressed')).not.toBe(before)
    await btn.trigger('click')
    expect(btn.attributes('aria-pressed')).toBe(before)
  })

  it('localStorage 键只存布尔字符串 true/false', async () => {
    const w = mount(InspectorToggle)
    await w.get('[data-testid=inspector-toggle]').trigger('click')
    const v1 = localStorage.getItem(INSPECTOR_KEY)
    expect(['true', 'false']).toContain(v1)
    await w.get('[data-testid=inspector-toggle]').trigger('click')
    const v2 = localStorage.getItem(INSPECTOR_KEY)
    expect(['true', 'false']).toContain(v2)
    expect(v1).not.toBe(v2)
  })

  it('存储抛错时不崩溃，开关仍可切换（内存态）', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    setActivePinia(createPinia())
    const w = mount(InspectorToggle)
    const btn = w.get('[data-testid=inspector-toggle]')
    const before = btn.attributes('aria-pressed')
    await expect(btn.trigger('click')).resolves.not.toThrow()
    expect(btn.attributes('aria-pressed')).not.toBe(before)
  })
})
