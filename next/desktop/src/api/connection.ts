// 后端连接信息来源：Tauri 命令 `backend_connection`，或 `pnpm dev:web` 注入的 dev 环境变量。
// token 只存在于内存：不写 localStorage、不进 URL、不进日志。

export interface BackendConnection {
  port: number
  token: string
}

export type TauriInvoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

export interface ConnectionSources {
  /** 返回 Tauri invoke；不在 Tauri 内返回 null。测试中可替换。 */
  getTauriInvoke: () => TauriInvoke | null
  /** dev 环境变量（默认 import.meta.env）。 */
  env: { VITE_TOOLBOX_PORT?: string; VITE_TOOLBOX_TOKEN?: string }
  /** 是否为 vite dev 模式（默认 import.meta.env.DEV）；为 false 时不读取 dev 变量，省略视为 true。 */
  dev?: boolean
}

export class ConnectionUnavailableError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ConnectionUnavailableError'
  }
}

export function defaultTauriInvoke(): TauriInvoke | null {
  const internals = (globalThis as { __TAURI_INTERNALS__?: { invoke?: TauriInvoke } })
    .__TAURI_INTERNALS__
  return typeof internals?.invoke === 'function' ? internals.invoke.bind(internals) : null
}

export function defaultSources(): ConnectionSources {
  return {
    getTauriInvoke: defaultTauriInvoke,
    env: import.meta.env.DEV ? import.meta.env : {},
    dev: import.meta.env.DEV,
  }
}

export function parseConnection(value: unknown): BackendConnection {
  if (typeof value !== 'object' || value === null) {
    throw new ConnectionUnavailableError('连接信息格式无效')
  }
  const { port, token } = value as { port?: unknown; token?: unknown }
  const portNum = typeof port === 'string' ? Number(port) : port
  if (
    typeof portNum !== 'number' ||
    !Number.isInteger(portNum) ||
    portNum < 1 ||
    portNum > 65535 ||
    typeof token !== 'string' ||
    token.length === 0
  ) {
    throw new ConnectionUnavailableError('连接信息格式无效')
  }
  return { port: portNum, token }
}

export async function getBackendConnection(
  sources: ConnectionSources = defaultSources(),
): Promise<BackendConnection> {
  const invoke = sources.getTauriInvoke()
  if (invoke) {
    return parseConnection(await invoke('backend_connection'))
  }
  // dev 变量只在 vite dev 中生效，避免构建时被内联进 dist。
  if (sources.dev === false) {
    throw new ConnectionUnavailableError('未检测到后端连接信息（非 Tauri 环境）')
  }
  const { VITE_TOOLBOX_PORT: port, VITE_TOOLBOX_TOKEN: token } = sources.env
  if (port && token) {
    return parseConnection({ port, token })
  }
  throw new ConnectionUnavailableError('未检测到后端连接信息（非 Tauri 环境且未设置 dev 变量）')
}

export function httpBase(conn: BackendConnection): string {
  return `http://127.0.0.1:${conn.port}`
}

export function wsUrl(conn: BackendConnection): string {
  return `ws://127.0.0.1:${conn.port}/ws/events`
}
