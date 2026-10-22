// S1-C：S0/S0.5 前端遗留修复（CR-S05-001..005、S0B-007、S0B-008）。
import { flushPromises, mount } from '@vue/test-utils'
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'
import AppTabs from '@/components/AppTabs.vue'
import { tabTriggerId } from '@/components/tabs'
import { scan } from '../../scripts/forbidden-scan.mjs'
import { FakeSocket, resetSeq } from './helpers'
import { boot, bootUnconnected } from './boot'

const src = (p: string) => readFileSync(join(process.cwd(), 'src', p), 'utf8')
const pkg = JSON.parse(readFileSync(join(process.cwd(), 'package.json'), 'utf8')) as {
  scripts: Record<string, string>
}

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('CR-S05-001：未取得连接时的告警开关', () => {
  it('点击开关：零请求，显示“后端未连接”，告警态不变', async () => {
    const b = await bootUnconnected()
    expect(b.runtime.api()).toBeNull()
    await b.wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(b.fetchMock).not.toHaveBeenCalled()
    expect(FakeSocket.instances).toHaveLength(0)
    expect(b.wrapper.get('[data-testid=alert-error]').text()).toBe('后端未连接')
    expect(b.wrapper.get('[role=switch]').attributes('aria-checked')).toBe('false')
    expect(b.wrapper.find('[data-testid=alert-banner]').exists()).toBe(false)
    await b.done()
  })
})

describe('CR-S05-002：告警开关点击目标 >= 32px', () => {
  it('Switch 视觉 20px 不变，AlertToggle 用 --target-min 把命中区扩到 32px（开关与标签）', () => {
    expect(src('components/ui/switch/Switch.vue')).toMatch(/\bh-5\b/)
    const t = src('components/AlertToggle.vue')
    expect(t).toMatch(/class="hit"/)
    expect(t).toMatch(/\.hit::after\s*{[^}]*position:\s*absolute[^}]*var\(--target-min\)/s)
    expect(t).toMatch(/\.lbl\s*{[^}]*min-height:\s*var\(--target-min\)/s)
    expect(src('design/tokens.css')).toMatch(/--target-min:\s*32px/)
  })
  it('挂载后开关带 hit 类', async () => {
    const b = await boot()
    expect(b.wrapper.get('[role=switch]').classes()).toContain('hit')
    await b.done()
  })
})

