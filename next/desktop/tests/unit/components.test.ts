import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { Inbox } from 'lucide-vue-next'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { inspectorHostKey } from '@/app/inspector'
import ApprovalBar from '@/components/ApprovalBar.vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import ConnectionStatus from '@/components/ConnectionStatus.vue'
import EmptyState from '@/components/EmptyState.vue'
import Inspector from '@/components/Inspector.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import ListRow from '@/components/ListRow.vue'
import Pane from '@/components/Pane.vue'
import SearchField from '@/components/SearchField.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import Sheet from '@/components/Sheet.vue'
import Skeleton from '@/components/Skeleton.vue'
import StatusDot from '@/components/StatusDot.vue'
import StatusPill from '@/components/StatusPill.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import ToolbarButton from '@/components/ToolbarButton.vue'
import { PILL_LABEL, type PillState } from '@/components/pill'
import type { ConnectionState } from '@/api/events'
import { useBackendStore } from '@/stores/backend'
import { INSPECTOR_KEY } from '@/stores/ui'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})
afterEach(() => {
  document.body.innerHTML = ''
})

const press = (key: string, target: EventTarget = window, init: KeyboardEventInit = {}) =>
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }),
  )

describe('Pane / Button / ToolbarButton', () => {
  it('Pane 是纯色面：可换标签与底色，不带玻璃或切角类', () => {
    const w = mount(Pane, { props: { as: 'section', surface: 'inspector' } })
    expect(w.element.tagName).toBe('SECTION')
    expect(w.attributes('data-surface')).toBe('inspector')
    expect(w.classes()).not.toEqual(expect.arrayContaining(['glass']))
    expect(w.classes().join(' ')).not.toMatch(/cut|glass/)
  })
  it('Button 变体 primary/default/destructive/plain，默认 type=button，点击触发', async () => {
    const onClick = vi.fn()
    const w = mount(Button, { slots: { default: 'GO' }, attrs: { onClick } })
    expect(w.attributes('data-variant')).toBe('default')
    expect(w.attributes('type')).toBe('button')
    await w.trigger('click')
    expect(onClick).toHaveBeenCalledOnce()
    for (const v of ['primary', 'destructive', 'plain'] as const) {
      expect(mount(Button, { props: { variant: v } }).attributes('data-variant')).toBe(v)
    }
  })
  it('ToolbarButton：aria-label 来自 label，pressed 映射 aria-pressed', () => {
    const w = mount(ToolbarButton, {
      props: { label: '检查器', pressed: true },
      slots: { default: 'x' },
    })
    expect(w.attributes('aria-label')).toBe('检查器')
    expect(w.attributes('aria-pressed')).toBe('true')
    expect(w.element.tagName).toBe('BUTTON')
  })
})

describe('TextField', () => {
  it('有不可见标签并双向绑定；多行变体用 textarea', async () => {
    const w = mount(TextField, { props: { label: '名称', modelValue: '' } })
    expect(w.get('.sr-only').text()).toBe('名称')
    await w.get('input').setValue('abc')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['abc'])
    expect(
      mount(TextField, { props: { label: 'm', multiline: true } })
        .find('textarea')
        .exists(),
    ).toBe(true)
  })
})

describe('SearchField（⌘K / Ctrl+K）', () => {
  it('⌘K 与 Ctrl+K 聚焦，Esc 失焦，卸载后不再响应', async () => {
    const w = mount(SearchField, { props: { label: '搜索' }, attachTo: document.body })
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
    const w = mount(SearchField, { props: { label: '搜索' }, attachTo: document.body })
    press('k')
    expect(document.activeElement).not.toBe(w.get('input').element)
    w.unmount()
  })
})

describe('Tag / StatusDot / StatusPill', () => {
  it('Tag 是中性小标签，tone 只改色', () => {
    expect(mount(Tag, { slots: { default: 'SSO' } }).text()).toBe('SSO')
    expect(mount(Tag, { props: { tone: 'warn' } }).attributes('data-tone')).toBe('warn')
  })
  it('状态点四态，装饰性 aria-hidden', () => {
    for (const s of ['ok', 'run', 'warn', 'idle'] as const) {
      const w = mount(StatusDot, { props: { state: s } })
      expect(w.attributes('data-state')).toBe(s)
      expect(w.attributes('aria-hidden')).toBe('true')
    }
  })
  it('StatusPill 八态文案', () => {
    const states: PillState[] = [
      'queued',
      'running',
      'stopping',
      'success',
      'failed',
      'cancelled',
      'verify',
      'disabled',
    ]
    expect(states.map((s) => mount(StatusPill, { props: { state: s } }).text())).toEqual([
      '排队中',
      '运行中',
      '停止中',
      '成功',
      '失败',
      '已取消',
      '需核实',
      '已停用',
    ])
    expect(Object.keys(PILL_LABEL)).toHaveLength(8)
    expect(mount(StatusPill, { props: { state: 'running' } }).attributes('data-state')).toBe(
      'running',
    )
  })
})

