// 终端 WebSocket 协议纯函数：认证、attach、分片输入、resize 夹取与二进制帧解析/去重

export function toBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString('base64')
  }
  let binary = ''
  const len = bytes.length
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]!)
  }
  return btoa(binary)
}

export function createAuthFrame(token: string): string {
  return JSON.stringify({ type: 'auth', token })
}

export function createAttachFrame(afterOffset: number | bigint): string {
  const offsetBig =
    typeof afterOffset === 'bigint'
      ? afterOffset
      : BigInt(Math.max(0, Math.floor(Number.isFinite(afterOffset) ? afterOffset : 0)))
  return `{"type":"attach","after_offset":${offsetBig.toString()}}`
}

export function createInputFrames(data: string, maxDecodedBytes = 16384): string[] {
  const encoder = new TextEncoder()
  const bytes = encoder.encode(data)
  if (bytes.length === 0) {
    return [JSON.stringify({ type: 'input', data: '' })]
  }
  const frames: string[] = []
  for (let offset = 0; offset < bytes.length; offset += maxDecodedBytes) {
    const chunk = bytes.slice(offset, offset + maxDecodedBytes)
    frames.push(JSON.stringify({ type: 'input', data: toBase64(chunk) }))
  }
  return frames
}

export function clampRows(rows: number): number {
  if (Number.isNaN(rows)) return 24
  if (rows === Number.POSITIVE_INFINITY) return 300
  if (rows === Number.NEGATIVE_INFINITY) return 5
  const r = Math.floor(rows)
  return Math.max(5, Math.min(300, Number.isFinite(r) ? r : 24))
}

export function clampCols(cols: number): number {
  if (Number.isNaN(cols)) return 80
  if (cols === Number.POSITIVE_INFINITY) return 500
  if (cols === Number.NEGATIVE_INFINITY) return 20
  const c = Math.floor(cols)
  return Math.max(20, Math.min(500, Number.isFinite(c) ? c : 80))
}

export function createResizeFrame(rows: number, cols: number): string {
  return JSON.stringify({
    type: 'resize',
    rows: clampRows(rows),
    cols: clampCols(cols),
  })
}

export interface ParsedFrame {
  offset: bigint
  payload: Uint8Array | null
  nextWatermark: bigint
}

/**
 * 解析后端终端输出二进制帧（8 字节大端 uint64 offset + 输出字节）
 * 根据当前水位 currentWatermark 进行去重和截取，保证重连或乱序时写入 xterm 的数据连续且不重复。
 */
export function parseBinaryFrame(
  buffer: ArrayBuffer | Uint8Array,
  currentWatermark: bigint,
): ParsedFrame {
  const isUint8 = buffer instanceof Uint8Array
  const byteLength = buffer.byteLength
  if (byteLength < 8) {
    return { offset: 0n, payload: null, nextWatermark: currentWatermark }
  }

  const arrBuffer = isUint8 ? buffer.buffer : buffer
  const byteOffset = isUint8 ? buffer.byteOffset : 0
  const view = new DataView(arrBuffer, byteOffset, byteLength)
  const offset = view.getBigUint64(0, false)
  const rawBytes = new Uint8Array(arrBuffer, byteOffset + 8, byteLength - 8)

  if (rawBytes.length === 0) {
    return {
      offset,
      payload: null,
      nextWatermark: offset > currentWatermark ? offset : currentWatermark,
    }
  }

  if (offset >= currentWatermark) {
    return {
      offset,
      payload: rawBytes,
      nextWatermark: offset + BigInt(rawBytes.length),
    }
  }

  const frameEnd = offset + BigInt(rawBytes.length)
  if (frameEnd <= currentWatermark) {
    // 已经完整接收过此段数据，去重丢弃
    return {
      offset,
      payload: null,
      nextWatermark: currentWatermark,
    }
  }

  // 部分重叠：截取未消费的后半段数据
  const skip = Number(currentWatermark - offset)
  const payload = rawBytes.slice(skip)
  return {
    offset,
    payload,
    nextWatermark: frameEnd,
  }
}

export function formatSessionState(state: string): string {
  switch (state) {
    case 'starting':
      return '启动中'
    case 'idle':
      return '空闲'
    case 'busy':
      return '运行中'
    case 'awaiting_approval':
      return '待审批'
    case 'closing':
      return '关闭中'
    case 'ended':
      return '已结束'
    case 'failed':
      return '失败'
    default:
      return state
  }
}

export function formatEndedReason(reason?: string | null): string {
  if (!reason) return '无'
  switch (reason) {
    case 'user_closed':
      return '用户关闭'
    case 'process_exited':
      return '进程退出'
    case 'interrupted_on_exit':
      return '退出时中断'
    case 'backend_restart':
      return '后端重启'
    case 'start_failed':
      return '启动失败'
    case 'limit':
      return '超出限额'
    default:
      return reason
  }
}

export const AI_ERROR_MESSAGES: Record<string, string> = {
  ai_session_limit: '活动终端会话已达上限（最多 6 个）',
  cli_not_found: '未找到对应的 AI CLI 可执行文件',
  repo_missing: '本地仓库不存在或已被删除',
  unsupported_cli: '该 CLI 不支持当前类型的会话',
  high_risk_ack_required: '高权限档位需要二次确认',
  ai_store_unavailable: 'AI 存储不可用（只读错误态）',
  ai_job_conflict: '已有 AI 升级任务正在运行，同时只允许一个升级任务',
  busy: '已有 AI 升级任务正在运行，同时只允许一个升级任务',
  builtin_profile: '内置配置不可删除',
  revision_conflict: '配置已被修改，请刷新后重试',
  not_found: '未找到请求的资源',
  validation_error: '输入参数格式不正确',
  conflict: '资源冲突，请稍后重试',
}

export function formatAiError(code?: string | null, fallback = '操作失败'): string {
  if (!code) return fallback
  return AI_ERROR_MESSAGES[code] || fallback
}
