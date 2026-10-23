export type PillState =
  'queued' | 'running' | 'stopping' | 'success' | 'failed' | 'cancelled' | 'verify' | 'disabled'

export const PILL_LABEL: Record<PillState, string> = {
  queued: '排队中',
  running: '运行中',
  stopping: '停止中',
  success: '成功',
  failed: '失败',
  cancelled: '已取消',
  verify: '需核实',
  disabled: '已停用',
}
