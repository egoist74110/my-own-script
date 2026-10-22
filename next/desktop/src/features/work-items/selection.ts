// 工单页界面选择的持久化：localStorage 只存 {project_id, column}（非敏感）。读写都包 try/catch。
import { COLUMNS } from './api'

export const SELECTION_KEY = 'toolbox.work-items.selection'

export interface Selection {
  project_id: string | null
  column: string | null
}

export function loadSelection(): Selection {
  const empty: Selection = { project_id: null, column: null }
  try {
    const raw = localStorage.getItem(SELECTION_KEY)
    if (!raw) return empty
    const v = JSON.parse(raw) as unknown
    if (typeof v !== 'object' || v === null) return empty
    const o = v as Record<string, unknown>
    return {
      project_id: typeof o.project_id === 'string' ? o.project_id : null,
      column:
        typeof o.column === 'string' && (COLUMNS as readonly string[]).includes(o.column)
          ? o.column
          : null,
    }
  } catch {
    return empty
  }
}

export function saveSelection(sel: { project_id: string; column: string }): void {
  try {
    localStorage.setItem(
      SELECTION_KEY,
      JSON.stringify({ project_id: sel.project_id, column: sel.column }),
    )
  } catch {
    // 存储不可用（隐私模式、被禁用）：忽略，页面照常工作
  }
}