describe('CR-S05-003：AppTabs tabpanel 关联', () => {
  const items = [
    { value: 'a', label: '甲' },
    { value: 'b', label: '乙' },
  ]
  function mountTabs(withSlot: boolean) {
    const model = ref('a')
    const slot = withSlot ? `<template #default="{ item }">内容-{{ item.value }}</template>` : ''
    const w = mount(
      {
        components: { AppTabs },
        setup: () => ({ model, items }),
        template: `<AppTabs v-model="model" label="视图" :items="items">${slot}</AppTabs>`,
      },
      { attachTo: document.body },
    )
    return { w, model }
  }

  it('有插槽：tab 的 aria-controls 指向 tabpanel，panel 的 aria-labelledby 指回 tab，仅当前面板显示', async () => {
    const { w, model } = mountTabs(true)
    await flushPromises()
    const tabs = w.findAll('[role=tab]')
    const panels = w.findAll('[role=tabpanel]')
    expect(panels).toHaveLength(2)
    tabs.forEach((t, i) => {
      const panel = document.getElementById(t.attributes('aria-controls')!)
      expect(panel, 'aria-controls 必须指向存在的元素').toBe(panels[i]!.element)
      expect(panels[i]!.attributes('aria-labelledby')).toBe(t.attributes('id'))
    })
    expect(panels[0]!.attributes('hidden')).toBeUndefined()
    expect(panels[0]!.text()).toBe('内容-a')
    expect(panels[1]!.attributes('hidden')).toBeDefined()
    model.value = 'b'
    await flushPromises()
    expect(w.findAll('[role=tabpanel]')[1]!.text()).toBe('内容-b')
    expect(w.findAll('[role=tabpanel]')[1]!.attributes('hidden')).toBeUndefined()
    expect(w.findAll('[role=tabpanel]')[0]!.attributes('hidden')).toBeDefined()
    w.unmount()
  })

  it('panelId（筛选型）：不渲染内部空面板；aria-controls 指向页面容器，容器是可见的 tabpanel 且含当前内容', async () => {
    const model = ref('a')
    const w = mount(
      {
        components: { AppTabs },
        setup: () => ({ model, items, tabTriggerId }),
        template: `<div><AppTabs v-model="model" label="视图" :items="items" panel-id="pp" />
          <div id="pp" role="tabpanel" :aria-labelledby="tabTriggerId('pp', model)"><p>列表-{{ model }}</p></div></div>`,
      },
      { attachTo: document.body },
    )
    await flushPromises()
    expect(w.findAll('[data-testid=tab-panel]')).toHaveLength(0)
    expect(w.findAll('[role=tabpanel]')).toHaveLength(1)
    for (const t of w.findAll('[role=tab]')) expect(t.attributes('aria-controls')).toBe('pp')
    for (const v of ['a', 'b']) {
      model.value = v
      await flushPromises()
      const current = w.get('[role=tab][aria-selected=true]')
      const panel = document.getElementById(current.attributes('aria-controls')!)!
      expect(panel.hasAttribute('hidden')).toBe(false)
      expect(panel.textContent).toContain(`列表-${v}`)
      expect(panel.getAttribute('aria-labelledby')).toBe(current.attributes('id'))
    }
    w.unmount()
  })

  for (const path of ['/tasks', '/work-items', '/ai']) {
    it(`${path}：页面里所有 aria-controls 都指向存在的元素`, async () => {
      const b = await boot({ path })
      await flushPromises()
      const controlled = b.wrapper.findAll('[aria-controls]')
      expect(controlled.length).toBeGreaterThan(0)
      for (const el of controlled) {
        expect(document.getElementById(el.attributes('aria-controls')!)).not.toBeNull()
      }
      await b.done()
    })
  }

  // 页面级：当前页签 aria-controls 解析到的元素可见，包含当前真实内容，并由当前页签标注
  const pageCases: [string, string, string, string][] = [
    ['/tasks', '视图', 'task-row-t1', '运行中'],
    ['/work-items', '看板列', 'wi-row-48213', '测试中'],
    ['/ai', '按 AI 筛选', 'session-s1', 'Claude'],
  ]
  for (const [path, label, testid, other] of pageCases) {
    it(`${path}：「${label}」当前页签的 aria-controls 指向可见、含真实内容的 tabpanel（切换后仍成立）`, async () => {
      const b = await boot({ path })
      await flushPromises()
      const list = b.wrapper.get(`[role=tablist][aria-label="${label}"]`)
      const check = () => {
        const current = list.get('[role=tab][aria-selected=true]')
        const panel = document.getElementById(current.attributes('aria-controls')!)
        expect(panel, 'aria-controls 目标存在').not.toBeNull()
        expect(panel!.getAttribute('role')).toBe('tabpanel')
        expect(panel!.hasAttribute('hidden')).toBe(false)
        expect(panel!.getAttribute('aria-labelledby')).toBe(current.attributes('id'))
        return panel!
      }
      const first = check()
      expect(first.querySelector(`[data-testid="${testid}"]`)).not.toBeNull()
      const next = list.findAll('[role=tab]').find((t) => t.text().includes(other))
      expect(next, `存在页签 ${other}`).toBeTruthy()
      await next!.trigger('mousedown')
      await flushPromises()
      const panel = check()
      expect(panel.textContent!.length).toBeGreaterThan(0)
      await b.done()
    })
  }

  it('/work-items 详情页签：面板是真实 tabpanel，显示当前页签的真实内容', async () => {
    const b = await boot({ path: '/work-items' })
    await flushPromises()
    const list = b.wrapper.get('[role=tablist][aria-label="工单内容"]')
    const current = list.get('[role=tab][aria-selected=true]')
    const panel = document.getElementById(current.attributes('aria-controls')!)!
    expect(panel.getAttribute('role')).toBe('tabpanel')
    expect(panel.hasAttribute('hidden')).toBe(false)
    expect(panel.querySelector('[data-testid=wi-body]')).not.toBeNull()
    const comments = list.findAll('[role=tab]').find((t) => t.text().includes('评论'))!
    await comments.trigger('mousedown')
    await flushPromises()
    const cur = list.get('[role=tab][aria-selected=true]')
    const p2 = document.getElementById(cur.attributes('aria-controls')!)!
    expect(p2.hasAttribute('hidden')).toBe(false)
    expect(p2.textContent).toContain('只读成员')
    await b.done()
  })
})

describe('CR-S05-004：AI 会话对话内容在 mock 层', () => {
  it('页面源码不含对话文案；mock 提供，并经 useAiSessions() 取', async () => {
    const page = src('features/ai/AiSessionsPage.vue')
    for (const text of ['usePermissions', '工单 #48213', 'queryKey', 'READ']) {
      expect(page).not.toContain(text)
    }
    const mock = src('features/ai/mock/sessions.ts')
    expect(mock).toContain('usePermissions')
    expect(mock).toContain('export function useAiSessions')
    const b = await boot({ path: '/ai' })
    expect(b.wrapper.get('.flow').text()).toContain('usePermissions')
    expect(b.wrapper.get('.flow').text()).toContain('分析工单')
    await b.done()
  })
  it('每个会话有自己的对话，不再都显示 s1 的内容', async () => {
    const b = await boot({ path: '/ai' })
    await b.wrapper.get('[data-testid=session-s2]').trigger('click')
    const flow = b.wrapper.get('.flow').text()
    expect(flow).toContain('网关各层的超时配置')
    expect(flow).not.toContain('usePermissions')
    await b.done()
  })
})

