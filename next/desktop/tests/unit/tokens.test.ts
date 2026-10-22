import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = process.cwd()
const tokensCss = readFileSync(join(root, 'src/design/tokens.css'), 'utf8')
const uiCss = readFileSync(join(root, 'src/design/ui.css'), 'utf8')
const appCss = readFileSync(join(root, 'src/design/app.css'), 'utf8')

function token(name: string): string {
  const m = new RegExp(`--${name}:\\s*([^;]+);`).exec(tokensCss)
  if (!m) throw new Error(`token --${name} not found`)
  return m[1]!.replace(/\s+/g, ' ').trim()
}

type RGB = [number, number, number]
const hex = (h: string): RGB => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB
function lum([r, g, b]: RGB): number {
  const c = [r, g, b].map((v) => {
    const x = v / 255
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!
}
function contrast(a: RGB, b: RGB): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}
/** 白色 alpha 叠在底色上（玻璃面板的不透明近似） */
const overWhite = (alpha: number, base: RGB): RGB =>
  base.map((v) => Math.round(255 * alpha + v * (1 - alpha))) as RGB

const pearls = ['pearl-a', 'pearl-b', 'pearl-c'].map((n) => hex(token(n)))
// 玻璃最透明处（.52）叠在三种珍珠底上，取最不利者
const glass = pearls.map((p) => overWhite(0.52, p))

describe('设计令牌（方向 E）', () => {
  it('关键令牌值', () => {
    expect(token('ink')).toBe('#14161a')
    expect(token('mute')).toBe('#545a68')
    expect(token('line')).toBe('rgba(20, 22, 26, 0.09)')
    expect(token('acc')).toBe('#c6f432')
    expect(token('warn')).toBe('#ff6a00')
    expect(token('pearl-a')).toBe('#f4f5f8')
    expect(token('pearl-b')).toBe('#eceef3')
    expect(token('pearl-c')).toBe('#f2efea')
    expect(token('page-bg')).toBe('#eef0f4')
  })

  it('字体令牌：Oxanium / Inter / JetBrains Mono，Inter 回退中文字体', () => {
    expect(token('font-display')).toContain("'Oxanium'")
    expect(token('font-sans')).toMatch(/^'Inter', 'PingFang SC', 'Hiragino Sans GB', system-ui/)
    expect(token('font-mono')).toContain("'JetBrains Mono'")
  })

  it('密度与几何：正文 13px、行高 46px、目标 >= 32px、微型字 >= 10px、切角 12/6、斜切 5', () => {
    expect(token('text-body')).toBe('13px')
    expect(token('row-h')).toBe('46px')
    expect(token('target-min')).toBe('32px')
    expect(token('text-micro')).toBe('10px')
    expect(token('cut-lg')).toBe('12px')
    expect(token('cut-sm')).toBe('6px')
    expect(token('skew')).toBe('5px')
    expect(token('sidebar-w')).toBe('208px')
    expect(uiCss).toMatch(/\.cut \{\s*clip-path: polygon\(\s*0 0,\s*calc\(100% - 12px\) 0/)
    expect(uiCss).toMatch(/\.cut-xs \{\s*clip-path: polygon\(0 0, calc\(100% - 6px\) 0/)
    expect(uiCss).toMatch(/\.skew \{\s*clip-path: polygon\(5px 0/)
  })

  it('body 显式背景色与珍珠渐变', () => {
    expect(appCss).toMatch(/background-color:\s*#eef0f4/)
    expect(appCss).toContain('#f4f5f8 0%, #eceef3 60%, #f2efea 100%')
  })

  it('玻璃面板：blur(28px) saturate(180%)，并为不支持 backdrop-filter 的环境保留不透明回退', () => {
    expect(uiCss).toContain('blur(28px) saturate(180%)')
    expect(uiCss).toMatch(/\.glass \{[^}]*background: var\(--glass-solid\)/)
    expect(uiCss).toMatch(/@supports \(backdrop-filter: blur\(1px\)\)/)
    expect(token('glass-solid')).toBe('#f8f9fb')
  })

  it('--denied 与 HUD 样式已删除', () => {
    expect(tokensCss).not.toContain('--denied')
    expect(uiCss + appCss).not.toContain('--denied')
    expect(existsSync(join(root, 'src/design/hud.css'))).toBe(false)
  })

  it('尊重 prefers-reduced-motion：关闭全部动画', () => {
    expect(uiCss).toMatch(/prefers-reduced-motion: reduce\)\s*{[^]*animation: none !important/)
  })

  it('--ink、--mute 在珍珠底与玻璃面板上 >= 4.5:1', () => {
    for (const name of ['ink', 'mute']) {
      const c = hex(token(name))
      for (const bg of [...pearls, ...glass, hex(token('glass-solid')), [255, 255, 255] as RGB]) {
        expect(contrast(c, bg)).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('墨色在 --acc、--warn 填充上 >= 4.5:1', () => {
    const ink = hex(token('ink'))
    expect(contrast(ink, hex(token('acc')))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(ink, hex(token('warn')))).toBeGreaterThanOrEqual(4.5)
  })

  it('深橙/深绿文字令牌在珍珠底与玻璃上 >= 4.5:1；亮橙本身不足，只能作填充', () => {
    for (const name of ['warn-ink', 'ok-ink']) {
      for (const bg of [...pearls, ...glass]) {
        expect(contrast(hex(token(name)), bg)).toBeGreaterThanOrEqual(4.5)
      }
    }
    expect(contrast(hex(token('warn')), pearls[1]!)).toBeLessThan(4.5)
  })

  it('强调色不作为文字色：样式里没有 color: var(--acc)（只允许深色底上的点缀）', () => {
    // 允许出现在黑底组件（审批条/阶段条/导航编号）上，这里只检查浅色面板里的通用类
    expect(uiCss).not.toMatch(/(^|[^-])color:\s*var\(--acc\)/)
  })
})
