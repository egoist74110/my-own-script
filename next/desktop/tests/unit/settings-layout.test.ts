// R1 返工：jsdom 不计算布局，这里用样式契约卡住「设置页内容区宽度为 0」的回归，
// 并确认编辑器在内容区分组卡片里、设置页不再有检查器与检查器开关。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const src = (p: string) => readFileSync(join(process.cwd(), 'src', p), 'utf8')
const block = (css: string, selector: string): string => {
  const i = css.indexOf(selector)
  expect(i, `找不到选择器 ${selector}`).toBeGreaterThanOrEqual(0)
  return css.slice(css.indexOf('{', i) + 1, css.indexOf('}', i))
}

describe('设置页布局契约', () => {
  const page = src('features/settings/SettingsPage.vue')
  const seg = src('components/SegmentedControl.vue')

  it('分区导航：固定 220px、不 flex-grow，右边 1px 分隔线', () => {
    // 选择器特异性须高于 SegmentedControl 的 `.seg-root[data-orientation='vertical'] .seg`（scoped 后 0,4,0），
    // 否则 220px/内边距被覆盖（主控集成截图实测导航只有 113px）
    const b = block(page, ".panel .settings-tabs[data-orientation='vertical'] > :deep(.seg) {")
    expect(b).toMatch(/flex:\s*none/)
    expect(b).toMatch(/width:\s*220px/)
    expect(b).toMatch(/border-right:\s*1px solid var\(--line\)/)
  })
  it('竖向 SegmentedControl 的 tablist 不设 width:100%（会盖过页面给的 220px，把内容区挤成 0）', () => {
    const b = block(seg, ".seg-root[data-orientation='vertical'] .seg {")
    expect(b).not.toMatch(/width:\s*100%/)
    expect(b).not.toMatch(/flex-grow:\s*[1-9]|flex:\s*[1-9]/)
  })
  it('内容区：flex:1、min-width:0、设置底色', () => {
    const b = block(page, '.settings-tabs > :deep(.tab-panel) {')
    expect(b).toMatch(/flex:\s*1/)
    expect(b).toMatch(/min-width:\s*0/)
    expect(b).toMatch(/background:\s*var\(--bg-settings\)/)
    expect(block(page, '.settings-tabs {')).toMatch(/display:\s*flex/)
  })
  it('设置页没有检查器：不挂 Inspector，也没有检查器开关', () => {
    for (const f of [
      'features/settings/SettingsPage.vue',
      'features/settings/AdoTab.vue',
      'features/settings/LocalReposTab.vue',
    ]) {
      const t = src(f)
      expect(t, f).not.toMatch(/<Inspector\b|InspectorToggle/)
    }
  })
  it('编辑器放在内容区分组卡片里；表单行标签在左控件在右', () => {
    expect(src('features/settings/AdoTab.vue')).toMatch(/class="st-section st-editor"/)
    expect(src('features/settings/LocalReposTab.vue')).toMatch(/class="st-section st-editor"/)
    const css = src('features/settings/settings.css')
    const b = block(css, '.st-fld {')
    expect(b).toMatch(/display:\s*grid/)
    expect(b).toMatch(/grid-template-columns:\s*120px/)
  })
})
