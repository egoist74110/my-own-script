import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    return statSync(p).isDirectory() ? walk(p) : [p]
  })
}

describe('源码不含禁用字样', () => {
  const files = walk(join(process.cwd(), 'src')).filter((f) => /\.(ts|vue|css|html)$/.test(f))
  it('扫描到源文件', () => expect(files.length).toBeGreaterThan(10))
  it('无 Rhine Lab / Arknights / 莱茵 / fonts.googleapis（允许署名 rhine-lock）', () => {
    const bad = files.filter((f) =>
      /rhine[\s_-]*lab|arknights|莱茵|fonts\.googleapis/i.test(readFileSync(f, 'utf8')),
    )
    expect(bad).toEqual([])
  })
})
