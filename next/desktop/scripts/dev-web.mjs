// `pnpm dev:web`：拉起 ../backend 后端 → 解析 READY 行 → 以环境变量启动 vite → 退出时回收后端。
// token 只经子进程环境变量传给 vite，不写文件、不进 URL、不打印。
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'
import { parseReadyLine } from './ready-line.mjs'

const desktopDir = fileURLToPath(new URL('..', import.meta.url))
const backendDir = fileURLToPath(new URL('../../backend', import.meta.url))
// 隔离环境（S1/S3 合同）：临时数据目录、仓库内假旧配置、内存凭据 + 假 PAT；绝不落到真实目录与 Keychain。
const dataDir = mkdtempSync(join(tmpdir(), 'toolbox-dev-web-'))
const taskRootDir = mkdtempSync(join(tmpdir(), 'toolbox-dev-task-root-'))
const legacyDir = join(backendDir, 'tests', 'fixtures', 'legacy')
const fakeCredentials = join(backendDir, 'tests', 'fixtures', 'dev-credentials.json')
// 本地假 ADO（S2/S3 合同）：后端仅在 --dev + memory 凭据下接受，出站请求改读 fixture，不连任何真实服务。
const fakeAdo = join(backendDir, 'tests', 'fixtures', 'fake-ado')
function removeTempDirs() {
  try {
    rmSync(dataDir, { recursive: true, force: true })
  } catch {
    // 临时目录清理失败不影响退出
  }
  try {
    rmSync(taskRootDir, { recursive: true, force: true })
  } catch {
    // 临时目录清理失败不影响退出
  }
}
const READY_TIMEOUT_MS = 20_000
const STOP_GRACE_MS = 5_000

/** @type {import('node:child_process').ChildProcess | null} */
let backend = null
/** @type {import('node:child_process').ChildProcess | null} */
let vite = null
let shuttingDown = false

function exited(child) {
  return child.exitCode !== null || child.signalCode !== null
}

function waitExit(child, ms) {
  return new Promise((resolve) => {
    if (exited(child)) return resolve(true)
    const t = setTimeout(() => resolve(false), ms)
    child.once('exit', () => {
      clearTimeout(t)
      resolve(true)
    })
  })
}

async function stopChild(child, { closeStdin = false } = {}) {
  if (!child || exited(child)) return
  if (closeStdin) child.stdin?.end()
  child.kill('SIGTERM')
  if (!(await waitExit(child, STOP_GRACE_MS))) {
    child.kill('SIGKILL')
    await waitExit(child, 2_000)
  }
}

async function shutdown(code) {
  if (shuttingDown) return
  shuttingDown = true
  await stopChild(vite)
  await stopChild(backend, { closeStdin: true })
  removeTempDirs()
  process.exit(code)
}

process.on('SIGINT', () => void shutdown(130))
process.on('SIGTERM', () => void shutdown(143))
process.on('exit', () => {
  // 兜底：同步路径下尽量不留子进程
  for (const c of [vite, backend]) if (c && !exited(c)) c.kill('SIGKILL')
  removeTempDirs()
})

function startBackend() {
  return new Promise((resolve, reject) => {
    backend = spawn('uv', ['run', 'python', '-m', 'toolbox_backend', '--dev'], {
      cwd: backendDir,
      env: {
        ...process.env,
        UV_PYTHON_DOWNLOADS: 'never',
        TOOLBOX_DATA_DIR: dataDir,
        TOOLBOX_LEGACY_CONFIG_DIR: legacyDir,
        TOOLBOX_CREDENTIALS: 'memory',
        TOOLBOX_DEV_FAKE_CREDENTIALS: fakeCredentials,
        TOOLBOX_DEV_FAKE_ADO: fakeAdo,
        TOOLBOX_DEV_TASK_ROOT: taskRootDir,
      },
      stdio: ['pipe', 'pipe', 'inherit'],
    })
    const timer = setTimeout(
      () => reject(new Error(`后端 ${READY_TIMEOUT_MS / 1000}s 内未输出 READY 行`)),
      READY_TIMEOUT_MS,
    )
    backend.once('error', (e) => {
      clearTimeout(timer)
      reject(e)
    })
    backend.once('exit', (code) => {
      clearTimeout(timer)
      if (!shuttingDown) reject(new Error(`后端提前退出 (code ${code})`))
    })
    const rl = createInterface({ input: backend.stdout })
    rl.on('line', (line) => {
      const ready = parseReadyLine(line)
      if (ready) {
        clearTimeout(timer)
        resolve(ready)
      }
    })
  })
}

try {
  const ready = await startBackend()
  console.error(`[dev:web] backend ready: pid=${ready.pid} port=${ready.port}`)
  vite = spawn('pnpm', ['exec', 'vite'], {
    cwd: desktopDir,
    env: {
      ...process.env,
      VITE_TOOLBOX_PORT: String(ready.port),
      VITE_TOOLBOX_TOKEN: ready.token,
    },
    stdio: 'inherit',
  })
  vite.once('exit', (code) => void shutdown(code ?? 0))
  backend.once('exit', () => void shutdown(1))
} catch (e) {
  console.error(`[dev:web] ${e instanceof Error ? e.message : String(e)}`)
  await shutdown(1)
}
