// 时钟格式与卸载清定时器（假定时器），以及设计令牌的常态值与对比度（独立计算，不复用 tests/unit）。
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ClockBlock from '@/components/ClockBlock.vue'
import { formatClock } from '@/lib/clock'

describe('时钟格式（独立）', () => {
  it('HH:MM、秒、THU · 22 OCT 2026（2026-10-22 为周四）', () => {
    const p = formatClock(new Date(2026, 9, 22, 9, 5, 3))
    expect(p.hm).toBe('09:05')
    expect(p.seconds).toBe('03')
    expect(p.date).toBe('THU · 22 OCT 2026')
  })

  it('午夜与 23:59 的两位补零、周日与一月', () => {
    expect(formatClock(new Date(2027, 0, 3, 0, 0, 0)).hm).toBe('00:00')
    expect(formatClock(new Date(2027, 0, 3, 23, 59, 59)).hm).toBe('23:59')
    expect(formatClock(new Date(2027, 0, 3, 0, 0, 0)).date).toBe('SUN · 03 JAN 2027')
  })
})

describe('时钟组件（假定时器）', () => {
  afterEach(() => vi.useRealTimers())

  it('每秒更新显示，卸载后不再有残留定时器', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 9, 22, 9, 5, 3))
    let now = new Date(2026, 9, 22, 9, 5, 3)
    const w = mount(ClockBlock, { props: { now: () => now } })
    expect(w.get('[data-testid=clock-hm]').text()).toBe('09:05')
    expect(w.get('[data-testid=clock-sec]').text()).toBe('03')

    now = new Date(2026, 9, 22, 9, 5, 4)
    await vi.advanceTimersByTimeAsync(1000)
    expect(w.get('[data-testid=clock-sec]').text()).toBe('04')
    expect(w.get('[data-testid=clock-date]').text()).toBe('THU · 22 OCT 2026')

    const before = vi.getTimerCount()
    expect(before).toBeGreaterThan(0)
    w.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})

// ---- 设计令牌 ----
const tokensCss = readFileSync(join(process.cwd(), 'src/design/tokens.css'), 'utf8')

/** 取 `.hud` 块内某令牌的原始值 */
function rawToken(name: string): string {
  const block = /\.hud\s*\{([\s\S]*?)\n\}/.exec(tokensCss)
  if (!block) throw new Error('.hud block missing')
  const m = new RegExp(`--${name}:\\s*([^;]+);`).exec(block[1]!)
  if (!m) throw new Error(`--${name} missing in .hud`)
  return m[1]!.replace(/\s+/g, ' ').trim()
}

/** 常态值：color-mix 的第一个颜色（denied=0 时的权重端） */
function normal(name: string): string {
  const m = /color-mix\(in srgb,\s*(#[0-9a-fA-F]{6})/.exec(rawToken(name))
  if (!m) throw new Error(`--${name} has no leading hex`)
  return m[1]!.toLowerCase()
}

function alertEnd(name: string): string {
  const m = /,\s*(#[0-9a-fA-F]{6})\s+calc/.exec(rawToken(name))
  if (!m) throw new Error(`--${name} has no alert hex`)
  return m[1]!.toLowerCase()
}

function luminance(hex: string): number {
  const ch = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * ch[0]! + 0.7152 * ch[1]! + 0.0722 * ch[2]!
}

function contrast(a: string, b: string): number {
  const la = luminance(a)
  const lb = luminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

describe('设计令牌（独立）', () => {
  it('常态值与设计稿一致', () => {
    expect(normal('paper')).toBe('#e7e5e1')
    expect(normal('ink')).toBe('#111214')
    expect(normal('inv')).toBe('#f2f0eb')
    expect(normal('mute')).toBe('#5f5c57')
    expect(normal('faint')).toBe('#c9c6c0')
    expect(normal('card')).toBe('#f6f5f2')
    expect(normal('tab')).toBe('#dcdad5')
  })

  it('常量 --orange / --lime 与设计稿一致', () => {
    expect(rawToken('orange')).toBe('#ff7b00')
    expect(rawToken('lime')).toBe('#b9e432')
  })

  it('--denied 注册为 <number> 且初始值为 0', () => {
    expect(tokensCss).toMatch(/@property --denied \{[\s\S]*syntax:\s*'<number>'/)
    expect(tokensCss).toMatch(/initial-value:\s*0/)
  })

  it('--ink 与 --mute 在 --paper 常态上对比度 ≥ 4.5:1（含告警端）', () => {
    const paper = normal('paper')
    expect(contrast(normal('ink'), paper)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(normal('mute'), paper)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(alertEnd('ink'), alertEnd('paper'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(alertEnd('mute'), alertEnd('paper'))).toBeGreaterThanOrEqual(4.5)
  })

  it('减少动态效果偏好被遵守', () => {
    expect(tokensCss).toMatch(/prefers-reduced-motion:\s*reduce/)
  })
})
