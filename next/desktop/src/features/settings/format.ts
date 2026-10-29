/** 设置页的时间显示：一律本地时间 MM-DD HH:mm，不露 ISO 原文；无法解析时给占位或原值。 */
const p2 = (n: number) => String(n).padStart(2, '0')

export function fmtLocal(v: string | number | null | undefined, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback
  // 数字按「秒」处理（与后端 checked_at 一致）
  const d = typeof v === 'number' ? new Date(v * 1000) : new Date(v)
  if (Number.isNaN(d.getTime())) return typeof v === 'string' ? v : fallback
  return `${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
}
