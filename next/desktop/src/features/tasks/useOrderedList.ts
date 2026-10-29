// 列表排序：乐观更新 + 串行提交 + 失败回滚。
// 连续快速移动时，每次移动立刻改界面，但提交按顺序一条一条发（后一条等前一条完成并刷新出最新 revision），
// 不会并发打出过期 revision；任一条失败就丢弃后面排队的、回滚到服务端顺序并报错。
import { computed, ref, type Ref } from 'vue'

export function useOrderedList<T extends { id: string }>(
  source: Ref<T[]>,
  opts: {
    /** 提交新顺序（全部 id 恰好一次）；revision 在提交那一刻才读取。 */
    commit: (ids: string[], revision: number) => Promise<unknown>
    revision: () => number
    /** 出错传错误，开始新一次移动时传 null 清除。 */
    onError: (e: unknown) => void
  },
) {
  const pending = ref<string[] | null>(null)
  let chain: Promise<void> = Promise.resolve()
  let gen = 0
  let inflight = 0

  /** 界面显示的顺序：有未完成的移动时按乐观顺序，否则按服务端。 */
  const items = computed<T[]>(() => {
    const src = source.value
    const order = pending.value
    if (!order) return src
    const byId = new Map(src.map((x) => [x.id, x]))
    const out: T[] = []
    for (const id of order) {
      const it = byId.get(id)
      if (it) {
        out.push(it)
        byId.delete(id)
      }
    }
    for (const it of byId.values()) out.push(it)
    return out
  })

  function moveTo(id: string, index: number) {
    const ids = items.value.map((x) => x.id)
    const from = ids.indexOf(id)
    if (from < 0) return
    const to = Math.max(0, Math.min(ids.length - 1, index))
    if (from === to) return
    ids.splice(from, 1)
    ids.splice(to, 0, id)
    pending.value = ids
    opts.onError(null)
    const myGen = gen
    inflight++
    chain = chain.then(async () => {
      try {
        if (myGen !== gen) return // 前面有失败，这一条基于过期的乐观顺序，丢弃
        await opts.commit(ids, opts.revision())
      } catch (e) {
        gen++
        pending.value = null
        opts.onError(e)
      } finally {
        inflight--
        if (inflight === 0 && myGen === gen) pending.value = null
      }
    })
  }

  function moveBy(id: string, delta: number) {
    const from = items.value.findIndex((x) => x.id === id)
    if (from < 0) return
    moveTo(id, from + delta)
  }

  return { items, moveTo, moveBy }
}
