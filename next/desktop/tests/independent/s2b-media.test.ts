// S2-B 独立测试：媒体 blob 缓存（createMediaCache）单元行为。假 ApiClient，不发真实请求。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '@/api/client'
import { createMediaCache, mediaFailureText, type MediaCache } from '@/components/media'

interface Pending {
  id: string
  signal: AbortSignal
  done: boolean
  settle: (r: unknown) => void
}

function fakeApi() {
  const pending: Pending[] = []
  const GET = vi.fn(
    (_path: string, init: { params: { path: { media_id: string } }; signal: AbortSignal }) =>
      new Promise((resolve) => {
        const p: Pending = {
          id: init.params.path.media_id,
          signal: init.signal,
          done: false,
          settle: (r) => {
            p.done = true
            resolve(r)
          },
        }
        pending.push(p)
      }),
  )
  return { api: { GET } as unknown as ApiClient, GET, pending }
}

const ok = () => ({ data: new Blob(['img']), response: new Response(null, { status: 200 }) })
const fail = (code: string, category?: string, status = 404) => ({
  error: { detail: { code, message: 'LEAK-MESSAGE', ...(category ? { category } : {}) } },
  response: new Response(null, { status }),
})

/** 让微任务跑够（不用 setTimeout，便于配合假定时器）。 */
async function tick(n = 30) {
  for (let i = 0; i < n; i++) await Promise.resolve()
}

let urlN = 0
let created: string[] = []
let revoked: string[] = []
beforeEach(() => {
  urlN = 0
  created = []
  revoked = []
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: () => {
      const u = `blob:fake/${++urlN}`
      created.push(u)
      return u
    },
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: (u: string) => {
      revoked.push(u)
    },
  })
})
afterEach(() => {
  delete (URL as unknown as Record<string, unknown>).createObjectURL
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL
  vi.useRealTimers()
})

describe('去重与并发上限', () => {
  it('同一 id 反复 get 只发一次请求，并返回同一个条目对象', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    const e1 = cache.get('m1')
    const e2 = cache.get('m1')
    await tick()
    expect(e1).toBe(e2)
    expect(f.GET).toHaveBeenCalledTimes(1)
  })

  it('同时在途的请求不超过 4 个；完成一个后补位下一个', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    for (let i = 0; i < 6; i++) cache.get(`m${i}`)
    await tick()
    expect(f.GET).toHaveBeenCalledTimes(4)
    f.pending[0]!.settle(ok())
    await tick()
    expect(f.GET).toHaveBeenCalledTimes(5)
    for (const p of f.pending) if (!p.done) p.settle(ok())
    await tick()
    expect(f.GET).toHaveBeenCalledTimes(6)
  })

  it('ready 后条目带 blob: URL；loading 阶段 url 为 null', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    const e = cache.get('m1')
    expect(e.status).toBe('loading')
    expect(e.url).toBeNull()
    f.pending[0]!.settle(ok())
    await tick()
    expect(e.status).toBe('ready')
    expect(e.url).toBe('blob:fake/1')
  })

  it('没有可用 api（未连接）时直接进入 network 错误，不发请求', async () => {
    const cache = createMediaCache(() => null)
    const e = cache.get('m1')
    await tick()
    expect(e.status).toBe('error')
    expect(e.code).toBe('network')
  })
})

describe('错误映射（只保留后端固定 code/category，不保留 message）', () => {
  it('media_expired 计入 expired 计数', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    const e = cache.get('m1')
    f.pending[0]!.settle(fail('media_expired'))
    await tick()
    expect(e.status).toBe('error')
    expect(e.code).toBe('media_expired')
    expect(cache.expired.value).toBe(1)
  })

  it('category 被带上；message 不进入条目', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    const e = cache.get('m1')
    f.pending[0]!.settle(fail('ado_request_failed', 'tls', 502))
    await tick()
    expect(e.code).toBe('ado_request_failed')
    expect(e.category).toBe('tls')
    expect(JSON.stringify(e)).not.toContain('LEAK-MESSAGE')
  })

  it('网络异常（fetch 抛错）映射为 network，且不保留原始异常文本', async () => {
    const GET = vi.fn(() => Promise.reject(new Error('socket hang up Bearer fake-token')))
    const cache = createMediaCache(() => ({ GET }) as unknown as ApiClient)
    const e = cache.get('m1')
    await tick()
    expect(e.code).toBe('network')
    expect(e.category).toBeNull()
    expect(JSON.stringify(e)).not.toContain('fake-token')
  })

  it('错误体不是对象（如字符串）映射为 unknown', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    const e = cache.get('m1')
    f.pending[0]!.settle({ error: 'boom', response: new Response(null, { status: 500 }) })
    await tick()
    expect(e.status).toBe('error')
    expect(e.code).toBe('unknown')
  })

  it('失败后不自动重试（同一条目保持 error，不再发请求）', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    cache.get('m1')
    f.pending[0]!.settle(fail('busy', undefined, 503))
    await tick(60)
    expect(f.GET).toHaveBeenCalledTimes(1)
  })
})

