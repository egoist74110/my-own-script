import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import AlertBanner from '@/components/AlertBanner.vue'
import AppButton from '@/components/AppButton.vue'
import AppTabs from '@/components/AppTabs.vue'
import ApprovalBar from '@/components/ApprovalBar.vue'
import BlockTag from '@/components/BlockTag.vue'
import EnergyBar from '@/components/EnergyBar.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import IconButton from '@/components/IconButton.vue'
import SearchBox from '@/components/SearchBox.vue'
import StageBar from '@/components/StageBar.vue'
import StampBadge from '@/components/StampBadge.vue'
import StatusDot from '@/components/StatusDot.vue'
import TextInput from '@/components/TextInput.vue'

afterEach(() => {
  document.body.innerHTML = ''
})

const press = (key: string, target: EventTarget = window, init: KeyboardEventInit = {}) =>
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }),
  )

describe('GlassPanel', () => {
  it('默认 12px 切角面板；cut=sm 为 6px；none 无切角；可换标签', () => {
    expect(mount(GlassPanel).classes()).toEqual(expect.arrayContaining(['glass', 'cut']))
    const sm = mount(GlassPanel, { props: { cut: 'sm' } })
    expect(sm.classes()).toContain('cut-xs')
    expect(sm.classes()).not.toContain('cut')
    const none = mount(GlassPanel, { props: { cut: 'none', as: 'section' } })
    expect(none.element.tagName).toBe('SECTION')
    expect(none.classes()).not.toContain('cut')
  })
})

describe('按钮', () => {
  it('变体 primary/accent/ghost，默认 type=button，点击触发', async () => {
    const onClick = vi.fn()
    const w = mount(AppButton, { slots: { default: 'GO' }, attrs: { onClick } })
    expect(w.attributes('data-variant')).toBe('primary')
    expect(w.attributes('type')).toBe('button')
    await w.trigger('click')
    expect(onClick).toHaveBeenCalledOnce()
    for (const v of ['accent', 'ghost'] as const) {
      expect(mount(AppButton, { props: { variant: v } }).attributes('data-variant')).toBe(v)
    }
  })
  it('图标按钮：aria-label 来自 label；最小尺寸约定 32px', () => {
    const w = mount(IconButton, { props: { label: '关闭' }, slots: { default: 'x' } })
    expect(w.attributes('aria-label')).toBe('关闭')
    expect(w.element.tagName).toBe('BUTTON')
  })
})

describe('输入框', () => {
  it('有不可见标签并双向绑定；多行变体用 textarea', async () => {
    const w = mount(TextInput, { props: { label: '名称', modelValue: '' } })
    expect(w.get('.sr-only').text()).toBe('名称')
    await w.get('input').setValue('abc')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['abc'])
    expect(
      mount(TextInput, { props: { label: 'm', multiline: true } })
        .find('textarea')
        .exists(),
    ).toBe(true)
  })
})

describe('⌘K 搜索框', () => {
  it('⌘K 与 Ctrl+K 聚焦，Esc 失焦，卸载后不再响应', async () => {
    const w = mount(SearchBox, { props: { label: '搜索' }, attachTo: document.body })
    const input = w.get('input').element
    press('k', window, { metaKey: true })
    expect(document.activeElement).toBe(input)
    ;(input as HTMLInputElement).blur()
    press('k', window, { ctrlKey: true })
    expect(document.activeElement).toBe(input)
    await w.get('input').trigger('keydown', { key: 'Escape' })
    expect(document.activeElement).not.toBe(input)
    w.unmount()
    press('k', window, { metaKey: true })
    expect(document.activeElement).not.toBe(input)
  })
  it('单独按 k 不聚焦', () => {
    const w = mount(SearchBox, { props: { label: '搜索' }, attachTo: document.body })
    press('k')
    expect(document.activeElement).not.toBe(w.get('input').element)
    w.unmount()
  })
})

describe('标签 / 印章 / 状态点', () => {
  it('黑色块标签与色调', () => {
    expect(mount(BlockTag, { slots: { default: '02' } }).classes()).toContain('blk')
    expect(mount(BlockTag, { props: { tone: 'acc' } }).attributes('data-tone')).toBe('acc')
  })
  it('结果印章三态', () => {
    const t = (r: 'clear' | 'failed' | 'rollback') =>
      mount(StampBadge, { props: { result: r } }).text()
    expect([t('clear'), t('failed'), t('rollback')]).toEqual(['CLEAR', 'FAILED', 'ROLLBACK'])
  })
  it('状态点四态，仅 run 带脉冲（由样式决定），装饰性 aria-hidden', () => {
    for (const s of ['ok', 'run', 'warn', 'idle'] as const) {
      const w = mount(StatusDot, { props: { state: s } })
      expect(w.attributes('data-state')).toBe(s)
      expect(w.attributes('aria-hidden')).toBe('true')
    }
  })
})

describe('阶段条', () => {
  it('四种状态；运行中段带流动斜纹类，其余不带；每段有可读标签', () => {
    const w = mount(StageBar, {
      props: {
        stages: [
          { code: 'SYNC', state: 'done' },
          { code: 'BUILD', state: 'run' },
          { code: 'REL', state: 'pending' },
          { code: 'REL', state: 'fail' },
        ],
      },
    })
    const segs = w.findAll('.seg')
    expect(segs.map((s) => s.attributes('data-state'))).toEqual(['done', 'run', 'pending', 'fail'])
    expect(segs.map((s) => s.classes().includes('chev'))).toEqual([false, true, false, false])
    expect(segs[1]!.attributes('aria-label')).toBe('BUILD 运行中')
    expect(segs[3]!.attributes('aria-label')).toBe('REL 失败')
  })
})

