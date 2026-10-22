// 媒体 blob 缓存（页面级）：把后端登记的 media id 取成 blob: URL，同一缓存内相同 id 复用一个 blob。
// 缓存的持有者（工单详情）卸载或切换工单时调用 clear()：中止进行中的请求并 revokeObjectURL 全部 blob。
// 请求只带 Bearer 头；token 与原始附件地址都不会出现在任何 URL 里（只有后端发的不透明 id）。
import { reactive, ref, type InjectionKey, type Ref } from 'vue'
import type { ApiClient } from '@/api/client'

export type MediaStatus = 'loading' | 'ready' | 'error'

export interface MediaEntry {
  status: MediaStatus
  /** blob: URL（status=ready 时）。 */
  url: string | null
  /** 后端错误 code（status=error 时），如 media_expired / unsupported_media。 */
  code: string | null
  category: string | null
}

export interface MediaFailure {
  code: string
  category: string | null
}

export interface MediaCache {
  /**
   * 取（必要时发起加载）一个 media id 的条目；返回响应式对象。
   * 传 `owner` 表示该使用方当前引用这个 id：「已过期」计数只统计仍被引用的失败 id。
   */
  get(id: string, owner?: object): MediaEntry
  /** 使用方不再引用其全部 id（重新渲染前、卸载时调用）。 */
  release(owner: object): void
  /** 取附件字节并触发浏览器下载；失败返回错误。 */
  download(id: string, name: string): Promise<MediaFailure | null>
  /** 丢弃失败条目（刷新详情后让它们能重新加载）。 */
  forgetFailed(): void
  /** media_expired 条目数（页面据此提示“刷新详情”）。 */
  readonly expired: Ref<number>
  /** forgetFailed() 每调用一次加一：渲染方据此重新挂接（失败条目被丢弃，需重新 get）。 */
  readonly generation: Ref<number>
  /** 中止进行中的请求并 revoke 全部 blob；之后 get() 只返回空的 loading 条目。 */
  clear(): void
}

export const mediaCacheKey: InjectionKey<MediaCache> = Symbol('media-cache')

const MAX_PARALLEL = 4
const DOWNLOAD_REVOKE_MS = 10_000

type Getter = () => ApiClient | null

async function fetchBlob(
  api: ApiClient,
  id: string,
  signal: AbortSignal,
): Promise<{ blob: Blob } | MediaFailure> {
  let result
  try {
    result = await api.GET('/api/work-items/media/{media_id}', {
      params: { path: { media_id: id } },
      parseAs: 'blob',
      signal,
    })
  } catch {
    return { code: 'network', category: null }
  }
  if (result.error !== undefined || !result.response.ok) {
    const body = result.error as { detail?: { code?: unknown; category?: unknown } } | undefined
    const d = body?.detail
    return {
      code: typeof d?.code === 'string' ? d.code : 'unknown',
      category: typeof d?.category === 'string' ? d.category : null,
    }
  }
  return { blob: result.data as Blob }
}

export function createMediaCache(getApi: Getter): MediaCache {
  const entries = new Map<string, MediaEntry>()
  const urls = new Set<string>()
  const controllers = new Set<AbortController>()
  const timers = new Set<ReturnType<typeof setTimeout>>()
  const queue: (() => void)[] = []
  const expired = ref(0)
  const owners = new Map<object, Set<string>>()
  const unowned = new Set<string>() // 未声明使用方的 get()：视为一直被引用
  const generation = ref(0)
  let running = 0
  let disposed = false

  function pump() {
    while (!disposed && running < MAX_PARALLEL && queue.length) queue.shift()!()
  }

  function revoke(url: string) {
    if (urls.delete(url)) URL.revokeObjectURL(url)
  }

  function load(id: string, entry: MediaEntry) {
    queue.push(() => {
      running++
      const ctrl = new AbortController()
      controllers.add(ctrl)
      const api = getApi()
      const done = (r: { blob: Blob } | MediaFailure) => {
        controllers.delete(ctrl)
        running--
        if (disposed) return
        if ('blob' in r) {
          const url = URL.createObjectURL(r.blob)
          urls.add(url)
          entry.url = url
          entry.status = 'ready'
        } else {
          entry.status = 'error'
          entry.code = r.code
          entry.category = r.category
          recount()
        }
        pump()
      }
      if (!api) return done({ code: 'network', category: null })
      void fetchBlob(api, id, ctrl.signal).then(done)
    })
    pump()
  }

  /** 只统计当前仍被某个使用方引用、且已失败为 media_expired 的 id。 */
  function recount() {
    const live = new Set<string>(unowned)
    for (const set of owners.values()) for (const id of set) live.add(id)
    let n = 0
    for (const id of live) {
      const e = entries.get(id)
      if (e && e.status === 'error' && e.code === 'media_expired') n++
    }
    expired.value = n
  }

  function release(owner: object) {
    if (owners.delete(owner)) recount()
  }

  function get(id: string, owner?: object): MediaEntry {
    if (owner && !disposed) {
      let set = owners.get(owner)
      if (!set) owners.set(owner, (set = new Set()))
      if (!set.has(id)) {
        set.add(id)
        queueMicrotask(recount) // 渲染期间不直接写响应式计数
      }
    }
    if (!owner) unowned.add(id)
    const hit = entries.get(id)
    if (hit) return hit
    const entry = reactive<MediaEntry>({ status: 'loading', url: null, code: null, category: null })
    if (disposed) return entry
    entries.set(id, entry)
    load(id, entry)
    return entry
  }

  async function download(id: string, name: string): Promise<MediaFailure | null> {
    const api = getApi()
    if (!api || disposed) return { code: 'network', category: null }
    const ctrl = new AbortController()
    controllers.add(ctrl)
    const r = await fetchBlob(api, id, ctrl.signal)
    controllers.delete(ctrl)
    if (disposed) return null
    if (!('blob' in r)) return r
    const url = URL.createObjectURL(r.blob)
    urls.add(url)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.rel = 'noopener'
    a.click()
    const t = setTimeout(() => {
      timers.delete(t)
      revoke(url)
    }, DOWNLOAD_REVOKE_MS)
    timers.add(t)
    return null
  }

  function forgetFailed() {
    for (const [id, e] of entries) if (e.status === 'error') entries.delete(id)
    recount()
    generation.value++
  }

  function clear() {
    disposed = true
    queue.length = 0
    for (const c of controllers) c.abort()
    controllers.clear()
    for (const t of timers) clearTimeout(t)
    timers.clear()
    for (const u of [...urls]) revoke(u)
    entries.clear()
    owners.clear()
    unowned.clear()
  }

  return { get, release, download, forgetFailed, expired, generation, clear }
}

/** 媒体失败占位文案（固定文案，不含任何远端内容）。 */
export function mediaFailureText(code: string | null, category: string | null): string {
  switch (code) {
    case 'media_expired':
      return '图片已过期'
    case 'unsupported_media':
      return '非图片，可下载'
    case 'no_credential':
      return '该代码库未配置 PAT'
    case 'busy':
      return '服务繁忙，图片未加载'
    case 'ado_request_failed':
      return category === 'blocked_origin' ? '图片被拦截' : '图片加载失败'
    default:
      return '图片加载失败'
  }
}
