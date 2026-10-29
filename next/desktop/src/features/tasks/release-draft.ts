// 发布配置编辑草稿：向导与编辑器共用的“表单态”模型与转换。
// 表单态里列表字段用逗号分隔的文本（方便手填），提交时再转成数组。
import type { ReleaseBranch, ReleaseBranchInput, ReleaseTarget, ReleaseTargetInput } from './api'

export interface EditableTarget {
  /** 已有目标的稳定 id；新增目标为空，由服务端生成。 */
  id: string | null
  /** 仅供列表渲染的本地键，新增和已有目标都有。 */
  key: string
  name: string
  enabled: boolean
  build_kind: 'pipeline' | 'build'
  build_id: string
  build_name: string
  release_id: string
  release_name: string
  release_stage_ids: string
  release_stage_names: string
}

export interface EditableBranch {
  /** 已有分支的稳定 id；新增分支为空，由服务端生成。 */
  id: string | null
  /** 仅供列表渲染的本地键，新增和已有分支都有。 */
  key: string
  build_branch: string
  update_branches: string
  merges: string
  push_branches: string
  /** 是否展开编辑规则。 */
  open: boolean
}

let seq = 0

export function blankBranch(name: string, open = true): EditableBranch {
  return {
    id: null,
    key: `new-branch-${seq++}`,
    build_branch: name,
    update_branches: '',
    merges: '',
    push_branches: '',
    open,
  }
}

export function branchFromView(b: ReleaseBranch, open: boolean): EditableBranch {
  return {
    id: b.id,
    key: b.id,
    build_branch: b.build_branch ?? '',
    update_branches: b.update_branches?.join(', ') ?? '',
    merges: b.merges?.map((m) => `${m.source}:${m.target}`).join(', ') ?? '',
    push_branches: b.push_branches?.join(', ') ?? '',
    open,
  }
}

export function blankTarget(n: number): EditableTarget {
  return {
    id: null,
    key: `new-target-${seq++}`,
    name: `目标 ${n}`,
    enabled: true,
    build_kind: 'build',
    build_id: '',
    build_name: '',
    release_id: '',
    release_name: '',
    release_stage_ids: '',
    release_stage_names: '',
  }
}

export function targetFromView(t: ReleaseTarget): EditableTarget {
  return {
    id: t.id,
    key: t.id,
    name: t.name ?? '目标',
    enabled: t.enabled ?? true,
    build_kind: (t.build_kind as 'pipeline' | 'build') ?? 'build',
    build_id: t.build_id ? String(t.build_id) : '',
    build_name: t.build_name ?? '',
    release_id: t.release_id ? String(t.release_id) : '',
    release_name: t.release_name ?? '',
    release_stage_ids: t.release_stage_ids?.join(', ') ?? '',
    release_stage_names: t.release_stage_names?.join(', ') ?? '',
  }
}

/** 列表分隔符：半角逗号、中文逗号、顿号、换行。去空白、去空项、去重保序。 */
const LIST_SEP = /[,，、\n\r]+/
export function parseList(s: string): string[] {
  const out: string[] = []
  for (const x of s.split(LIST_SEP)) {
    const v = x.trim()
    if (v && !out.includes(v)) out.push(v)
  }
  return out
}

/** 合并规则「来源:目标」（也接受中文冒号）；格式不对的项原样收集到 bad，绝不丢弃。 */
export function analyzeMerges(s: string): {
  rules: Array<{ source: string; target: string }>
  bad: string[]
} {
  const rules: Array<{ source: string; target: string }> = []
  const bad: string[] = []
  for (const item of parseList(s)) {
    const parts = item.split(/[:：]/).map((x) => x.trim())
    if (parts.length === 2 && parts[0] && parts[1] && parts[0] !== parts[1]) {
      if (!rules.some((r) => r.source === parts[0] && r.target === parts[1]))
        rules.push({ source: parts[0], target: parts[1] })
    } else bad.push(item)
  }
  return { rules, bad }
}

export function toBranchInput(b: EditableBranch): ReleaseBranchInput {
  return {
    // 已有分支必须回传 id；新增分支省略 id
    ...(b.id ? { id: b.id } : {}),
    build_branch: b.build_branch.trim(),
    update_branches: parseList(b.update_branches),
    push_branches: parseList(b.push_branches),
    merges: analyzeMerges(b.merges).rules,
  }
}

export function toTargetInput(t: EditableTarget): ReleaseTargetInput {
  return {
    // 已有目标必须回传 id；新增目标省略 id
    ...(t.id ? { id: t.id } : {}),
    name: t.name.trim(),
    enabled: t.enabled,
    build_kind: t.build_kind,
    build_id: t.build_id.trim() || null,
    build_name: t.build_name.trim() || null,
    release_id: t.release_id.trim() || null,
    release_name: t.release_name.trim() || null,
    release_stage_ids: parseList(t.release_stage_ids),
    release_stage_names: parseList(t.release_stage_names),
  }
}

/** 构建分支名重复或为空的分支下标（同一配置里构建分支不能重复）。 */
export function duplicateBranchIndexes(branches: EditableBranch[]): Set<number> {
  const seen = new Map<string, number>()
  const dup = new Set<number>()
  branches.forEach((b, i) => {
    const key = b.build_branch.trim()
    if (!key) return
    if (seen.has(key)) {
      dup.add(i)
      dup.add(seen.get(key)!)
    } else seen.set(key, i)
  })
  return dup
}

/** 环境名里的分隔符会在“逗号分隔文本”里被拆开，换成空格；替换后为空就回退成 `环境 {id}`，保证 ids 与 names 等长。 */
export function safeStageName(n: string, id: string): string {
  return n.replace(/[,，、\n\r]+/g, ' ').trim() || `环境 ${id}`
}

/** 目标是否连到了 ADO：构建定义、Release 定义和至少一个环境都要有。 */
export function targetIsComplete(t: EditableTarget): boolean {
  return Boolean(
    t.build_id.trim() && t.release_id.trim() && parseList(t.release_stage_ids).length > 0,
  )
}

/** 目标的问题（给界面提示）；没问题返回 null。已有目标沿用服务端内容，只检查名称。 */
export function targetProblem(t: EditableTarget): string | null {
  if (!t.name.trim()) return '目标名称不能为空'
  if (!t.id && !targetIsComplete(t))
    return '新目标要有构建定义、Release 定义和至少一个环境，缺的补上后才能保存'
  return null
}
