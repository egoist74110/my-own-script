// 重新生成 schema.d.ts 并与入库文件比对；不一致则非 0 退出（并还原入库内容）。
import { spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const target = fileURLToPath(new URL('../src/api/schema.d.ts', import.meta.url))
const committed = readFileSync(target, 'utf8')
const r = spawnSync('pnpm', ['run', 'contracts:gen'], { stdio: 'inherit' })
const generated = readFileSync(target, 'utf8')
writeFileSync(target, committed)
if (r.status !== 0) process.exit(r.status ?? 1)
if (generated !== committed) {
  console.error(
    'contracts:check 失败：src/api/schema.d.ts 与 openapi.json 不一致，请运行 pnpm contracts:gen',
  )
  process.exit(1)
}
console.log('contracts:check ok')
