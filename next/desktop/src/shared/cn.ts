import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * 类名合并工具。放在 `src/shared/` 而非 `src/lib/`：仓库根 .gitignore 的 `lib/` 规则会让 `src/lib/` 不入库。
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
