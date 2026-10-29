import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = process.cwd()
const read = (p: string) => readFileSync(join(root, p), 'utf8')
const tokensCss = read('src/design/tokens.css')
const uiCss = read('src/design/ui.css')
const appCss = read('src/design/app.css')

// tokens.css = 浅色 :root 块 + `@media (prefers-color-scheme: dark)` 里的 :root 块
const darkStart = tokensCss.indexOf('@media (prefers-color-scheme: dark)')
const lightCss = tokensCss.slice(0, darkStart)
const darkCss = tokensCss.slice(darkStart)

function parse(css: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of css.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
    out[m[1]!] = m[2]!.replace(/\s+/g, ' ').trim()
  }
  return out
}
const light = parse(lightCss)
// 深色只覆盖一部分令牌，其余沿用浅色
const dark = { ...light, ...parse(darkCss) }

type RGB = [number, number, number]
const hex = (h: string): RGB => {
  expect(h, `不是 6 位十六进制色：${h}`).toMatch(/^#[0-9a-f]{6}$/i)
  return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB
}
function lum([r, g, b]: RGB): number {
  const c = [r, g, b].map((v) => {
    const x = v / 255
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [lum(hex(a)), lum(hex(b))].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}
const ok = (set: Record<string, string>, fg: string, bg: string, min = 4.5) =>
  expect(
    contrast(set[fg]!, set[bg]!),
    `${fg} on ${bg} (${set[fg]} / ${set[bg]})`,
  ).toBeGreaterThanOrEqual(min)

describe('设计令牌（方向 A）：浅色', () => {
  it('面、分隔线、文字、控件、强调的关键值', () => {
    const want: Record<string, string> = {
      'bg-window': '#ffffff',
      'bg-sidebar': '#f3f4f6',
      'bg-inspector': '#fafafb',
      'bg-settings': '#f5f5f7',
      line: '#e4e6eb',
      ink: '#1b1d22',
      mute: '#5b616e',
      faint: '#8b919c',
      disabled: '#a1a1a6',
      ctl: '#f3f4f6',
      hover: '#f3f4f6',
      'sel-blur': '#e9ecf3',
      'btn-primary-bg': '#1b1d22',
      accent: '#0a63d6',
      'on-accent': '#ffffff',
      'accent-ink': '#0a55b8',
      link: '#0058d0',
    }
    for (const [k, v] of Object.entries(want)) expect(light[k], k).toBe(v)
  })
  it('运行状态八色（底 / 文字 / 圆点）', () => {
    const want: Record<string, [string, string, string]> = {
      // 状态色取规范值；成功色 #1f8a5b 在浅底上只有 3.8:1，文字用加深的 #176a46，圆点保持规范值
      queued: ['#f3f4f6', '#4b5160', '#8b919c'],
      running: ['#e8eefc', '#2457d6', '#2457d6'],
      stopping: ['#fff0e0', '#8a3f00', '#e07b00'],
      success: ['#e6f4ec', '#176a46', '#1f8a5b'],
      failed: ['#fbeceb', '#b02f28', '#c2372f'],
      cancelled: ['#f3f4f6', '#4b5160', '#8b919c'],
      verify: ['#fdf1de', '#8a5200', '#9a5b00'],
      disabled: ['#f3f4f6', '#65656a', '#c7c7cc'],
    }
    for (const [k, [bg, fg, dot]] of Object.entries(want)) {
      expect([light[`st-${k}-bg`], light[`st-${k}-fg`], light[`st-${k}-dot`]], k).toEqual([
        bg,
        fg,
        dot,
      ])
    }
  })
  it('仓库线路色：四色固定，色板 8 色互不相同且不与状态圆点色重合', () => {
    expect([light['l-event'], light['l-front'], light['l-vip'], light['l-api']]).toEqual([
      '#0f8f86',
      '#2f5fe0',
      '#7a4fd6',
      '#d4651c',
    ])
    const palette = [1, 2, 3, 4, 5, 6, 7, 8].map((i) =>
      i <= 4 ? light[['l-event', 'l-front', 'l-vip', 'l-api'][i - 1]!] : light[`l-${i}`],
    )
    expect(new Set(palette).size).toBe(8)
    const statusDots = Object.entries(light)
      .filter(([k]) => /^st-.*-dot$/.test(k))
      .map(([, v]) => v)
    for (const c of palette) expect(statusDots).not.toContain(c)
  })
  it('提示横幅底与描边（信息 / 警告 / 错误）', () => {
    expect(light['bn-info-bg']).toBe('#f2f6fd')
    expect(light['bn-warn-bg']).toBe('#fff6e5')
    expect(light['bn-error-bg']).toBe('#fdecea')
    for (const k of ['info', 'warn', 'error']) {
      expect(light[`bn-${k}-line`], k).toMatch(/^#[0-9a-f]{6}$/i)
      expect(light[`bn-${k}-fg`], k).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
  it('字体、字号、圆角、间距、尺寸', () => {
    expect(light['font-sans']).toBe(
      "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Helvetica Neue', sans-serif",
    )
    expect(light['font-mono']).toBe("'SF Mono', ui-monospace, Menlo, monospace")
    expect([light['text-title'], light['text-page'], light['text-long']]).toEqual([
      '22px',
      '15px',
      '14px',
    ])
    expect([light['text-body'], light['text-sub'], light['text-group']]).toEqual([
      '13px',
      '12px',
      '11px',
    ])
    expect([light['r-ctl'], light['r-row'], light['r-group'], light['r-window']]).toEqual([
      '7px',
      '9px',
      '10px',
      '12px',
    ])
    expect([
      light['sp-1'],
      light['sp-2'],
      light['sp-3'],
      light['sp-4'],
      light['sp-5'],
      light['sp-6'],
    ]).toEqual(['4px', '8px', '12px', '16px', '20px', '28px'])
    expect([light['ctl-h'], light['topbar-h'], light['sidebar-w'], light['inspector-w']]).toEqual([
      '28px',
      '52px',
      '212px',
      '280px',
    ])
    expect(light['sidebar-w-compact']).toBe('76px')
    expect(light['target-min']).toBe('28px')
    const list = parseInt(light['list-w']!)
    expect(list).toBeGreaterThanOrEqual(320)
    expect(list).toBeLessThanOrEqual(380)
  })
  it('--ink 在窗口、侧栏、检查器、设置底、控件底、选中未聚焦底上 >= 4.5:1', () => {
    for (const bg of [
      'bg-window',
      'bg-sidebar',
      'bg-inspector',
      'bg-settings',
      'bg-list',
      'ctl',
      'sel-blur',
      'hover',
      'sidebar-sel',
    ]) {
      ok(light, 'ink', bg)
    }
  })
  it('--mute 在窗口、检查器、设置底上 >= 4.5:1；--mute-tint 在侧栏、控件底、选中未聚焦底上 >= 4.5:1', () => {
    for (const bg of ['bg-window', 'bg-inspector', 'bg-settings', 'bg-list', 'bg-group', 'hover'])
      ok(light, 'mute', bg)
    for (const bg of ['bg-sidebar', 'ctl', 'sel-blur', 'hover']) ok(light, 'mute-tint', bg)
  })
  it('白字在强调色上、强调文字/链接色在各面上、行选中态 >= 4.5:1', () => {
    ok(light, 'on-accent', 'accent')
    ok(light, 'row-sel-fg', 'row-sel-bg')
    ok(light, 'row-sel-sub', 'row-sel-bg')
    for (const bg of ['bg-window', 'bg-sidebar', 'bg-inspector', 'bg-settings']) {
      ok(light, 'accent-ink', bg)
      ok(light, 'link', bg)
    }
    for (const bg of ['bg-window', 'ctl', 'bg-inspector']) ok(light, 'danger', bg)
  })
  it('八种状态文字在各自底色上 >= 4.5:1', () => {
    for (const k of [
      'queued',
      'running',
      'stopping',
      'success',
      'failed',
      'cancelled',
      'verify',
      'disabled',
    ]) {
      ok(light, `st-${k}-fg`, `st-${k}-bg`)
    }
  })
  it('横幅文字（含错误标题）在横幅底上 >= 4.5:1', () => {
    for (const k of ['info', 'warn', 'error']) ok(light, `bn-${k}-fg`, `bn-${k}-bg`)
    ok(light, 'bn-error-title', 'bn-error-bg')
  })
})

describe('设计令牌（方向 B）：深色（跟随系统）', () => {
  it('深色在 @media (prefers-color-scheme: dark) 里，没有手动切换', () => {
    expect(darkStart).toBeGreaterThan(0)
    expect(tokensCss).not.toMatch(/data-theme|\.dark\b/)
  })
  it('面、文字、控件、强调的关键值', () => {
    const want: Record<string, string> = {
      'bg-window': '#121315',
      'bg-sidebar': '#0e0f11',
      'bg-list': '#141517',
      'bg-inspector': '#17181b',
      line: '#23252a',
      ctl: '#1f2125',
      'ctl-selected': '#3a3d44',
      ink: '#ecedef',
      mute: '#8b8e98',
      disabled: '#6f727c',
      accent: '#c6f432',
      'on-accent': '#14161a',
      link: '#d4f56a',
      'row-sel-bg': '#262a1c',
    }
    for (const [k, v] of Object.entries(want)) expect(dark[k], k).toBe(v)
  })
  it('--ink / --mute 在窗口、侧栏、列表、检查器、控件底上 >= 4.5:1', () => {
    for (const bg of [
      'bg-window',
      'bg-sidebar',
      'bg-list',
      'bg-inspector',
      'bg-settings',
      'bg-group',
      'ctl',
      'hover',
      'sel-blur',
      'sidebar-sel',
    ]) {
      ok(dark, 'ink', bg)
      ok(dark, 'mute', bg)
      ok(dark, 'mute-tint', bg)
    }
  })
  it('#14161A 在强调绿上 >= 4.5:1；链接色、强调文字在各面上；行选中态', () => {
    ok(dark, 'on-accent', 'accent')
    for (const bg of ['bg-window', 'bg-sidebar', 'bg-list', 'bg-inspector']) {
      ok(dark, 'link', bg)
      ok(dark, 'accent-ink', bg)
    }
    ok(dark, 'row-sel-fg', 'row-sel-bg')
    ok(dark, 'row-sel-sub', 'row-sel-bg')
    for (const bg of ['bg-window', 'ctl', 'bg-inspector']) ok(dark, 'danger', bg)
  })
  it('绿色不作文字色：强调色不被用作 color', () => {
    const css = [
      uiCss,
      appCss,
      ...walk(join(root, 'src'))
        .filter((f) => /\.(vue|css)$/.test(f))
        .map((f) => readFileSync(f, 'utf8')),
    ].join('\n')
    expect(css).not.toMatch(/(^|[^-])color:\s*var\(--accent\)/)
  })
  it('八种状态文字在各自底色上 >= 4.5:1', () => {
    for (const k of [
      'queued',
      'running',
      'stopping',
      'success',
      'failed',
      'cancelled',
      'verify',
      'disabled',
    ]) {
      ok(dark, `st-${k}-fg`, `st-${k}-bg`)
    }
  })
  it('横幅文字在横幅底上 >= 4.5:1', () => {
    for (const k of ['info', 'warn', 'error']) ok(dark, `bn-${k}-fg`, `bn-${k}-bg`)
    ok(dark, 'bn-error-title', 'bn-error-bg')
  })
})

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    return statSync(p).isDirectory() ? walk(p) : [p]
  })
}

describe('守卫：不含方向 E 残留', () => {
  const files = walk(join(root, 'src')).filter((f) => /\.(ts|vue|css|html)$/.test(f))
  const text = files.map((f) => ({ f, s: readFileSync(f, 'utf8') }))
  it.each([
    ['clip-path', /clip-path/],
    // 字符串拆开写：Tailwind 会扫描 tests/ 里的字面量并据此生成同名工具类，进而污染产物
    ['backdrop' + '-filter', new RegExp('backdrop' + '-filter')],
    ['Oxanium', /oxanium/i],
    ['@fontsource', /@fontsource/],
    ['--cut-* / --skew', /--cut-|--skew\b/],
    ['旧 --acc / --warn 令牌', /--acc\b|--warn\b|--warn-ink|--ok-ink/],
  ])('src 不含 %s', (_n, re) => {
    expect(text.filter(({ s }) => re.test(s)).map((x) => x.f)).toEqual([])
  })
  it('index.html 与 package.json 不含字体依赖', () => {
    expect(read('index.html')).not.toMatch(/fontsource|fonts\.googleapis/)
    expect(read('package.json')).not.toMatch(/@fontsource/)
  })
  it('不画假窗口按钮（红黄绿圆点色）', () => {
    expect(text.filter(({ s }) => /#ff5f57|#febc2e|#28c840/i.test(s)).map((x) => x.f)).toEqual([])
  })
  it('尊重 prefers-reduced-motion：关闭全部动画', () => {
    expect(uiCss).toMatch(/prefers-reduced-motion: reduce\)\s*{[^]*animation: none !important/)
  })
  it('body 显式背景色与系统字体令牌', () => {
    expect(appCss).toMatch(/background-color:\s*var\(--bg-window\)/)
    expect(appCss).toMatch(/font-family:\s*var\(--font-sans\)/)
  })
  // dist 的检查由 `pnpm guard:dist`（build 之后）负责；测试文件不读取 dist/（见 s1c S0B-007）
})