describe('能量条', () => {
  it('0..N 段点亮，越界被夹住', () => {
    const lit = (v: number, n = 10) =>
      mount(EnergyBar, { props: { value: v, segments: n, label: 'x' } }).findAll('[data-on=true]')
        .length
    expect([lit(0), lit(4), lit(10), lit(99), lit(-3)]).toEqual([0, 4, 10, 10, 0])
    const w = mount(EnergyBar, { props: { value: 3, segments: 5, label: '进度' } })
    expect(w.findAll('.cell')).toHaveLength(5)
    expect(w.attributes('role')).toBe('meter')
    expect(w.attributes('aria-valuenow')).toBe('3')
    expect(w.attributes('aria-valuemax')).toBe('5')
  })
})

describe('告警横幅', () => {
  it('role=alert，显示 reason，空 reason 给默认文案，不是遮罩', () => {
    const a = mount(AlertBanner, { props: { reason: 'boom' } })
    expect(a.attributes('role')).toBe('alert')
    expect(a.text()).toContain('WARNING')
    expect(a.text()).toContain('boom')
    expect(mount(AlertBanner, { props: { reason: null } }).text()).toContain('未提供原因')
    expect(a.element.className).not.toMatch(/fixed|overlay/)
  })
})

describe('斜切 Tabs', () => {
  function mountTabs() {
    const model = ref('a')
    const w = mount(
      {
        components: { AppTabs },
        setup: () => ({ model }),
        template: `<AppTabs v-model="model" label="视图" :items="[{value:'a',label:'甲',count:1},{value:'b',label:'乙'},{value:'c',label:'丙'}]" />`,
      },
      { attachTo: document.body },
    )
    return { w, model }
  }
  it('渲染 tablist 与三个 tab，选中态 data-state=active', () => {
    const { w } = mountTabs()
    expect(w.get('[role=tablist]').attributes('aria-label')).toBe('视图')
    const tabs = w.findAll('[role=tab]')
    expect(tabs).toHaveLength(3)
    expect(tabs[0]!.attributes('aria-selected')).toBe('true')
    expect(tabs[0]!.classes()).toContain('skew')
    w.unmount()
  })
  it('方向键切换（右/左/Home/End）', async () => {
    const { w, model } = mountTabs()
    await flushPromises() // Reka 的 roving focus 在挂载后的 post-flush 才注册键盘监听
    const tabs = () => w.findAll('[role=tab]')
    ;(tabs()[0]!.element as HTMLElement).focus()
    const key = async (i: number, k: string) => {
      await tabs()[i]!.trigger('keydown', { key: k })
      await flushPromises()
    }
    await key(0, 'ArrowRight')
    expect(model.value).toBe('b')
    expect(document.activeElement).toBe(tabs()[1]!.element)
    await key(1, 'ArrowRight')
    expect(model.value).toBe('c')
    await key(2, 'ArrowLeft')
    expect(model.value).toBe('b')
    await key(1, 'End')
    expect(model.value).toBe('c')
    await key(2, 'Home')
    expect(model.value).toBe('a')
    w.unmount()
  })
  it('点击切换', async () => {
    const { w, model } = mountTabs()
    await w.findAll('[role=tab]')[2]!.trigger('mousedown', { button: 0 })
    await w.findAll('[role=tab]')[2]!.trigger('click')
    await w.findAll('[role=tab]')[2]!.trigger('focus')
    expect(model.value).toBe('c')
    w.unmount()
  })
})

describe('审批条', () => {
  it('按钮点击发出 decide：once / always / deny', async () => {
    const w = mount(ApprovalBar, { props: { command: 'ls' } })
    const acts = w.findAll('button')
    expect(acts.map((b) => b.attributes('data-act'))).toEqual(['once', 'always', 'deny'])
    for (const b of acts) await b.trigger('click')
    expect(w.emitted('decide')).toEqual([['once'], ['always'], ['deny']])
    expect(w.text()).toContain('ls')
  })
  it('Y / A / N（不分大小写）触发对应 decide', () => {
    const w = mount(ApprovalBar, { props: { command: 'ls' }, attachTo: document.body })
    press('y')
    press('A')
    press('n')
    expect(w.emitted('decide')).toEqual([['once'], ['always'], ['deny']])
    w.unmount()
  })
  it('input / textarea / contenteditable 聚焦时不触发', () => {
    const w = mount(ApprovalBar, { props: { command: 'ls' }, attachTo: document.body })
    const input = document.createElement('input')
    const ta = document.createElement('textarea')
    const ce = document.createElement('div')
    ce.contentEditable = 'true'
    // jsdom 不实现 isContentEditable，补上以模拟浏览器
    Object.defineProperty(ce, 'isContentEditable', { value: true })
    document.body.append(input, ta, ce)
    for (const el of [input, ta, ce]) {
      el.focus()
      press('y', el)
      press('n', el)
    }
    expect(w.emitted('decide')).toBeUndefined()
    ;(document.activeElement as HTMLElement).blur()
    press('y')
    expect(w.emitted('decide')).toEqual([['once']])
    w.unmount()
  })
  it('带修饰键（⌘Y / Ctrl+A）不触发；卸载后不再监听', () => {
    const w = mount(ApprovalBar, { props: { command: 'ls' }, attachTo: document.body })
    press('y', window, { metaKey: true })
    press('a', window, { ctrlKey: true })
    expect(w.emitted('decide')).toBeUndefined()
    w.unmount()
    press('y')
    expect(w.emitted('decide')).toBeUndefined()
  })
  it('role=group 且有标签', () => {
    const w = mount(ApprovalBar, { props: { command: 'ls' } })
    expect(w.attributes('role')).toBe('group')
    expect(w.attributes('aria-label')).toBeTruthy()
  })
})
