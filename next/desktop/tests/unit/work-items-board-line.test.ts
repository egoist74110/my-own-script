// 回归：工单详情里的看板列线路被 flex 压成细带（只剩圆圈上半截 + 纵向滚动条）。
// 根因：.route 为 overflow-x:auto（→ overflow-y 也算 auto，min-height:auto 变 0），
// 位于 overflow:auto 的 flex 列 .detail 内，默认 flex-shrink:1 被压扁。
// jsdom 不做布局：这里断言 DOM 与源码样式；真实像素高度（不被裁、窄窗三档、浮层）需在应用里目测。
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BoardLine from '@/features/work-items/BoardLine.vue'
import source from '@/features/work-items/BoardLine.vue?raw'

const cols = ['新建', '开发中', '测试中', '待发布', '已发布']

function rule(selector: string): string {
  const css = source.slice(source.indexOf('<style'))
  const m = css.match(new RegExp(`(^|\\n)${selector.replace('.', '\\.')}\\s*\\{([^}]*)\\}`))
  return m?.[2] ?? ''
}

describe('BoardLine 线路图容器', () => {
  it('站点名称、当前站都在 DOM 里', () => {
    const w = mount(BoardLine, { props: { columns: cols, current: '测试中' } })
    for (const c of cols) expect(w.text()).toContain(c)
    const here = w.get('[aria-current="step"]')
    expect(here.text()).toContain('测试中')
    expect(w.findAll('li')).toHaveLength(cols.length)
  })

  it('当前列不在站点里时不渲染（不猜位置）', () => {
    expect(
      mount(BoardLine, { props: { columns: cols, current: '不存在' } })
        .find('.route')
        .exists(),
    ).toBe(false)
  })

  it('容器不是纵向滚动、没有固定小高度、不会被 flex 压缩', () => {
    const r = rule('.route')
    expect(r).toMatch(/flex:\s*none/)
    expect(r).toMatch(/overflow-y:\s*hidden/)
    expect(r).not.toMatch(/overflow-y:\s*(auto|scroll)/)
    expect(r).not.toMatch(/(^|[\s;])(max-)?height\s*:/)
    expect(r).toMatch(/overflow-x:\s*auto/)
  })

  it('站名与副标题没有 display:none，也无内联 display:none', () => {
    const w = mount(BoardLine, { props: { columns: cols, current: '开发中' } })
    for (const sel of ['.name', '.sub']) {
      expect(rule(sel)).not.toMatch(/display:\s*none/)
    }
    for (const el of w.findAll('.route, .track, .stn, .name')) {
      expect(el.attributes('style') ?? '').not.toMatch(/display:\s*none/)
    }
    expect(w.findAll('.name').map((n) => n.text())).toEqual(cols)
  })
})
