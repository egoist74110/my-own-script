import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

function token(name: string): string {
  const m = new RegExp(`--${name}:\\s*([^;]+);`).exec(tokensCss)
  if (!m) throw new Error(`token --${name} not found`)
  return m[1]!.replace(/\s+/g, ' ').trim()
}

/** color-mix(in srgb, A, B calc(...)) 的两端颜色 */
function mixEnds(name: string): [string, string] {
  const m = /color-mix\(in srgb, (#[0-9a-f]{6}), (#[0-9a-f]{6}) calc/i.exec(token(name))
  if (!m) throw new Error(`--${name} is not a two-colour mix`)
  return [m[1]!.toLowerCase(), m[2]!.toLowerCase()]
}

function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

const tokensCss = readFileSync(join(process.cwd(), 'src/design/tokens.css'), 'utf8')

describe('设计令牌（与设计稿一致）', () => {
  const expected: Record<string, [string, string]> = {
    paper: ['#e7e5e1', '#0b0b0c'],
    ink: ['#111214', '#f2f0eb'],
    inv: ['#f2f0eb', '#111214'],
    mute: ['#5f5c57', '#9a9893'],
    faint: ['#c9c6c0', '#2b2b2d'],
    card: ['#f6f5f2', '#151618'],
    tab: ['#dcdad5', '#1d1e20'],
    fa: ['#ffffff', '#5a2a08'],
    fb: ['#cdc8bf', '#120b06'],
  }
  for (const [name, ends] of Object.entries(expected)) {
    it(`--${name} 常态/告警端点`, () => {
      expect(mixEnds(name)).toEqual(ends)
    })
  }

  it('常量与 accent 混色', () => {
    expect(token('orange')).toBe('#ff7b00')
    expect(token('lime')).toBe('#b9e432')
    expect(token('accent')).toBe(
      'color-mix(in srgb, #7fa316, var(--orange) calc(var(--denied) * 100%))',
    )
    expect(token('accent-fill')).toBe(
      'color-mix(in srgb, var(--lime), var(--orange) calc(var(--denied) * 100%))',
    )
  })

  it('--denied 注册为 <number>，常态为 0', () => {
    expect(tokensCss).toMatch(/@property --denied\s*{[^}]*syntax:\s*'<number>'/)
    expect(tokensCss).toMatch(/initial-value:\s*0;/)
  })

  it('微型字号 >= 10px', () => {
    expect(token('text-micro')).toBe('10px')
  })

  it('尊重 prefers-reduced-motion', () => {
    expect(tokensCss).toContain('prefers-reduced-motion: reduce')
  })

  it('文字对比度 >= 4.5:1（常态与告警态）', () => {
    const [paper0, paper1] = mixEnds('paper')
    for (const name of ['ink', 'mute']) {
      const [c0, c1] = mixEnds(name)
      expect(contrast(c0, paper0)).toBeGreaterThanOrEqual(4.5)
      expect(contrast(c1, paper1)).toBeGreaterThanOrEqual(4.5)
    }
    // 文字灰在卡片面上同样达标
    const [card0] = mixEnds('card')
    expect(contrast(mixEnds('mute')[0], card0)).toBeGreaterThanOrEqual(4.5)
  })
})
