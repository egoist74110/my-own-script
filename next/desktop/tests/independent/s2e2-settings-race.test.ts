// S2-E2 独立测试（independent）：settings.changed 与工单列表/详情/评论的在途请求竞态。
// 假 fetch（按 openapi 形状），不连任何真实服务；本文件自带门控 fetch，可晚于 abort 放行旧响应。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSocket, env, resetSeq } from '../unit/helpers'
import { createWiFake, detail, summary, type WiFake } from '../unit/wi-fake'
import { openRow, openWi, rowIds, settle, clickTab, stubObjectUrls } from '../unit/wi-helpers'
import type { components } from '@/api/schema'

type S = components['schemas']
type Held = { signal: AbortSignal; release: () => void }
type Gate = { on: boolean; held: Held[] }

/**
 * 门控：匹配路径且 on 时，先用真实假后端取快照（即请求发出时的数据），再挂起响应直到 release()。
 * abortRejects=false：abort 后旧响应仍会晚到（模拟不理会取消的服务端），应用必须丢弃它。
 * abortRejects=true：abort 时 fetch 以 AbortError 拒绝（浏览器的真实行为）。
 */
function gate(
  base: typeof fetch,
  match: (path: string) => boolean,
  opts: { on?: boolean; abortRejects?: boolean } = {},
): { fetch: typeof fetch; g: Gate } {
  const g: Gate = { on: opts.on ?? false, held: [] }
  const f = (async (req: Request) => {
    const path = new URL(req.url).pathname
    if (!g.on || !match(path)) return base(req)
    const res = await base(req)
    let release!: () => void
    const open = new Promise<void>((r) => (release = r))
    g.held.push({ signal: req.signal, release })
    if (opts.abortRejects) {
      await Promise.race([
        open,
        new Promise<never>((_, rej) =>
          req.signal.addEventListener(
            'abort',
            () => rej(new DOMException('aborted', 'AbortError')),
            { once: true },
          ),
        ),
      ])
    } else {
      await open
    }
    return res
  }) as typeof fetch
  return { fetch: f, g }
}

const K = 'proj:a|开发中'
const page = (items: S['WorkItemSummary'][]) => ({ items, truncated: false, omitted: 0 })
const cm = (text: string): S['CommentsResponse'] => ({
  comments: [
    { id: 1, author: '甲', created_date: null, modified_date: null, html: `<p>${text}</p>` },
  ],
  truncated: false,
})

let fake: WiFake
let urls: ReturnType<typeof stubObjectUrls>
beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  urls = stubObjectUrls()
  fake = createWiFake()
})
afterEach(() => {
  document.body.innerHTML = ''
  urls.restore()
  vi.restoreAllMocks()
})

const emitRev = (b: { sock: FakeSocket }, revision: number) =>
  b.sock.emit(env('settings.changed', { revision }))

describe('settings.changed：列表查询', () => {
  it('首次列表在途、来源已变：第二次请求取新数据；旧响应晚到也不得覆盖', async () => {
    fake.lists[K] = page([summary(1, { title: '旧来源A' })])
    const g = gate(fake.fetch, (p) => p === '/api/work-items', { on: true })
    const b = await openWi({ ...fake, fetch: g.fetch })
    expect(g.g.held).toHaveLength(1)

    fake.lists[K] = page([summary(2, { title: '新来源B' })])
    emitRev(b, 9)
    await settle()
    expect(g.g.held).toHaveLength(2)
    expect(g.g.held[0]!.signal.aborted).toBe(true)
    expect(g.g.held[1]!.signal.aborted).toBe(false)

    g.g.held[1]!.release()
    await settle()
    expect(rowIds(b)).toEqual([2])

    g.g.held[0]!.release() // 旧响应晚到
    await settle()
    expect(rowIds(b)).toEqual([2])
    expect(b.wrapper.text()).toContain('新来源B')
    expect(b.wrapper.text()).not.toContain('旧来源A')
    expect(fake.to('/api/work-items').filter((c) => c.path === '/api/work-items')).toHaveLength(2)
    await b.done()
  })

  it('连续两次 settings.changed（revision 递增）：按事件序列只留最后的来源，乱序到达的旧响应被丢弃', async () => {
    fake.lists[K] = page([summary(1)])
    const g = gate(fake.fetch, (p) => p === '/api/work-items', { on: true })
    const b = await openWi({ ...fake, fetch: g.fetch })

    fake.lists[K] = page([summary(2)])
    emitRev(b, 9)
    await settle()
    fake.lists[K] = page([summary(3)])
    emitRev(b, 10)
    await settle()
    expect(g.g.held).toHaveLength(3)
    expect(g.g.held.slice(0, 2).every((h) => h.signal.aborted)).toBe(true)

    g.g.held[2]!.release() // 最新
    await settle()
    expect(rowIds(b)).toEqual([3])
    g.g.held[1]!.release() // 中间的旧响应
    await settle()
    g.g.held[0]!.release() // 最早的旧响应
    await settle()
    expect(rowIds(b)).toEqual([3])
    await b.done()
  })

  it('连续两次 settings.changed（revision 递增；store 对相同 revision 不触发，后端 revision 单调）：每次都取消并重取', async () => {
    fake.lists[K] = page([summary(1)])
    const g = gate(fake.fetch, (p) => p === '/api/work-items', { on: true })
    const b = await openWi({ ...fake, fetch: g.fetch })
    fake.lists[K] = page([summary(2)])
    emitRev(b, 10)
    await settle()
    fake.lists[K] = page([summary(3)])
    emitRev(b, 9)
    await settle()
    expect(g.g.held).toHaveLength(3)
    for (const h of g.g.held.slice(-1)) h.release()
    await settle()
    expect(rowIds(b)).toEqual([3])
    await b.done()
  })

  it('fetch 因 abort 以 AbortError 拒绝：不出现错误提示，新数据正常显示', async () => {
    fake.lists[K] = page([summary(1)])
    const g = gate(fake.fetch, (p) => p === '/api/work-items', { on: true, abortRejects: true })
    const b = await openWi({ ...fake, fetch: g.fetch })

    fake.lists[K] = page([summary(2)])
    emitRev(b, 9)
    await settle()
    expect(g.g.held[0]!.signal.aborted).toBe(true)
    g.g.held[1]!.release() // 新请求放行
    await settle()
    expect(rowIds(b)).toEqual([2])
    expect(b.wrapper.text()).not.toContain('无法连接后端')
    expect(b.wrapper.text()).not.toContain('读取失败')
    await b.done()
  })
})

