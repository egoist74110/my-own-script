import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('S4-C dev-web 假 Telegram 静态安全门禁', () => {
  it('只由 dev-web 启动器设置假 Telegram 环境变量', () => {
    const script = readFileSync('scripts/dev-web.mjs', 'utf8')
    expect(script).toMatch(/TOOLBOX_DEV_FAKE_TELEGRAM\s*:\s*['"]1['"]/)
    expect(script).toContain("spawn('uv', ['run', 'python', '-m', 'toolbox_backend', '--dev']")
  })
})
