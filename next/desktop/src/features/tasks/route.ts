// 「线路图」的纯函数：仓库线路色、步骤 → 站点、站点 → 迷你线路圆点。
// 一次运行 = 一趟列车，步骤是站点；终态运行里没走到的站一律显示“没有执行”，不得再转圈。
import {
  formatDuration,
  type EffectView,
  type RunStatus,
  type StepView,
  type TargetInput,
} from './api'

/** 线路色板：前四个是 Event / Front / VIP / API 固定色，后四个给其余仓库按 hash 取。取自 tokens.css 的 --l-*。 */
export const LINE_PALETTE = [
  'var(--l-event)',
  'var(--l-front)',
  'var(--l-vip)',
  'var(--l-api)',
  'var(--l-5)',
  'var(--l-6)',
  'var(--l-7)',
  'var(--l-8)',
] as const

/** 名称里带这些关键词的仓库使用固定线路色（先匹配先得；API 先于 Front，避免 front_api 落到 Front）。 */
const PRESET_LINES: ReadonlyArray<readonly [RegExp, number]> = [
  [/event/i, 0],
  [/vip/i, 2],
  [/api/i, 3],
  [/front/i, 1],
]

function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}

/** 仓库 → 线路色（CSS 颜色值）。同名仓库永远同色；其余仓库按 hash 落在后四色里，不与固定四色混淆。 */
export function repoLineColor(repoName?: string | null): string {
  const name = (repoName ?? '').trim()
  if (!name) return LINE_PALETTE[7]
  for (const [re, idx] of PRESET_LINES) if (re.test(name)) return LINE_PALETTE[idx]!
  return LINE_PALETTE[4 + (hash(name.toLowerCase()) % 4)]!
}

export type StationState = 'done' | 'here' | 'fail' | 'verify' | 'skip' | 'wait'
/** 迷你线路上圆点的状态。 */
export type DotState = 'ok' | 'run' | 'bad' | 'warn' | 'idle'

export function isRunActive(status?: RunStatus | null): boolean {
  return status === 'queued' || status === 'running' || status === 'cancelling'
}

/**
 * 步骤状态 + 所属运行状态 → 站点状态。
 * 运行已经不在活动态（成功/失败/取消/需核实）时，不是 succeeded/failed 的步骤都没有真正执行：
 * pending / running / skipped 一律是 skip（“没有执行”）；唯一例外是需核实的运行里仍标 running 的步骤，显示需核实。
 */
export function stationState(
  step: Pick<StepView, 'status'>,
  runStatus?: RunStatus | null,
): StationState {
  switch (step.status) {
    case 'succeeded':
      return 'done'
    case 'failed':
      return 'fail'
    case 'unknown':
      return 'verify'
    case 'skipped':
      return 'skip'
    default:
      break
  }
  if (isRunActive(runStatus)) return step.status === 'running' ? 'here' : 'wait'
  if (runStatus === 'unknown' && step.status === 'running') return 'verify'
  return 'skip'
}

/** 运行快照里的目标、已发生的远端副作用和运行结果说明：让站点能写目标名、构建号、Release 号和失败原因。 */
export interface StationContext {
  /** 运行快照 task_snapshot.targets，下标与步骤的 target_index 对应。 */
  targets?: TargetInput[] | null
  effects?: EffectView[] | null
  /** 运行的 summary（失败原因）。 */
  summary?: string | null
}

/** 站点标题：有目标名称就写“测试 · 构建”，取不到才回退“目标 N 构建”。 */
export function stepName(
  step: Pick<StepView, 'kind' | 'target_index'>,
  targetName?: string | null,
): string {
  const named = targetName?.trim()
  const n =
    step.target_index !== null ? (named ? `${named} · ` : `目标 ${step.target_index + 1} `) : ''
  switch (step.kind) {
    case 'git':
      return 'Git 同步'
    case 'build':
      return `${n}构建`
    case 'release':
      return `${n}发布`
    case 'rollback':
      return `${n}回滚`
    default:
      return step.kind
  }
}

function cp(step: StepView): Record<string, unknown> {
  return (step.checkpoint ?? {}) as Record<string, unknown>
}

/** 站名下方的一行小字：已完成写构建号/用时，当前站写进度，没走到的写“没有执行”。 */
export function stationSub(
  step: StepView,
  state: StationState,
  nowMs = Date.now(),
  ctx?: StationContext,
): string {
  const made = createdId(step, ctx)
  if (made && (step.kind === 'release' || state !== 'done')) {
    return createdSub(step, state, made, ctx, nowMs)
  }
  const c = cp(step)
  const duration = formatDuration(step.started_at, step.finished_at, nowMs)
  const hasDuration = Boolean(step.started_at)
  switch (state) {
    case 'skip':
      return '没有执行'
    case 'wait':
      return '等待中'
    case 'verify':
      return '需核实'
    case 'fail':
      return hasDuration ? `失败，${duration}` : '失败'
    case 'here': {
      const what = step.kind === 'git' ? '同步中' : step.kind === 'build' ? '构建中' : '部署中'
      return hasDuration ? `${what} ${duration}` : what
    }
    case 'done': {
      const parts: string[] = []
      const summary = typeof c.summary === 'string' ? c.summary.trim() : ''
      if (step.kind === 'build' && (c.build_id ?? c.definition_id)) {
        parts.push(`#${String(c.build_id ?? c.definition_id)}`)
      } else if (step.kind === 'git' && c.expected_commit) {
        parts.push(String(c.expected_commit).slice(0, 7))
      } else if ((step.kind === 'release' || step.kind === 'rollback') && c.release_id) {
        parts.push(`Release-${String(c.release_id)}`)
      } else if (summary) {
        // 没有构建号/版本号可写时，用服务给的一句结果说明
        parts.push(summary)
      }
      if (hasDuration) parts.push(duration)
      return parts.join('，') || '已完成'
    }
  }
}

