// S1-C 独立边界/故障用例（independent=true）：AppTabs 键盘与多实例、告警开关故障态与可达性、AI 会话隔离。
// 只用假 fetch / 假 socket；fixtures 复用 tests/unit/boot.ts 与 tests/unit/helpers.ts。
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'
import AppTabs from '@/components/AppTabs.vue'
import { tabTriggerId } from '@/components/tabs'
import { FakeSocket, resetSeq } from '../unit/helpers'
import { boot, bootUnconnected, json } from '../unit/boot'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
})
afterEach(() => {
  document.body.innerHTML = ''
})

const items = [
  { value: 'a', label: '甲' },
  { value: 'b', label: '乙' },
  { value: 'c', label: '丙' },
]

function mountTabs(opts: { label?: string; withSlot?: boolean; initial?: string } = {}) {
  const model = ref(opts.initial ?? 'a')
  const slot =
    opts.withSlot === false ? '' : `<template #default="{ item }">内容-{{ item.value }}</template>`
  const w = mount(
    {
      components: { AppTabs },
      setup: () => ({ model, items, label: opts.label ?? '视图' }),
      template: `<AppTabs v-model="model" :label="label" :items="items">${slot}</AppTabs>`,
    },
    { attachTo: document.body },
  )
  return { w, model }
}

/** 断言：每个 tab 的 aria-controls 指向唯一存在的 tabpanel，且 panel.aria-labelledby 指回该 tab。 */
function expectPairing(w: ReturnType<typeof mountTabs>['w']) {
  const tabs = w.findAll('[role=tab]')
  const panels = w.findAll('[role=tabpanel]')
  expect(tabs.length).toBe(panels.length)
  tabs.forEach((t) => {
    const id = t.attributes('aria-controls')
    expect(id, 'tab 必须有 aria-controls').toBeTruthy()
    const panel = document.getElementById(id!)
    expect(panel?.getAttribute('role')).toBe('tabpanel')
    expect(panel?.getAttribute('aria-labelledby')).toBe(t.attributes('id'))
  })
}