describe('clear()：中止、revoke、丢弃迟到结果', () => {
  it('中止在途请求；revoke 已 ready 的 blob；迟到的成功结果不再创建 blob', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    cache.get('m1')
    f.pending[0]!.settle(ok())
    await tick()
    const firstUrl = created[0]!
    cache.get('m2')
    await tick()
    cache.clear()
    expect(f.pending[1]!.signal.aborted).toBe(true)
    expect(revoked).toContain(firstUrl)
    f.pending[1]!.settle(ok())
    await tick()
    expect(created.length).toBe(1)
  })

  it('clear 之后 get 不再发请求，返回停留在 loading 的条目', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    cache.clear()
    const e = cache.get('m9')
    await tick()
    expect(f.GET).not.toHaveBeenCalled()
    expect(e.status).toBe('loading')
  })

  it('clear 丢弃尚未开始的排队请求', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    for (let i = 0; i < 6; i++) cache.get(`m${i}`)
    await tick()
    expect(f.GET).toHaveBeenCalledTimes(4)
    cache.clear()
    for (const p of f.pending) p.settle(ok())
    await tick(60)
    expect(f.GET).toHaveBeenCalledTimes(4)
    expect(created.length).toBe(0)
  })

  it('clear 可重复调用而不抛错', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    cache.get('m1')
    f.pending[0]!.settle(ok())
    await tick()
    expect(() => {
      cache.clear()
      cache.clear()
    }).not.toThrow()
    expect(revoked.length).toBe(1)
  })
})

describe('forgetFailed()', () => {
  it('丢弃失败条目：下次 get 重新请求；expired 归零；generation 递增', async () => {
    const f = fakeApi()
    const cache: MediaCache = createMediaCache(() => f.api)
    cache.get('m1')
    f.pending[0]!.settle(fail('media_expired'))
    await tick()
    expect(cache.expired.value).toBe(1)
    expect(cache.generation.value).toBe(0)
    cache.forgetFailed()
    expect(cache.expired.value).toBe(0)
    expect(cache.generation.value).toBe(1)
    const e2 = cache.get('m1')
    expect(e2.status).toBe('loading')
    expect(f.GET).toHaveBeenCalledTimes(2)
  })

  it('成功的（ready）条目不受影响，不会重新请求', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    const e = cache.get('m1')
    f.pending[0]!.settle(ok())
    await tick()
    cache.forgetFailed()
    expect(cache.get('m1')).toBe(e)
    expect(e.status).toBe('ready')
    expect(f.GET).toHaveBeenCalledTimes(1)
  })
})

describe('download()', () => {
  it('成功：以给定文件名触发下载（blob 链接），10 秒后 revoke', async () => {
    vi.useFakeTimers()
    const clicks: { href: string; download: string }[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push({ href: this.href, download: this.download })
    })
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    const r = cache.download('f1', '报告.pdf')
    await tick()
    f.pending[0]!.settle(ok())
    expect(await r).toBeNull()
    expect(clicks).toEqual([{ href: 'blob:fake/1', download: '报告.pdf' }])
    expect(revoked).not.toContain('blob:fake/1')
    vi.advanceTimersByTime(10_000)
    expect(revoked).toContain('blob:fake/1')
  })

  it('失败：返回后端 code/category，不触发点击', async () => {
    const clicked = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(clicked)
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    const r = cache.download('f2', 'x.bin')
    await tick()
    f.pending[0]!.settle(fail('unsupported_media'))
    expect(await r).toEqual({ code: 'unsupported_media', category: null })
    expect(clicked).not.toHaveBeenCalled()
  })

  it('clear 之后 download 不发请求并返回 network', async () => {
    const f = fakeApi()
    const cache = createMediaCache(() => f.api)
    cache.clear()
    expect(await cache.download('f3', 'x')).toEqual({ code: 'network', category: null })
    expect(f.GET).not.toHaveBeenCalled()
  })
})

describe('mediaFailureText：固定文案映射', () => {
  it.each([
    ['media_expired', null, '图片已过期'],
    ['unsupported_media', null, '非图片，可下载'],
    ['no_credential', null, '该代码库未配置 PAT'],
    ['busy', null, '服务繁忙，图片未加载'],
    ['ado_request_failed', 'blocked_origin', '图片被拦截'],
    ['ado_request_failed', 'tls', '图片加载失败'],
    ['ado_request_failed', null, '图片加载失败'],
    ['network', null, '图片加载失败'],
    ['not_a_code', null, '图片加载失败'],
    [null, null, '图片加载失败'],
  ])('code=%s category=%s → %s', (code, category, text) => {
    expect(mediaFailureText(code, category)).toBe(text)
  })
})
