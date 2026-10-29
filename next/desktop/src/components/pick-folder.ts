// 文件夹选择：Tauri 内走官方 dialog 插件（系统原生选择器）；单测/浏览器里没有这个能力，调用方据此隐藏按钮。

export function canPickFolder(): boolean {
  return typeof (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ === 'object'
}

/** 弹出系统“选择文件夹”；用户取消或出错返回 null。 */
export async function pickFolder(): Promise<string | null> {
  if (!canPickFolder()) return null
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const res = await open({ directory: true, multiple: false })
    return typeof res === 'string' ? res : null
  } catch {
    return null
  }
}
