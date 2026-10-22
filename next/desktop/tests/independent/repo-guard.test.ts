// 源码与构建产物禁词守卫（独立编写，等价于 grep -rIiE 'rhine|arknights|fonts.googleapis' src dist）。
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = process.cwd()
const FORBIDDEN = /rhine|arknights|莱茵|fonts\.googleapis/i

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

/** 返回命中禁词的 `文件:行号` 列表（跳过含 NUL 的二进制文件，与 grep -I 一致）。 */
function scan(dir: string): string[] {
  const hits: string[] = []
  for (const file of walk(dir)) {
    const buf = readFileSync(file)
    if (buf.includes(0)) continue
    const lines = buf.toString('utf8').split('\n')
    lines.forEach((line, i) => {
      if (FORBIDDEN.test(line)) hits.push(`${file}:${i + 1}`)
    })
  }
  return hits
}

describe('禁词守卫（独立）', () => {
  it('src 不含 Rhine / RHINE / Arknights / fonts.googleapis.com', () => {
    expect(scan(join(ROOT, 'src'))).toEqual([])
  })

  it('dist 不含禁词（需先运行 pnpm build）', () => {
    const dist = join(ROOT, 'dist')
    expect(existsSync(dist), 'dist 不存在：请先运行 pnpm build').toBe(true)
    expect(scan(dist)).toEqual([])
  })
})
