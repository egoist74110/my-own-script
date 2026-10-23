// 设置页检查器的「编辑会话 + 基线」共用逻辑（library / project / 本地仓库）。
//
// 会话：每次开始编辑（选中条目变化或新建）递增；写请求发出时捕获当时的会话，
//   响应与回调只在会话仍是当前会话时作用于组件状态（CR-S1B-005）。
// 草稿：每次开始会话都从当前服务器数据初始化，不跨会话保留。若开始时数据正在刷新或有写入在途
//   （缓存可能是旧的），则在刷新/写入落定后，把用户尚未改动的字段对齐到服务器值。
// 基线：开始编辑时的字段值 + 当时的 revision。外部改动不改基线字段；但若刷新后服务器上该条目的
//   字段与基线完全相同（revision 只因其它条目/非 patch 写入前进），静默把基线 revision 前移，
//   不触发多余的 409；字段不同才在保存时走 409 合并（mergeConflict）。
import { watch, type Ref } from 'vue'
import type { SettingsContext } from './useSettings'

type Fields<K extends string> = Record<K, string>

export function useEditSession<K extends string>(
  ctx: SettingsContext,
  o: {
    /** 草稿输入（比较时取 trim 后的值）。 */
    drafts: Record<K, Ref<string>>
    /** 该条目当前的服务器字段；新建或条目已不存在时为 null。 */
    server: () => Fields<K> | null
    /** 新建时的草稿初值（缺省空串）。 */
    defaults?: () => Partial<Fields<K>>
    /** 自定义 revision 获取器（缺省读取 ctx.ado.data.value?.revision）。 */
    revision?: () => number | null
    /** 自定义 isFetching 获取器（缺省读取 ctx.ado.isFetching.value）。 */
    isFetching?: () => boolean
    /** 自定义触发对齐的 watch 目标（缺省读取 ctx.ado.data.value）。 */
    watchTarget?: () => unknown
  },
) {
  const keys = Object.keys(o.drafts) as K[]
  let session = 0
  let settling = false
  let baseline: { fields: Fields<K>; revision: number | null } = {
    fields: Object.fromEntries(keys.map((k) => [k, ''])) as Fields<K>,
    revision: null,
  }

  const serverRevision = () => (o.revision ? o.revision() : (ctx.ado.data.value?.revision ?? null))
  const isFetching = () => (o.isFetching ? o.isFetching() : ctx.ado.isFetching.value)
  const watchTarget = o.watchTarget ? o.watchTarget : () => ctx.ado.data.value
  const draftOf = (k: K) => o.drafts[k].value.trim()
  const sameAsBaseline = (srv: Fields<K>) => keys.every((k) => srv[k] === baseline.fields[k])

  /** 基线字段与服务器相同而 revision 落后：静默前移。 */
  function reconcile() {
    const srv = o.server()
    const rev = serverRevision()
    if (!srv || rev === null || baseline.revision === null || rev <= baseline.revision) return
    if (sameAsBaseline(srv)) baseline.revision = rev
  }

  /** 用户没改过的字段换成服务器新值，基线整体更新为服务器当前值。 */
  function adopt(srv: Fields<K>, rev: number) {
    for (const k of keys) if (draftOf(k) === baseline.fields[k]) o.drafts[k].value = srv[k]
    baseline = { fields: { ...srv }, revision: rev }
  }

  /** 开始一次新的编辑会话；返回新会话号。 */
  function begin(): number {
    session++
    const srv = o.server()
    const seed = (srv ?? {
      ...Object.fromEntries(keys.map((k) => [k, ''])),
      ...o.defaults?.(),
    }) as Fields<K>
    baseline = { fields: { ...seed }, revision: serverRevision() }
    for (const k of keys) o.drafts[k].value = seed[k]
    settling = ctx.busy.value || isFetching()
    return session
  }

  watch(watchTarget, reconcile)
  watch(
    () => ctx.busy.value || isFetching(),
    (working) => {
      if (working || !settling) return
      settling = false
      const srv = o.server()
      const rev = serverRevision()
      if (!srv || rev === null || sameAsBaseline(srv)) return
      // 用户已改的字段若服务器上也变了（与基线不同）：不 adopt，基线与 revision 不动，
      // 下一次保存得到 409 并走合并提示（CR-S2C-001）；否则替换未改字段、前移基线。
      if (keys.some((k) => draftOf(k) !== baseline.fields[k] && srv[k] !== baseline.fields[k]))
        return
      adopt(srv, rev)
    },
  )

  return {
    begin,
    current: () => session,
    /** 本次会话的基线 revision（可能为 null：尚未加载）。 */
    revisionOpt: () => (baseline.revision !== null ? { revision: baseline.revision } : {}),
    /** 基线中的字段值。 */
    base: (k: K) => baseline.fields[k],
    /** 已提交字段（trim 后与基线不同）。 */
    changed(): Partial<Fields<K>> {
      const body: Partial<Fields<K>> = {}
      for (const k of keys) if (draftOf(k) !== baseline.fields[k]) body[k] = draftOf(k)
      return body
    },
    /** revision_conflict 后：用户改过的字段保留，未改字段换成服务器新值，基线整体更新。 */
    mergeConflict(s: number): boolean {
      if (s !== session) return false
      const srv = o.server()
      const rev = serverRevision()
      if (!srv || rev === null) return false
      adopt(srv, rev)
      return true
    },
    /** 本会话的 patch 写入成功：基线吸收已提交字段，revision 取响应值。 */
    saved(s: number, body: Partial<Fields<K>>, revision: number) {
      if (s !== session) return
      baseline = { fields: { ...baseline.fields, ...body }, revision }
      reconcile()
    },
    /** 非 patch 写入（PAT、设为当前）用缓存 revision：若只有本次写入推进了 revision，基线随之前进。 */
    advance(s: number, r: { ok: boolean; rev: number | null; data?: unknown }) {
      if (s !== session) return
      const d = r.data as { revision?: number } | undefined
      if (r.ok && r.rev !== null && r.rev === baseline.revision && typeof d?.revision === 'number')
        baseline.revision = d.revision
      reconcile()
    },
  }
}