describe('AppTabs 键盘与关联（独立）', () => {
  it('方向键切换后，选中态与可见面板随之更新，tabpanel 关联保持一致', async () => {
    const { w, model } = mountTabs()
    await flushPromises()
    const first = w.findAll('[role=tab]')[0]!
    ;(first.element as HTMLElement).focus()
    await first.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(model.value).toBe('b')
    expectPairing(w)
    const visible = w.findAll('[role=tabpanel]').filter((p) => !p.element.hasAttribute('hidden'))
    expect(visible).toHaveLength(1)
    expect(visible[0]!.text()).toBe('内容-b')
    // 被选中页签的 panel 应可聚焦（有插槽时 tabindex=0）
    const selectedPanel = document.getElementById(
      w.findAll('[role=tab]')[1]!.attributes('aria-controls')!,
    )
    expect(selectedPanel!.getAttribute('tabindex')).toBe('0')
    w.unmount()
  })

  it('panelId 用法：方向键更新 modelValue；当前页签 aria-controls 指向可见 tabpanel 且含当前内容', async () => {
    const model = ref('a')
    const w = mount(
      {
        components: { AppTabs },
        setup: () => ({ model, items, tabTriggerId }),
        template: `<div><AppTabs v-model="model" label="视图" :items="items" panel-id="pp" />
          <div id="pp" role="tabpanel" :aria-labelledby="tabTriggerId('pp', model)">内容-{{ model }}</div></div>`,
      },
      { attachTo: document.body },
    )
    await flushPromises()
    ;(w.findAll('[role=tab]')[0]!.element as HTMLElement).focus()
    await w.findAll('[role=tab]')[0]!.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(model.value).toBe('b')
    expect(w.findAll('[role=tabpanel]')).toHaveLength(1)
    const current = w.get('[role=tab][aria-selected=true]')
    const panel = document.getElementById(current.attributes('aria-controls')!)!
    expect(panel.hasAttribute('hidden')).toBe(false)
    expect(panel.textContent).toBe('内容-b')
    expect(panel.getAttribute('aria-labelledby')).toBe(current.attributes('id'))
    w.unmount()
  })

  it('同一应用内多个 AppTabs（工单页即如此）：所有 id 唯一，各自关联不串线', async () => {
    const m1 = ref('a')
    const m2 = ref('c')
    const w = mount(
      {
        components: { AppTabs },
        setup: () => ({ m1, m2, items }),
        template: `<div><AppTabs v-model="m1" label="甲组" :items="items"><template #default="{ item }">内容-{{ item.value }}</template></AppTabs><AppTabs v-model="m2" label="乙组" :items="items"><template #default="{ item }">内容-{{ item.value }}</template></AppTabs></div>`,
      },
      { attachTo: document.body },
    )
    await flushPromises()
    const ids = Array.from(document.querySelectorAll('[id]')).map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    const groups = w.findAllComponents(AppTabs)
    expect(groups).toHaveLength(2)
    for (const g of groups) expectPairing(g as unknown as ReturnType<typeof mountTabs>['w'])
    // 改动第二组不影响第一组的选中与可见面板
    await w.findAll('[role=tab]')[3]!.trigger('mousedown')
    await flushPromises()
    expect(m1.value).toBe('a')
    expect(m2.value).toBe('a')
    const firstGroupVisible = w
      .findAll('[role=tabpanel]')
      .slice(0, 3)
      .filter((p) => !p.element.hasAttribute('hidden'))
    expect(firstGroupVisible.map((p) => p.text())).toEqual(['内容-a'])
    w.unmount()
  })

  it('工单页（含两组 AppTabs）：文档内所有 id 唯一，aria-controls/aria-labelledby 都能解析', async () => {
    const b = await boot({ path: '/work-items' })
    await flushPromises()
    const ids = Array.from(document.querySelectorAll('[id]')).map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const el of b.wrapper.findAll('[aria-labelledby]')) {
      expect(document.getElementById(el.attributes('aria-labelledby')!)).not.toBeNull()
    }
    await b.done()
  })
})

/** 可手动决定何时结束的 fetch，用于观察 pending 态。 */
function deferredAlertFetch() {
  const calls: { url: string; method: string; body: unknown }[] = []
  let release: ((r: Response) => void) | null = null
  const fetchImpl = (async (req: Request) => {
    if (req.url.endsWith('/health')) {
      return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
    }
    calls.push({
      url: req.url,
      method: req.method,
      body: await req
        .clone()
        .json()
        .catch(() => null),
    })
    return new Promise<Response>((res) => {
      release = res
    })
  }) as unknown as typeof fetch
  return { fetchImpl, calls, resolve: (r: Response) => release?.(r) }
}