describe('Banner', () => {
  it('info/warn/error：info 默认 role=status，warn/error 默认 role=alert，可覆盖；不是遮罩', () => {
    expect(mount(Banner, { props: { kind: 'info' } }).attributes('role')).toBe('status')
    expect(mount(Banner, { props: { kind: 'warn' } }).attributes('role')).toBe('alert')
    expect(mount(Banner, { props: { kind: 'error' } }).attributes('role')).toBe('alert')
    const w = mount(Banner, {
      props: { kind: 'warn', title: '标题' },
      attrs: { role: 'status', 'data-testid': 'x' },
      slots: { default: '正文', actions: '<button>重试</button>' },
    })
    expect(w.attributes('role')).toBe('status')
    expect(w.attributes('data-testid')).toBe('x')
    expect(w.text()).toContain('标题')
    expect(w.text()).toContain('正文')
    expect(w.text()).toContain('重试')
    expect(w.element.className).not.toMatch(/fixed|overlay/)
  })
})

describe('EmptyState / Skeleton', () => {
  it('EmptyState：图标 + 标题 + 说明 + 动作', async () => {
    const onClick = vi.fn()
    const w = mount(EmptyState, {
      props: { title: '没有项目', description: '先去设置', icon: Inbox },
      slots: { actions: () => h(Button, { onClick }, () => '去设置') },
    })
    expect(w.get('h2').text()).toBe('没有项目')
    expect(w.text()).toContain('先去设置')
    expect(w.find('svg').exists()).toBe(true)
    await w.get('button').trigger('click')
    expect(onClick).toHaveBeenCalledOnce()
  })
  it('Skeleton：按行数渲染且对读屏隐藏', () => {
    const w = mount(Skeleton, { props: { rows: 3 } })
    expect(w.findAll('.sk-row')).toHaveLength(3)
    expect(w.attributes('aria-hidden')).toBe('true')
  })
})