export interface Station {
  key: string
  kind: string
  name: string
  state: StationState
  sub: string
  /** 第二行小字：构建定义名 / 发布到的环境名。 */
  detail?: string
  /** ADO 链接（数据里有才有）。 */
  link?: string
}

function targetOf(step: StepView, ctx?: StationContext): TargetInput | null {
  if (step.target_index === null) return null
  return ctx?.targets?.[step.target_index] ?? null
}

/** 该步骤已在 ADO 创建的对象编号：先看远端副作用的 remote_id，再看步骤检查点。 */
function createdId(step: StepView, ctx?: StationContext): string | null {
  const kind =
    step.kind === 'build' ? 'build_create' : step.kind === 'release' ? 'release_create' : null
  if (!kind) return null
  const fx = (ctx?.effects ?? []).find(
    (e) => e.step_no === step.step_no && e.kind === kind && e.remote_id && e.state !== 'rejected',
  )
  if (fx?.remote_id) return String(fx.remote_id)
  const c = cp(step)
  const v = step.kind === 'build' ? c.build_id : c.release_id
  return v !== undefined && v !== null && v !== '' ? String(v) : null
}

function linkOf(step: StepView): string | undefined {
  const c = cp(step)
  for (const k of ['web_url', 'url', 'build_url', 'release_url']) {
    const v = c[k]
    if (typeof v === 'string' && /^https?:\/\//i.test(v)) return v
  }
  return undefined
}

/**
 * 有 Release / 构建在 ADO 创建、但步骤没走完的站：不写“没有执行”，写已创建的编号和真实进度。
 * 发布站按状态写“未部署 / 部署中 / 已部署 / 部署失败”；失败时附上运行给的具体原因。
 */
function createdSub(
  step: StepView,
  state: StationState,
  id: string,
  ctx: StationContext | undefined,
  nowMs: number,
): string {
  const reason = state === 'fail' ? (ctx?.summary ?? '').trim() : ''
  const tail = reason ? `：${reason}` : ''
  if (step.kind === 'build') {
    const duration = step.started_at ? formatDuration(step.started_at, step.finished_at, nowMs) : ''
    switch (state) {
      case 'done':
        return duration ? `#${id}，${duration}` : `#${id}`
      case 'here':
        return `#${id}，构建中`
      case 'fail':
        return `#${id}，构建失败${tail}`
      case 'verify':
        return `#${id}，需核实`
      default:
        return `#${id}，未完成`
    }
  }
  const deployed =
    step.status === 'succeeded' ||
    (ctx?.effects ?? []).some(
      (e) => e.step_no === step.step_no && e.kind === 'env_deploy' && e.state === 'confirmed',
    )
  const deploy = deployed
    ? '已部署'
    : state === 'here'
      ? '部署中'
      : step.status === 'failed'
        ? '部署失败'
        : state === 'verify'
          ? '需核实'
          : '未部署'
  return `Release #${id} 已创建，${deploy}${tail}`
}

export function buildStations(
  steps: StepView[],
  runStatus?: RunStatus | null,
  nowMs = Date.now(),
  ctx?: StationContext,
): Station[] {
  return steps.map((s) => {
    let state = stationState(s, runStatus)
    const made = createdId(s, ctx)
    // 已经在 ADO 创建了东西却被判成“没有执行”：按运行结果显示失败/需核实
    if (made && state === 'skip') {
      if (runStatus === 'failed') state = 'fail'
      else if (runStatus === 'unknown') state = 'verify'
    }
    const t = targetOf(s, ctx)
    const detail =
      s.kind === 'build'
        ? t?.build_name
          ? `构建定义：${t.build_name}`
          : undefined
        : s.kind === 'release' || s.kind === 'rollback'
          ? (t?.release_stage_names ?? []).length
            ? `环境：${(t!.release_stage_names ?? []).join('、')}`
            : undefined
          : undefined
    return {
      key: `${s.step_no}`,
      kind: s.kind,
      name: stepName(s, t?.name),
      state,
      sub: stationSub(s, state, nowMs, ctx),
      detail,
      link: s.kind === 'build' ? linkOf(s) : undefined,
    }
  })
}

export function stationToDot(state: StationState): DotState {
  switch (state) {
    case 'done':
      return 'ok'
    case 'here':
      return 'run'
    case 'fail':
      return 'bad'
    case 'verify':
      return 'warn'
    default:
      return 'idle'
  }
}

/** 运行的迷你线路：有步骤用步骤；没有步骤（列表接口只给了概要）时，按运行结果给一条粗略线路。 */
export function runDots(
  steps: StepView[] | undefined,
  status: RunStatus | null | undefined,
  fallbackCount = 3,
): DotState[] {
  if (steps && steps.length > 0) return steps.map((s) => stationToDot(stationState(s, status)))
  return coarseDots(status, fallbackCount)
}

/** 只知道运行结果、不知道停在哪一站时的粗略线路：不假装知道哪一站出了问题，整条线统一表示结果。 */
export function coarseDots(status: RunStatus | null | undefined, count = 3): DotState[] {
  const n = Math.max(1, count)
  const fill = (d: DotState): DotState[] => Array.from({ length: n }, () => d)
  switch (status) {
    case 'succeeded':
      return fill('ok')
    case 'failed':
      return fill('bad')
    case 'unknown':
      return fill('warn')
    case 'running':
    case 'cancelling':
    case 'queued': {
      const dots = fill('idle')
      dots[0] = 'run'
      return dots
    }
    default:
      return fill('idle')
  }
}