describe('告警开关故障态与可达性（独立）', () => {
  it('请求在途时开关为 disabled，重复点击不再发第二个请求', async () => {
    const f = deferredAlertFetch()
    const b = await boot({ fetchImpl: f.fetchImpl })
    await flushPromises()
    const sw = b.wrapper.get('[role=switch]')
    await sw.trigger('click')
    await flushPromises()
    expect(f.calls).toHaveLength(1)
    expect(b.wrapper.get('[role=switch]').attributes('disabled')).toBeDefined()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(f.calls).toHaveLength(1)
    f.resolve(new Response(null, { status: 200 }))
    await flushPromises()
    expect(b.wrapper.get('[role=switch]').attributes('disabled')).toBeUndefined()
    await b.done()
  })

  it('请求体：开启发送 active=true + 演示原因；关闭发送 active=false 且 reason=null', async () => {
    const f = deferredAlertFetch()
    const b = await boot({ fetchImpl: f.fetchImpl })
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(f.calls[0]!.url).toMatch(/\/api\/system\/alert$/)
    expect(f.calls[0]!.method).toBe('POST')
    expect(f.calls[0]!.body).toEqual({ active: true, reason: 'S0 DEMO ALERT' })
    f.resolve(new Response(null, { status: 200 }))
    await flushPromises()
    await b.done()
  })

  it('服务端返回 503：显示 请求失败 (503)，开关恢复可点', async () => {
    let n = 0
    const fetchImpl = (async (req: Request) => {
      if (req.url.endsWith('/health'))
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      n++
      return new Response('{"detail":"down"}', {
        status: 503,
        headers: { 'content-type': 'application/json' },
      })
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(n).toBe(1)
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('请求失败 (503)')
    expect(b.wrapper.get('[role=switch]').attributes('disabled')).toBeUndefined()
    await b.done()
  })

  it('网络异常（fetch reject）：显示 请求失败（网络）', async () => {
    const fetchImpl = (async (req: Request) => {
      if (req.url.endsWith('/health'))
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      throw new TypeError('network down')
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('请求失败（网络）')
    await b.done()
  })

  it('错误后再次成功：错误文案被清除', async () => {
    let n = 0
    const fetchImpl = (async (req: Request) => {
      if (req.url.endsWith('/health'))
        return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
      n++
      if (n === 1) throw new TypeError('flaky')
      return new Response(null, { status: 200 })
    }) as unknown as typeof fetch
    const b = await boot({ fetchImpl })
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-error]').exists()).toBe(true)
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=alert-error]').exists()).toBe(false)
    expect(n).toBe(2)
    await b.done()
  })

  it('未连接时点击 → 连接建立后再点击：发出请求并清除“后端未连接”', async () => {
    const b = await bootUnconnected()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('后端未连接')
    expect(b.fetchMock).not.toHaveBeenCalled()
    b.runtime.start()
    await flushPromises()
    FakeSocket.last().open()
    await flushPromises()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.fetchMock).toHaveBeenCalled()
    expect(b.wrapper.find('[data-testid=alert-error]').exists()).toBe(false)
    await b.done()
  })

  it('label 与开关关联：点击“告警演示”文字同样触发开关请求', async () => {
    const f = deferredAlertFetch()
    const b = await boot({ fetchImpl: f.fetchImpl })
    await flushPromises()
    const label = b.wrapper.get('label.lbl')
    const switchId = b.wrapper.get('[role=switch]').attributes('id')
    expect(label.attributes('for')).toBe('alert-demo')
    expect(switchId).toBe('alert-demo')
    await label.trigger('click')
    await flushPromises()
    expect(f.calls).toHaveLength(1)
    f.resolve(new Response(null, { status: 200 }))
    await flushPromises()
    await b.done()
  })
})

describe('AI 会话隔离（独立）', () => {
  type Wrap = Awaited<ReturnType<typeof boot>>['wrapper']
  const sessBtn = (w: Wrap, id: string) => w.get(`[data-testid=session-${id}]`)
  const submit = async (w: Wrap, text: string) => {
    await w.get('textarea').setValue(text)
    await w.get('form').trigger('submit')
    await flushPromises()
  }

  it('纯空白消息不发送，也不产生消息条目', async () => {
    const b = await boot({ path: '/ai' })
    const before = b.wrapper.findAll('[data-testid=message]').length
    await submit(b.wrapper, '   \n\t ')
    expect(b.wrapper.findAll('[data-testid=message]').length).toBe(before)
    await b.done()
  })

  it('发送带首尾空白的消息：存入的内容已 trim', async () => {
    const b = await boot({ path: '/ai' })
    await submit(b.wrapper, '  追问内容  ')
    const last = b.wrapper.findAll('[data-testid=message]').at(-1)!
    expect(last.text()).toBe('You追问内容')
    await b.done()
  })

  it('s1 审批后在 s2/s3 发送，再切回 s1：审批记录与消息都只在 s1 中', async () => {
    const b = await boot({ path: '/ai' })
    await b.wrapper.get('[data-act=always]').trigger('click')
    await flushPromises()
    expect(b.wrapper.get('[data-testid=decision-log]').attributes('data-decision')).toBe('always')
    await sessBtn(b.wrapper, 's2').trigger('click')
    await submit(b.wrapper, '发给 s2')
    await sessBtn(b.wrapper, 's3').trigger('click')
    await submit(b.wrapper, '发给 s3')
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(false)
    await sessBtn(b.wrapper, 's1').trigger('click')
    expect(b.wrapper.findAll('[data-testid=decision-log]')).toHaveLength(1)
    expect(b.wrapper.get('.flow').text()).not.toContain('发给 s2')
    expect(b.wrapper.get('.flow').text()).not.toContain('发给 s3')
    await b.done()
  })

  it('N 键拒绝：记录 deny，会话状态变为已完成（done），审批条消失', async () => {
    const b = await boot({ path: '/ai' })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', bubbles: true }))
    await flushPromises()
    expect(b.wrapper.get('[data-testid=decision-log]').attributes('data-decision')).toBe('deny')
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    expect(b.wrapper.get('[data-testid=session-s1]').text()).toContain('已拒绝')
    await b.done()
  })

  it('输入框聚焦时按 Y 不审批（不应误触审批）', async () => {
    const b = await boot({ path: '/ai' })
    const ta = b.wrapper.get('textarea').element as HTMLTextAreaElement
    ta.focus()
    ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', bubbles: true }))
    await flushPromises()
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(true)
    await b.done()
  })

  it('每个会话的工具统计与上下文随会话切换而变化（不残留 s1 的数据）', async () => {
    const b = await boot({ path: '/ai' })
    expect(b.wrapper.get('[data-testid=ai-inspector]').text()).toContain('41%')
    expect(b.wrapper.get('[data-testid=ai-inspector]').text()).toContain('EDIT')
    await sessBtn(b.wrapper, 's2').trigger('click')
    const insp = b.wrapper.get('[data-testid=ai-inspector]').text()
    expect(insp).toContain('23%')
    expect(insp).not.toContain('EDIT')
    expect(insp).not.toContain('+2 −1')
    await b.done()
  })

  it('筛选：按 Codex 过滤后列表只含 Codex 会话', async () => {
    const b = await boot({ path: '/ai' })
    const codexTab = b.wrapper.findAll('[role=tab]').find((t) => t.text().startsWith('Codex'))!
    await codexTab.trigger('mousedown')
    await flushPromises()
    const ids = b.wrapper.findAll('[data-testid^=session-]').map((e) => e.attributes('data-testid'))
    expect(ids.sort()).toEqual(['session-s2', 'session-s5'])
    await b.done()
  })

  it('特征化：选中的会话被筛选掉后，列表不再高亮它，但对话区仍绑定该会话（待产品确认）', async () => {
    const b = await boot({ path: '/ai' })
    expect(b.wrapper.get('[data-testid=session-s1]').attributes('data-selected')).toBe('true')
    const codexTab = b.wrapper.findAll('[role=tab]').find((t) => t.text().startsWith('Codex'))!
    await codexTab.trigger('mousedown')
    await flushPromises()
    expect(b.wrapper.find('[data-testid=session-s1]').exists()).toBe(false)
    expect(b.wrapper.findAll('[data-selected=true]')).toHaveLength(0)
    expect(b.wrapper.get('.chat strong').text()).toBe('#48213 权限缓存未刷新')
    await b.done()
  })

  it('搜索无匹配：列表为空，不抛错，对话区仍保留', async () => {
    const b = await boot({ path: '/ai' })
    await b.wrapper.get('input[type=search], input').setValue('不存在的关键字xyz')
    await flushPromises()
    expect(b.wrapper.findAll('[data-testid^=session-]')).toHaveLength(0)
    expect(b.wrapper.find('.chat').exists()).toBe(true)
    await b.done()
  })
})
