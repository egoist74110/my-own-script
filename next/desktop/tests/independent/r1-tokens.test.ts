// R1 独立验证：令牌数值与对比度（从合同 R1 验收第 2 条推导，不照抄既有 tokens.test.ts）。
// 解析 src/design/tokens.css 的浅色 :root 与深色 @media 两段，按“实际用于该面的文字令牌”断言。
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src/design/tokens.css'), 'utf8')
const DARK_MARK = '@media (prefers-color-scheme: dark)'
const darkAt = css.indexOf(DARK_MARK)
const lightBlock = css.slice(0, darkAt)
const darkBlock = css.slice(darkAt)

function tokens(block: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    out[m[1]!] = m[2]!.toLowerCase()
  }
  return out
}
const light = tokens(lightBlock)
const dark = tokens(darkBlock)

function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

function need(t: Record<string, string>, name: string): string {
  const v = t[name]
  if (!v) throw new Error(`token --${name} missing`)
  return v
}

describe('R1 令牌数值（浅色 / 深色）', () => {
  it('浅色关键令牌与合同一致', () => {
    expect(light['bg-window']).toBe('#ffffff')
    // 方向 A（线路图）规范取值：纸 / 框架 / 墨 / 次文字 / 分隔线
    expect(light['bg-sidebar']).toBe('#f3f4f6')
    expect(light['bg-inspector']).toBe('#fafafb')
    expect(light['bg-settings']).toBe('#f5f5f7')
    expect(light['line']).toBe('#e4e6eb')
    expect(light['ink']).toBe('#1b1d22')
    expect(light['mute']).toBe('#5b616e')
    expect(light['disabled']).toBe('#a1a1a6')
    expect(light['ctl']).toBe('#f3f4f6')
    expect(light['accent']).toBe('#0a63d6')
    expect(light['accent-ink']).toBe('#0a55b8')
    expect(light['link']).toBe('#0058d0')
  })

  it('深色关键令牌与合同一致（强调为荧光绿，文字为深色）', () => {
    expect(dark['bg-window']).toBe('#121315')
    expect(dark['bg-sidebar']).toBe('#0e0f11')
    expect(dark['bg-list']).toBe('#141517')
    expect(dark['bg-inspector']).toBe('#17181b')
    expect(dark['line']).toBe('#23252a')
    expect(dark['ctl']).toBe('#1f2125')
    expect(dark['ctl-selected']).toBe('#3a3d44')
    expect(dark['ink']).toBe('#ecedef')
    expect(dark['mute']).toBe('#8b8e98')
    expect(dark['disabled']).toBe('#6f727c')
    expect(dark['accent']).toBe('#c6f432')
    expect(dark['on-accent']).toBe('#14161a')
    expect(dark['link']).toBe('#d4f56a')
    expect(dark['row-sel-bg']).toBe('#262a1c')
  })

  it('已删除的旧令牌（切角/斜切/--acc/--warn）不再声明', () => {
    for (const name of Object.keys({ ...light, ...dark })) {
      expect(name.startsWith('cut-'), `--${name}`).toBe(false)
      expect(name, `--${name}`).not.toBe('skew')
      expect(name, `--${name}`).not.toBe('acc')
      expect(name, `--${name}`).not.toBe('warn')
    }
  })
})

describe('R1 对比度（实际用于该面的文字令牌，浅色与深色）', () => {
  // 浅色：窗口/检查器上用 --mute；侧栏与控件底上用 --mute-tint（合同已知偏差）
  it('浅色正文与次要文字在窗口、侧栏、检查器、控件底上 ≥4.5:1', () => {
    const faces = ['bg-window', 'bg-sidebar', 'bg-inspector', 'ctl'] as const
    for (const f of faces) {
      expect(ratio(need(light, 'ink'), need(light, f)), `ink on ${f}`).toBeGreaterThanOrEqual(4.5)
    }
    expect(ratio(need(light, 'mute'), need(light, 'bg-window'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(need(light, 'mute'), need(light, 'bg-inspector'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(need(light, 'mute-tint'), need(light, 'bg-sidebar'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(need(light, 'mute-tint'), need(light, 'ctl'))).toBeGreaterThanOrEqual(4.5)
  })

  it('深色正文与次要文字在窗口、侧栏、检查器、控件底上 ≥4.5:1', () => {
    const faces = ['bg-window', 'bg-sidebar', 'bg-inspector', 'ctl'] as const
    for (const f of faces) {
      expect(ratio(need(dark, 'ink'), need(dark, f)), `ink on ${f}`).toBeGreaterThanOrEqual(4.5)
      expect(ratio(need(dark, 'mute'), need(dark, f)), `mute on ${f}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('白字在浅色强调上、#14161A 在深色强调上 ≥4.5:1', () => {
    expect(ratio('#ffffff', need(light, 'accent'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(need(dark, 'on-accent'), need(dark, 'accent'))).toBeGreaterThanOrEqual(4.5)
    expect(need(dark, 'on-accent')).toBe('#14161a')
  })

  it('链接在窗口底上 ≥4.5:1（两套）', () => {
    expect(ratio(need(light, 'link'), need(light, 'bg-window'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(need(dark, 'link'), need(dark, 'bg-window'))).toBeGreaterThanOrEqual(4.5)
  })

  const STATES = [
    'queued',
    'running',
    'stopping',
    'success',
    'failed',
    'cancelled',
    'verify',
    'disabled',
  ] as const
  for (const s of STATES) {
    it(`运行状态「${s}」文字在自身底色上 ≥4.5:1（浅色与深色）`, () => {
      expect(
        ratio(need(light, `st-${s}-fg`), need(light, `st-${s}-bg`)),
        `light ${s}`,
      ).toBeGreaterThanOrEqual(4.5)
      expect(
        ratio(need(dark, `st-${s}-fg`), need(dark, `st-${s}-bg`)),
        `dark ${s}`,
      ).toBeGreaterThanOrEqual(4.5)
    })
  }

  for (const kind of ['info', 'warn', 'error'] as const) {
    it(`提示横幅（${kind}）文字在横幅底上 ≥4.5:1（浅色与深色）`, () => {
      expect(
        ratio(need(light, `bn-${kind}-fg`), need(light, `bn-${kind}-bg`)),
        `light ${kind}`,
      ).toBeGreaterThanOrEqual(4.5)
      expect(
        ratio(need(dark, `bn-${kind}-fg`), need(dark, `bn-${kind}-bg`)),
        `dark ${kind}`,
      ).toBeGreaterThanOrEqual(4.5)
    })
  }
})
