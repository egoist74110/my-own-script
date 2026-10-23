/** 页签 id 只用于 aria 关联：把 value 里不安全的字符转成 `_<码点>`，保证是单个合法 IDREF。 */
function safe(value: string): string {
  return Array.from(value)
    .map((c) => (/[A-Za-z0-9-]/.test(c) ? c : `_${c.codePointAt(0)!.toString(16)}`))
    .join('')
}

/** `SegmentedControl` 传 `panelId` 时各 trigger 的 id；页面里承载内容的 tabpanel 用它设 `aria-labelledby`。 */
export function tabTriggerId(panelId: string, value: string): string {
  return `${panelId}-tab-${safe(value)}`
}
