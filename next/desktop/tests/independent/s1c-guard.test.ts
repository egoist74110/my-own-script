// S1-C 独立用例（independent=true）：guard-dist 的禁词与 --denied 残留检测。
// 为不触碰真实 dist/，把 scripts/guard-dist.mjs 与 forbidden-scan.mjs 复制到 os.tmpdir() 下的沙箱，
// 脚本以 import.meta.url 定位的 ../dist 即沙箱内的 dist。测试结束后删除沙箱。
import { spawnSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

const ROOT = process.cwd()
const DIST_DIR = 'dist'
let sandbox = ''

function setup(): string {
  const dir = mkdtempSync(join(tmpdir(), 's1c-guard-'))
  mkdirSync(join(dir, 'scripts'))
  copyFileSync(join(ROOT, 'scripts/guard-dist.mjs'), join(dir, 'scripts/guard-dist.mjs'))
  copyFileSync(join(ROOT, 'scripts/forbidden-scan.mjs'), join(dir, 'scripts/forbidden-scan.mjs'))
  return dir
}

function runGuard(dir: string) {
  const r = spawnSync(process.execPath, [join(dir, 'scripts/guard-dist.mjs')], { encoding: 'utf8' })
  return { code: r.status, out: r.stdout, err: r.stderr }
}

function freshDist(): string {
  const d = join(sandbox, DIST_DIR)
  rmSync(d, { recursive: true, force: true })
  mkdirSync(join(d, 'assets'), { recursive: true })
  return d
}

beforeAll(() => {
  sandbox = setup()
})
afterAll(() => {
  if (sandbox) rmSync(sandbox, { recursive: true, force: true })
})

describe('guard:dist 沙箱（独立）', () => {
  it('dist 不存在：失败退出 1，且有明确提示', () => {
    rmSync(join(sandbox, DIST_DIR), { recursive: true, force: true })
    const r = runGuard(sandbox)
    expect(r.code).toBe(1)
    expect(r.err).toContain('dist/ 不存在')
  })

  it('干净的 dist：退出 0，输出 ok', () => {
    const d = freshDist()
    writeFileSync(join(d, 'assets', 'index.js'), 'console.log("hello")\n')
    writeFileSync(join(d, 'index.html'), '<!doctype html><title>工具箱</title>\n')
    const r = runGuard(sandbox)
    expect(r.code).toBe(0)
    expect(r.out).toContain('guard:dist ok')
  })

  const words = [
    'Rhine',
    'rhine',
    'RHINE',
    'Arknights',
    'ARKNIGHTS',
    '莱茵',
    'fonts.googleapis.com',
  ]
  for (const w of words) {
    it(`禁词 ${w} 命中：退出 1，报告 文件:行号（第 3 行）`, () => {
      const d = freshDist()
      writeFileSync(join(d, 'assets', 'bad.js'), `ok\nfine\nx ${w} y\n`)
      const r = runGuard(sandbox)
      expect(r.code).toBe(1)
      expect(r.err).toContain('dist 含禁词')
      expect(r.err).toMatch(/bad\.js:3\b/)
    })
  }

  it('嵌套子目录中的禁词同样被发现', () => {
    const d = freshDist()
    mkdirSync(join(d, 'assets', 'deep', 'er'), { recursive: true })
    writeFileSync(join(d, 'assets', 'deep', 'er', 'x.css'), '/* Rhine */\n')
    const r = runGuard(sandbox)
    expect(r.code).toBe(1)
    expect(r.err).toMatch(/x\.css:1\b/)
  })

  it('同一产物多处命中：每一处都列出', () => {
    const d = freshDist()
    writeFileSync(join(d, 'a.js'), 'Rhine\n')
    writeFileSync(join(d, 'b.js'), 'Arknights\n莱茵\n')
    const r = runGuard(sandbox)
    expect(r.code).toBe(1)
    expect(r.err).toMatch(/a\.js:1/)
    expect(r.err).toMatch(/b\.js:1/)
    expect(r.err).toMatch(/b\.js:2/)
  })

  it('含 NUL 的二进制文件中的禁词被跳过（与 grep -I 一致），不误报', () => {
    const d = freshDist()
    writeFileSync(join(d, 'font.woff2'), Buffer.from([0, 82, 104, 105, 110, 101, 0]))
    const r = runGuard(sandbox)
    expect(r.code).toBe(0)
  })

  it('特征化（已知盲区）：UTF-16 编码的文本含禁词会因含 NUL 被跳过（与 grep -I 行为一致）', () => {
    const d = freshDist()
    writeFileSync(join(d, 'u16.js'), Buffer.from('Rhine', 'utf16le'))
    const r = runGuard(sandbox)
    expect(r.code).toBe(0)
  })

  it('不误报：只含 denied（无 --）或 Rhin 这类近似词的产物通过', () => {
    const d = freshDist()
    writeFileSync(join(d, 'ok.js'), 'denied access\nRhin\nfonts.googleapi\n')
    const r = runGuard(sandbox)
    expect(r.code).toBe(0)
  })

  it('--denied 残留：文本产物中出现即退出 1，并提示已删除令牌', () => {
    const d = freshDist()
    writeFileSync(join(d, 'cli.js'), 'const flags = ["--denied"]\n')
    const r = runGuard(sandbox)
    expect(r.code).toBe(1)
    expect(r.err).toContain('已删除的 --denied 令牌')
    expect(r.err).toContain('cli.js')
  })

  it('--denied 残留：含 NUL 的二进制产物被跳过（与 residue 检测逻辑一致）', () => {
    const d = freshDist()
    writeFileSync(join(d, 'blob.bin'), Buffer.concat([Buffer.from([0]), Buffer.from('--denied')]))
    const r = runGuard(sandbox)
    expect(r.code).toBe(0)
  })

  it('禁词优先于 --denied 检测：两者同时存在时先报禁词并退出 1', () => {
    const d = freshDist()
    writeFileSync(join(d, 'both.js'), 'Rhine --denied\n')
    const r = runGuard(sandbox)
    expect(r.code).toBe(1)
    expect(r.err).toContain('dist 含禁词')
    expect(r.err).not.toContain('--denied 令牌')
  })
})
