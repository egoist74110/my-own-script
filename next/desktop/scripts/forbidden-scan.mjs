// 禁词扫描（供 guard-dist.mjs 与单元测试共用）。等价于 grep -rIiE '<FORBIDDEN>' <dir>。
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

export const FORBIDDEN = /rhine|arknights|莱茵|fonts\.googleapis/i

export function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

/** 返回命中禁词的 `文件:行号` 列表（跳过含 NUL 的二进制文件，与 grep -I 一致）。 */
export function scan(dir) {
  const hits = []
  for (const file of walk(dir)) {
    const buf = readFileSync(file)
    if (buf.includes(0)) continue
    buf
      .toString('utf8')
      .split('\n')
      .forEach((line, i) => {
        if (FORBIDDEN.test(line)) hits.push(`${file}:${i + 1}`)
      })
  }
  return hits
}
