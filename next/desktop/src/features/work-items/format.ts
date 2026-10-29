const pad = (n: number) => String(n).padStart(2, '0')

/** ISO 时间 → 本地 `YYYY-MM-DD HH:mm`；无法解析原样返回，空值返回 `—`。 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return '大小未知'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** 工单类型 → 圆点颜色（CSS 变量）。未知类型用中性色。 */
export function kindColor(type: string | null | undefined): string {
  const t = (type ?? '').toLowerCase()
  if (t === 'bug') return 'var(--kind-bug)'
  if (t === 'task' || t === '任务') return 'var(--kind-task)'
  if (t === 'feature' || t === '功能') return 'var(--kind-feature)'
  if (t === 'user story' || t === '用户情景' || t === '用户故事') return 'var(--kind-story)'
  return 'var(--kind-default)'
}

/** ISO 时间 → 本地 `MM-DD`（列表行用）；无法解析原样返回，空值返回 `—`。 */
export function formatMonthDay(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** ISO 时间 → 本地 `MM-DD HH:mm`（评论时间用）；无法解析原样返回，空值返回 `—`。 */
export function formatShort(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 姓名 → 头像里的两个字母：按 空格 _ . - 分词取各词首字，只有一个词时取前两个字符。 */
export function initials(name: string | null | undefined): string {
  const s = (name ?? '').trim()
  if (!s) return '?'
  const words = s.split(/[\s_.-]+/).filter(Boolean)
  const out = words.length > 1 ? words[0]!.charAt(0) + words[1]!.charAt(0) : s.slice(0, 2)
  return out.toUpperCase()
}
