// 外链打开：WebView 本身永不导航。Tauri 内走 opener 插件（系统浏览器），dev:web 下 window.open + noopener。
// 只放行 http/https（opener 的 capability scope 同样只含这两类）；其余协议一律忽略。

function isTauri(): boolean {
  return typeof (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ === 'object'
}

/** 返回可安全打开的 http(s) 绝对地址；否则 null。 */
export function safeExternalUrl(raw: string): string | null {
  try {
    const u = new URL(raw)
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null
    if (u.username || u.password) return null
    return u.href
  } catch {
    return null
  }
}

export async function openExternal(raw: string): Promise<boolean> {
  const url = safeExternalUrl(raw)
  if (!url) return false
  if (isTauri()) {
    try {
      const { openUrl } = await import('@tauri-apps/plugin-opener')
      await openUrl(url)
      return true
    } catch {
      return false
    }
  }
  window.open(url, '_blank', 'noopener')
  return true
}
