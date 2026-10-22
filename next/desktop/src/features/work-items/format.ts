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