describe('SegmentedControl', () => {
  function mountSeg(orientation: 'horizontal' | 'vertical' = 'horizontal') {
    const model = ref('a')
    const w = mount(
      {
        components: { SegmentedControl },
        setup: () => ({ model, orientation }),
        template: `<SegmentedControl v-model="model" label="视图" :orientation="orientation" :items="[{value:'a',label:'甲',count:1},{value:'b',label:'乙'},{value:'c',label:'丙'}]" />`,
      },
      { attachTo: document.body },
    )
    return { w, model }
  }
  it('渲染 tablist 与三个 tab，选中态 aria-selected，带计数', () => {
    const { w } = mountSeg()
    expect(w.get('[role=tablist]').attributes('aria-label')).toBe('视图')
    const tabs = w.findAll('[role=tab]')
    expect(tabs).toHaveLength(3)
    expect(tabs[0]!.attributes('aria-selected')).toBe('true')
    expect(tabs[0]!.text().replace(/\s+/g, ' ')).toBe('甲 1')
    expect(w.get('[role=tablist]').attributes('aria-orientation')).not.toBe('vertical')
    w.unmount()
  })
  it('横向：方向键 右/左/Home/End 切换', async () => {
    const { w, model } = mountSeg()
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
  it('竖向：上下方向键切换（orientation=vertical）', async () => {
    const { w, model } = mountSeg('vertical')
    await flushPromises()
    expect(w.get('[role=tablist]').attributes('aria-orientation')).toBe('vertical')
    const tabs = () => w.findAll('[role=tab]')
    ;(tabs()[0]!.element as HTMLElement).focus()
    await tabs()[0]!.trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()
    expect(model.value).toBe('b')
    await tabs()[1]!.trigger('keydown', { key: 'ArrowUp' })
    await flushPromises()
    expect(model.value).toBe('a')
    w.unmount()
  })
  it('点击切换', async () => {
    const { w, model } = mountSeg()
    await w.findAll('[role=tab]')[2]!.trigger('mousedown', { button: 0 })
    await w.findAll('[role=tab]')[2]!.trigger('click')
    await w.findAll('[role=tab]')[2]!.trigger('focus')
    expect(model.value).toBe('c')
    w.unmount()
  })
})

describe('ListRow', () => {
  it('两行：标题 + 日期 + 次行插槽；选中带 aria-current 与 data-selected', () => {
    const w = mount(ListRow, {
      props: { title: '标题', meta: '10-01', dot: 'red', selected: true },
      slots: { default: '#1 · Bug' },
    })
    expect(w.text()).toContain('标题')
    expect(w.text()).toContain('10-01')
    expect(w.text()).toContain('#1 · Bug')
    expect(w.attributes('aria-current')).toBe('true')
    expect(w.attributes('data-selected')).toBe('true')
    const off = mount(ListRow, { props: { title: 't' } })
    expect(off.attributes('aria-current')).toBeUndefined()
    expect(off.attributes('data-selected')).toBe('false')
  })
  it('选中聚焦=强调底白字、选中未聚焦=灰底：由容器 :focus-within 区分（样式契约）', () => {
    const css = readFileSync(join(process.cwd(), 'src/design/ui.css'), 'utf8')
    expect(css).toMatch(/\.b-row\[data-selected='true'\]\s*\{[^}]*var\(--sel-blur\)/)
    expect(css).toMatch(
      /\.b-list:focus-within \.b-row\[data-selected='true'\]\s*\{[^}]*var\(--row-sel-bg\)[^}]*var\(--row-sel-fg\)/,
    )
  })
  it('在 .b-list 里聚焦行：焦点在容器内（focus-within 成立）', () => {
    const w = mount(
      {
        components: { ListRow },
        template: '<ul class="b-list"><li><ListRow title="a" selected /></li></ul>',
      },
      { attachTo: document.body },
    )
    const btn = w.get('button').element as HTMLButtonElement
    btn.focus()
    expect(document.activeElement).toBe(btn)
    expect(w.get('.b-list').element.matches(':focus-within')).toBe(true)
    btn.blur()
    expect(w.get('.b-list').element.matches(':focus-within')).toBe(false)
    w.unmount()
  })
})

describe('Sheet（确认单）', () => {
  function mountSheet() {
    const open = ref(true)
    const onOk = vi.fn()
    const w = mount(
      defineComponent({
        setup: () => () =>
          h('div', [
            h('button', { id: 'opener', onClick: () => (open.value = true) }, '打开'),
            h(
              Sheet,
              {
                open: open.value,
                'onUpdate:open': (v: boolean) => (open.value = v),
                title: '确认删除',
                description: '不可撤销',
              },
              {
                default: () => h('p', '正文'),
                actions: () => [
                  h('button', { id: 'cancel', onClick: () => (open.value = false) }, '取消'),
                  h('button', { id: 'ok', onClick: onOk }, '删除'),
                ],
              },
            ),
          ]),
      }),
      { attachTo: document.body },
    )
    return { w, open, onOk }
  }
  it('打开时渲染对话框（标题/说明/动作），Esc 关闭', async () => {
    const { w, open } = mountSheet()
    await nextTick()
    await flushPromises()
    const dlg = document.body.querySelector('[role=dialog]') as HTMLElement
    expect(dlg).toBeTruthy()
    expect(dlg.textContent).toContain('确认删除')
    expect(dlg.textContent).toContain('不可撤销')
    expect(dlg.querySelector('#ok')).toBeTruthy()
    dlg.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(open.value).toBe(false)
    w.unmount()
  })
  it('焦点陷阱：打开后焦点进入对话框，Tab 不会跑到对话框外', async () => {
    const { w } = mountSheet()
    await flushPromises()
    const dlg = document.body.querySelector('[role=dialog]') as HTMLElement
    expect(dlg.contains(document.activeElement)).toBe(true)
    const inside = Array.from(dlg.querySelectorAll<HTMLElement>('button'))
    for (let i = 0; i < inside.length + 2; i++) {
      document.activeElement?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }),
      )
      await flushPromises()
      expect(dlg.contains(document.activeElement)).toBe(true)
    }
    // 对话框外的按钮被 aria-hidden 隔离
    expect(document.body.querySelector('#opener')!.closest('[aria-hidden=true]')).toBeTruthy()
    w.unmount()
  })
})

