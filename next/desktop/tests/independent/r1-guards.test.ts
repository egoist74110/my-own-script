// R1 独立验证：守卫（合同 R1 验收第 3 条）。只扫描 src/**，不读 dist/。
// 禁用词在本文件中用拼接形式书写，避免 Tailwind 扫描 tests/ 时把字面量写进构建产物。
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(process.cwd())
const SRC = join(ROOT, 'src')

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(vue|ts|tsx|css|html|json|js)$/.test(name)) out.push(p)
  }
  return out
}
const FILES = walk(SRC)
const read = (p: string) => readFileSync(p, 'utf8')

/** 返回所有命中 `needle` 的相对路径（含行号），便于失败时定位。 */
function hits(needle: string | RegExp): string[] {
  const found: string[] = []
  for (const f of FILES) {
    const lines = read(f).split('\n')
    lines.forEach((line, i) => {
      const hit = typeof needle === 'string' ? line.includes(needle) : needle.test(line)
      if (hit) found.push(`${relative(ROOT, f)}:${i + 1}`)
    })
  }
  return found
}

describe('R1 守卫：src/** 不含已废弃的视觉手法与字体', () => {
  it('扫描到了 src 文件（守卫不是空跑）', () => {
    expect(FILES.length).toBeGreaterThan(20)
    expect(FILES.some((f) => f.endsWith('tokens.css'))).toBe(true)
  })

  it('不含 clip-path（切角）', () => {
    expect(hits('clip-path')).toEqual([])
  })

  it('不含 backdrop-filter（玻璃），用拼接形式检查', () => {
    expect(hits('backdrop' + '-filter')).toEqual([])
  })

  it('不含 Oxanium 与 @fontsource（字体已改为系统字体）', () => {
    expect(hits('Oxanium')).toEqual([])
    expect(hits('@fontsource')).toEqual([])
  })

  it('已删除的 --cut-*/--skew/旧 --acc/--warn 令牌不再被声明或引用', () => {
    expect(hits(/--cut-/)).toEqual([])
    expect(hits(/--skew/)).toEqual([])
    expect(hits(/--acc(?![\w-])/)).toEqual([])
    expect(hits(/--warn(?![\w-])/)).toEqual([])
  })

  it('package.json 不再依赖任何 @fontsource 包，main.ts 不再导入字体', () => {
    const pkg = read(join(ROOT, 'package.json'))
    expect(pkg).not.toMatch(/@fontsource/)
    const main = read(join(SRC, 'main.ts'))
    expect(main).not.toMatch(/@fontsource|\.css\/font|oxanium/i)
  })
})

describe('R1 守卫：禁词不得出现在 src/**', () => {
  for (const word of ['Rhine', 'RHINE', 'Arknights', 'fonts.googleapis']) {
    it(`不含 ${word}`, () => {
      expect(hits(word)).toEqual([])
    })
  }
})