describe('CR-S05-005：sent 与审批记录按会话 id 隔离', () => {
  const sessionBtn = (b: Awaited<ReturnType<typeof boot>>, id: string) =>
    b.wrapper.get(`[data-testid=session-${id}]`)
  async function sendMsg(b: Awaited<ReturnType<typeof boot>>, text: string) {
    await b.wrapper.get('textarea').setValue(text)
    await b.wrapper.get('form').trigger('submit')
    await flushPromises()
  }

  it('发送的消息只属于当前会话，切走不残留，切回仍在', async () => {
    const b = await boot({ path: '/ai' })
    await sendMsg(b, '只给 s1 的追问')
    expect(b.wrapper.get('.flow').text()).toContain('只给 s1 的追问')
    await sessionBtn(b, 's2').trigger('click')
    expect(b.wrapper.get('.flow').text()).not.toContain('只给 s1 的追问')
    await sendMsg(b, '只给 s2 的追问')
    await sessionBtn(b, 's1').trigger('click')
    expect(b.wrapper.get('.flow').text()).toContain('只给 s1 的追问')
    expect(b.wrapper.get('.flow').text()).not.toContain('只给 s2 的追问')
    await b.done()
  })

  it('审批记录只属于 s1；切到别的会话不显示，切回仍在；审批条不再出现', async () => {
    const b = await boot({ path: '/ai' })
    await b.wrapper.get('[data-act=once]').trigger('click')
    expect(b.wrapper.findAll('[data-testid=decision-log]')).toHaveLength(1)
    await sessionBtn(b, 's2').trigger('click')
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    await sessionBtn(b, 's1').trigger('click')
    expect(b.wrapper.findAll('[data-testid=decision-log]')).toHaveLength(1)
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(false)
    await b.done()
  })

  it('在非审批会话按 Y 不产生任何记录', async () => {
    const b = await boot({ path: '/ai' })
    await sessionBtn(b, 's3').trigger('click')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', bubbles: true }))
    await flushPromises()
    await sessionBtn(b, 's1').trigger('click')
    expect(b.wrapper.find('[data-testid=decision-log]').exists()).toBe(false)
    expect(b.wrapper.find('[data-testid=approval-bar]').exists()).toBe(true)
    await b.done()
  })
})

describe('S0B-007：test 不依赖 dist，dist 检查在 guard:dist', () => {
  it('package.json 提供 guard:dist；test 脚本不含 dist', () => {
    expect(pkg.scripts['guard:dist']).toBe('node scripts/guard-dist.mjs')
    expect(pkg.scripts.test).not.toMatch(/dist/)
    const guard = readFileSync(join(process.cwd(), 'scripts/guard-dist.mjs'), 'utf8')
    expect(guard).toContain("from './forbidden-scan.mjs'")
    expect(guard).toMatch(/process\.exit\(1\)/)
  })
  it('禁词集合未缩减', () => {
    const dir = mkdtempSync(join(tmpdir(), 'guard-'))
    mkdirSync(join(dir, 'assets'))
    for (const [i, w] of [
      'Rhine',
      'RHINE',
      'Arknights',
      '莱茵',
      'fonts.googleapis.com',
    ].entries()) {
      writeFileSync(join(dir, 'assets', `f${i}.js`), `ok\nx ${w} y\n`)
    }
    writeFileSync(join(dir, 'assets', 'clean.js'), 'nothing here')
    writeFileSync(join(dir, 'assets', 'bin.woff2'), Buffer.from([0, 82, 104, 105, 110, 101]))
    const hits = scan(dir)
    expect(hits).toHaveLength(5)
    expect(hits.every((h) => h.endsWith(':2'))).toBe(true)
  })
  it('测试文件不再读取 dist/', () => {
    const files: string[] = []
    const walk = (d: string) =>
      readdirSync(d).forEach((n) => {
        const p = join(d, n)
        if (statSync(p).isDirectory()) walk(p)
        else if (p.endsWith('.test.ts') && !p.endsWith('s1c.test.ts')) files.push(p)
      })
    walk(join(process.cwd(), 'tests'))
    for (const f of files) expect(readFileSync(f, 'utf8'), f).not.toMatch(/join\([^)]*['"]dist['"]/)
  })
})

describe('S0B-008：界面不显示运行时长（UPTIME）', () => {
  it('src 中除 api 契约外没有 uptime / 运行时长；/health 的 uptime_s 不被渲染', async () => {
    const hits: string[] = []
    const walk = (d: string) =>
      readdirSync(d).forEach((n) => {
        const p = join(d, n)
        if (statSync(p).isDirectory()) {
          if (!p.endsWith('/src/api')) walk(p)
        } else if (/uptime|运行时长/i.test(readFileSync(p, 'utf8'))) hits.push(p)
      })
    walk(join(process.cwd(), 'src'))
    expect(hits).toEqual([])
    const b = await boot()
    expect(b.wrapper.text()).not.toMatch(/uptime|运行时长/i)
    expect(b.wrapper.text()).not.toContain('12.4')
    await b.done()
  })
})