describe('settings.changed：详情查询', () => {
  it('详情在途、来源已变：取新详情；旧详情晚到不覆盖', async () => {
    fake.lists[K] = page([summary(101)])
    fake.details[101] = detail(101, { title: '旧详情A' })
    const g = gate(fake.fetch, (p) => p === '/api/work-items/101')
    const b = await openWi({ ...fake, fetch: g.fetch })
    g.g.on = true
    await openRow(b, 101)
    expect(g.g.held).toHaveLength(1)

    fake.details[101] = detail(101, { title: '新详情B' })
    emitRev(b, 9)
    await settle()
    expect(g.g.held).toHaveLength(2)
    expect(g.g.held[0]!.signal.aborted).toBe(true)

    g.g.held[1]!.release()
    await settle()
    expect(b.wrapper.get('.d-head h2').text()).toBe('新详情B')

    g.g.held[0]!.release()
    await settle()
    expect(b.wrapper.get('.d-head h2').text()).toBe('新详情B')
    expect(b.wrapper.text()).not.toContain('旧详情A')
    expect(fake.calls.filter((c) => c.path === '/api/work-items/101')).toHaveLength(2)
    await b.done()
  })

  it('连续两次 settings.changed：详情只显示最后一次来源', async () => {
    fake.lists[K] = page([summary(101)])
    fake.details[101] = detail(101, { title: '详情甲' })
    const g = gate(fake.fetch, (p) => p === '/api/work-items/101')
    const b = await openWi({ ...fake, fetch: g.fetch })
    g.g.on = true
    await openRow(b, 101)

    fake.details[101] = detail(101, { title: '详情乙' })
    emitRev(b, 9)
    await settle()
    fake.details[101] = detail(101, { title: '详情丙' })
    emitRev(b, 10)
    await settle()
    expect(g.g.held).toHaveLength(3)

    g.g.held[2]!.release()
    await settle()
    g.g.held[1]!.release()
    g.g.held[0]!.release()
    await settle()
    expect(b.wrapper.get('.d-head h2').text()).toBe('详情丙')
    expect(b.wrapper.text()).not.toContain('详情乙')
    await b.done()
  })
})

describe('settings.changed：评论查询', () => {
  it('评论在途、来源已变：取新评论；旧评论晚到不覆盖', async () => {
    fake.lists[K] = page([summary(101)])
    fake.details[101] = detail(101)
    fake.comments[101] = cm('旧评论A')
    const g = gate(fake.fetch, (p) => p === '/api/work-items/101/comments')
    const b = await openWi({ ...fake, fetch: g.fetch })
    await openRow(b, 101)
    g.g.on = true
    await clickTab(b, '工单内容', '评论')
    expect(g.g.held).toHaveLength(1)

    fake.comments[101] = cm('新评论B')
    emitRev(b, 9)
    await settle()
    expect(g.g.held).toHaveLength(2)
    expect(g.g.held[0]!.signal.aborted).toBe(true)

    g.g.held[1]!.release()
    await settle()
    expect(b.wrapper.text()).toContain('新评论B')

    g.g.held[0]!.release()
    await settle()
    expect(b.wrapper.text()).toContain('新评论B')
    expect(b.wrapper.text()).not.toContain('旧评论A')
    expect(fake.calls.filter((c) => c.path === '/api/work-items/101/comments')).toHaveLength(2)
    await b.done()
  })

  it('连续两次 settings.changed：评论只显示最后一次来源', async () => {
    fake.lists[K] = page([summary(101)])
    fake.details[101] = detail(101)
    const g = gate(fake.fetch, (p) => p === '/api/work-items/101/comments')
    const b = await openWi({ ...fake, fetch: g.fetch })
    await openRow(b, 101)
    fake.comments[101] = cm('评论甲')
    g.g.on = true
    await clickTab(b, '工单内容', '评论')

    fake.comments[101] = cm('评论乙')
    emitRev(b, 9)
    await settle()
    fake.comments[101] = cm('评论丙')
    emitRev(b, 10)
    await settle()
    expect(g.g.held).toHaveLength(3)

    g.g.held[2]!.release()
    await settle()
    g.g.held[1]!.release()
    g.g.held[0]!.release()
    await settle()
    expect(b.wrapper.text()).toContain('评论丙')
    expect(b.wrapper.text()).not.toContain('评论乙')
    expect(b.wrapper.text()).not.toContain('评论甲')
    await b.done()
  })
})
