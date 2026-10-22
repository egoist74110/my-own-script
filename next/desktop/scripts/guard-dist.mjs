// 构建产物禁词守卫：必须在 `pnpm build` 之后单独运行（`pnpm guard:dist`）。
// dist 不存在视为失败（不能静默通过）；`pnpm test` 不依赖 dist。
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { scan, walk } from './forbidden-scan.mjs'

const dist = fileURLToPath(new URL('../dist', import.meta.url))
if (!existsSync(dist)) {
  console.error('guard:dist 失败：dist/ 不存在，请先运行 pnpm build')
  process.exit(1)
}
const hits = scan(dist)
if (hits.length > 0) {
  console.error(`guard:dist 失败：dist 含禁词：\n${hits.join('\n')}`)
  process.exit(1)
}
// 已删除的 --denied 令牌不得残留在产物里
const residue = walk(dist).filter((f) => {
  const buf = readFileSync(f)
  return !buf.includes(0) && /--denied/.test(buf.toString('utf8'))
})
if (residue.length > 0) {
  console.error(`guard:dist 失败：dist 含已删除的 --denied 令牌：\n${residue.join('\n')}`)
  process.exit(1)
}
console.log('guard:dist ok')
