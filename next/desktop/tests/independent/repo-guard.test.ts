// 源码禁词守卫（独立编写，等价于 grep -rIiE 'rhine|arknights|fonts.googleapis' src）。
// dist 的禁词检查已移到 `pnpm guard:dist`（build 之后单独运行），本文件不依赖 dist。
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { scan } from '../../scripts/forbidden-scan.mjs'

describe('禁词守卫（独立）', () => {
  it('src 不含 Rhine / RHINE / Arknights / fonts.googleapis.com', () => {
    expect(scan(join(process.cwd(), 'src'))).toEqual([])
  })
})
