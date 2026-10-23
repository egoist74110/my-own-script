// 主控守卫（S5-LEAD-002）：NewSessionSheet 的档位选项为手写列表，此处按 CLI 逐块锁定契约枚举；
// 后端枚举变化或某个 CLI 的列表漏项/多项时本用例失败，提醒同步更新 src/features/ai/NewSessionSheet.vue。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const openapi = JSON.parse(
  readFileSync(join(process.cwd(), '..', 'contracts', 'openapi.json'), 'utf8'),
)
const sheet = readFileSync(
  join(process.cwd(), 'src', 'features', 'ai', 'NewSessionSheet.vue'),
  'utf8',
)

function enumOf(schema: string, field: string): string[] {
  const prop = openapi.components.schemas[schema].properties[field]
  const found = [prop, ...(prop.anyOf ?? [])].find((p: { enum?: string[] }) => p.enum)
  return [...found.enum].sort()
}

/** 取 `const <name> = computed(...)` 中 `if (cli === '<cli>') { return [...] }` 块里的非空 value。 */
function optionValues(name: string, cli: string): string[] {
  const start = sheet.indexOf(`const ${name} = computed`)
  const end = sheet.indexOf('\n})', start)
  const body = sheet.slice(start, end)
  const blockStart = body.indexOf(`if (cli === '${cli}')`)
  expect(blockStart, `${name} 缺少 ${cli} 分支`).toBeGreaterThan(-1)
  const block = body.slice(blockStart, body.indexOf(']', blockStart))
  return [...block.matchAll(/value: '([^']*)'/g)]
    .map((m) => m[1] ?? '')
    .filter(Boolean)
    .sort()
}

describe('新会话 Sheet 的档位选项与契约枚举逐 CLI 一致', () => {
  it.each([
    ['effortOptions', 'claude', 'ClaudeDefaults', 'effort'],
    ['effortOptions', 'codex', 'CodexDefaults', 'effort'],
    ['effortOptions', 'agy', 'AgyDefaults', 'effort'],
    ['permissionOptions', 'claude', 'ClaudeDefaults', 'permission'],
    ['permissionOptions', 'codex', 'CodexDefaults', 'sandbox'],
    ['permissionOptions', 'agy', 'AgyDefaults', 'mode'],
  ])('%s[%s] 等于 %s.%s', (name, cli, schema, field) => {
    expect(optionValues(name, cli)).toEqual(enumOf(schema, field))
  })
})