describe('Inspector / InspectorToggle', () => {
  function mountWithHost(withToggle = true) {
    const host = document.createElement('div')
    document.body.append(host)
    const w = mount(
      defineComponent({
        setup: () => () =>
          h('div', [
            withToggle ? h(InspectorToggle) : null,
            h(Inspector, { label: '测试检查器' }, () => h('p', { id: 'content' }, '内容')),
          ]),
      }),
      { attachTo: document.body, global: { provide: { [inspectorHostKey as symbol]: ref(host) } } },
    )
    return { w, host }
  }
  it('Inspector 经 Teleport 进入壳容器，region 带标签', async () => {
    const { w, host } = mountWithHost()
    await flushPromises()
    expect(host.querySelector('#content')).toBeTruthy()
    expect(host.querySelector('[role=region]')!.getAttribute('aria-label')).toBe('测试检查器')
    w.unmount()
  })
  it('开关：aria-pressed + aria-label 随状态变化；localStorage 只存布尔值', async () => {
    const { w } = mountWithHost()
    const btn = () => w.get('[data-testid=inspector-toggle]')
    expect(btn().attributes('aria-pressed')).toBe('true')
    expect(btn().attributes('aria-label')).toBe('收起检查器')
    await btn().trigger('click')
    expect(btn().attributes('aria-pressed')).toBe('false')
    expect(btn().attributes('aria-label')).toBe('展开检查器')
    expect(localStorage.getItem(INSPECTOR_KEY)).toBe('false')
    await btn().trigger('click')
    expect(localStorage.getItem(INSPECTOR_KEY)).toBe('true')
    expect(Object.keys(localStorage)).toEqual([INSPECTOR_KEY])
    w.unmount()
  })
  it('读取：localStorage 为 false 时初始收起；存储抛错时回退为展开', async () => {
    localStorage.setItem(INSPECTOR_KEY, 'false')
    setActivePinia(createPinia())
    const a = mountWithHost()
    expect(a.w.get('[data-testid=inspector-toggle]').attributes('aria-pressed')).toBe('false')
    a.w.unmount()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    setActivePinia(createPinia())
    const b = mountWithHost()
    expect(b.w.get('[data-testid=inspector-toggle]').attributes('aria-pressed')).toBe('true')
    await b.w.get('[data-testid=inspector-toggle]').trigger('click')
    expect(b.w.get('[data-testid=inspector-toggle]').attributes('aria-pressed')).toBe('false')
    b.w.unmount()
  })
})

describe('ConnectionStatus', () => {
  const queryClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function mountConn(post = vi.fn(async () => ({ response: { ok: true, status: 200 } }))) {
    const get = vi.fn(async () => ({ data: { version: '1.2.3' } }))
    const runtime = { api: () => ({ POST: post, GET: get }) }
    const w = mount(ConnectionStatus, {
      attachTo: document.body,
      global: {
        plugins: [[VueQueryPlugin, { queryClient: queryClient() }]],
        provide: { [backendRuntimeKey as symbol]: runtime },
      },
    })
    return { w, post, store: useBackendStore() }
  }
  it('四种连接态文案；告警时状态行变橙（data-alert）', async () => {
    const { w, store } = mountConn()
    const label = () => w.get('[data-testid=connection]').text()
    const cases: [ConnectionState, string][] = [
      ['connecting', '连接中'],
      ['online', '在线'],
      ['reconnecting', '重连中'],
      ['offline', '离线'],
    ]
    for (const [state, text] of cases) {
      store.setConnection(state)
      await nextTick()
      expect(label()).toContain(text)
      expect(w.get('[data-testid=connection] > span').attributes('data-state')).toBe(state)
    }
    expect(w.attributes('data-alert')).toBe('false')
    store.applyEvent({
      seq: 5,
      topic: 'system',
      type: 'system.alert',
      ts: 't',
      data: { active: true, reason: 'r', changed_at: 't' },
    })
    await nextTick()
    expect(w.attributes('data-alert')).toBe('true')
    w.unmount()
  })
  it('按钮：aria-haspopup/aria-expanded；弹出层显示 pid 与心跳延迟（无数据显示 —）', async () => {
    const { w, store } = mountConn()
    const trigger = w.get('[data-testid=connection-trigger]')
    expect(trigger.element.tagName).toBe('BUTTON')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-testid=connection-popover]').exists()).toBe(false)
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(w.get('[data-testid=connection-pid]').text()).toBe('—')
    store.pid = 99
    store.setConnection('online')
    store.setLatency(12.4)
    await nextTick()
    expect(w.get('[data-testid=connection-pid]').text()).toBe('99')
    expect(w.get('[data-testid=connection-latency]').text()).toBe('12 ms')
    w.unmount()
  })
  it('告警演示开关只发 POST /api/system/alert，不本地切换告警态', async () => {
    const { w, post, store } = mountConn()
    await w.get('[data-testid=connection-trigger]').trigger('click')
    await w.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledWith('/api/system/alert', {
      body: { active: true, reason: 'S0 DEMO ALERT' },
    })
    expect(store.alert.active).toBe(false)
    expect(w.get('[role=switch]').attributes('aria-checked')).toBe('false')
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
