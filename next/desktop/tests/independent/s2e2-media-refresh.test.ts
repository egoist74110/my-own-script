// S2-E2 独立测试（independent）：「刷新详情」的顺序与过期计数；附件的下载按钮（CR-S2B-002 / 003 的对抗面）。
// 假 fetch（按 openapi 形状），不连任何真实服务。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSocket, env, resetSeq } from '../unit/helpers'
import { PNG, createWiFake, detail, summary, wiErr, type WiFake } from '../unit/wi-fake'
import { clickTab, openRow, openWi, settle, stubObjectUrls } from '../unit/wi-helpers'
import type { components } from '@/api/schema'

type S = components['schemas']
type Held = { signal: AbortSignal; release: () => void }
type Gate = { on: boolean; held: Held[] }

/** 门控：匹配路径且 on 时，先取快照，再挂起响应直到 release()（abort 后仍会晚到）。 */
function gate(
  base: typeof fetch,
  match: (path: string) => boolean,
): { fetch: typeof fetch; g: Gate } {
  const g: Gate = { on: false, held: [] }
  const f = (async (req: Request) => {
    const path = new URL(req.url).pathname
    if (!g.on || !match(path)) return base(req)
    const res = await base(req)
    let release!: () => void
    const open = new Promise<void>((r) => (release = r))
    g.held.push({ signal: req.signal, release })
    await open
    return res
  }) as typeof fetch
  return { fetch: f, g }
}

const K = 'proj:a|开发中'
const withImg = (id: string) =>
  detail(101, {
    html: {
      description: { html: `<p>正文</p><img data-media-id="${id}">` },
      repro_steps: null,
      acceptance_criteria: null,
    },
  })
const notice = (b: { wrapper: { find: (s: string) => { exists(): boolean } } }) =>
  b.wrapper.find('[data-testid=media-expired]').exists()
const mediaCalls = (fake: WiFake, id: string) =>
  fake.calls.filter((c) => c.path === `/api/work-items/media/${id}`).length
const blobImgs = (el: HTMLElement) =>
  Array.from(el.querySelectorAll<HTMLImageElement>('img')).filter((i) =>
    (i.getAttribute('src') ?? '').startsWith('blob:'),
  ).length

let fake: WiFake
let urls: ReturnType<typeof stubObjectUrls>
beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  urls = stubObjectUrls()
  fake = createWiFake()
  fake.lists[K] = { items: [summary(101)], truncated: false, omitted: 0 }
})
afterEach(() => {
  document.body.innerHTML = ''
  urls.restore()
  vi.restoreAllMocks()
})

describe('刷新详情：先重取、后清失败条目', () => {
  it('详情重取未完成时不得重试旧 id；重取完成后才用新 id 加载并清除提示', async () => {
    fake.details[101] = withImg('old1')
    fake.media['old1'] = () => wiErr(404, 'media_expired')
    fake.media['new1'] = PNG
    const g = gate(fake.fetch, (p) => p === '/api/work-items/101')
    const b = await openWi({ ...fake, fetch: g.fetch })
    await openRow(b, 101)
    expect(notice(b)).toBe(true)
    expect(mediaCalls(fake, 'old1')).toBe(1)

    g.g.on = true
    fake.details[101] = withImg('new1') // 后端登记表已换新 id
    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle(3)
    expect(g.g.held).toHaveLength(1) // 详情重取挂起中
    expect(mediaCalls(fake, 'old1')).toBe(1)
    expect(notice(b)).toBe(true)

    g.g.held[0]!.release()
    await settle(6)
    expect(mediaCalls(fake, 'old1')).toBe(1)
    expect(mediaCalls(fake, 'new1')).toBe(1)
    expect(notice(b)).toBe(false)
    expect(blobImgs(b.wrapper.element as HTMLElement)).toBe(1)
    await b.done()
  })

  it('刷新后仍是同一个 id：仍被引用，只重试一次，提示保留且不无限重试', async () => {
    fake.details[101] = withImg('old1')
    fake.media['old1'] = () => wiErr(404, 'media_expired')
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(mediaCalls(fake, 'old1')).toBe(1)

    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle(6)
    expect(mediaCalls(fake, 'old1')).toBe(2)
    expect(notice(b)).toBe(true)

    await settle(6)
    expect(mediaCalls(fake, 'old1')).toBe(2)
    await b.done()
  })

  it('已打开的评论：重取挂起时不重试旧 id；重取完成后用新 id 清除提示', async () => {
    fake.details[101] = detail(101)
    fake.comments[101] = {
      comments: [
        {
          id: 1,
          author: '甲',
          created_date: null,
          modified_date: null,
          html: '<img data-media-id="c-old">',
        },
      ],
      truncated: false,
    }
    fake.media['c-old'] = () => wiErr(404, 'media_expired')
    fake.media['c-new'] = PNG
    const g = gate(fake.fetch, (p) => p === '/api/work-items/101/comments')
    const b = await openWi({ ...fake, fetch: g.fetch })
    await openRow(b, 101)
    await clickTab(b, '工单内容', '评论')
    expect(notice(b)).toBe(true)
    expect(mediaCalls(fake, 'c-old')).toBe(1)

    g.g.on = true
    fake.comments[101] = {
      comments: [
        {
          id: 1,
          author: '甲',
          created_date: null,
          modified_date: null,
          html: '<img data-media-id="c-new">',
        },
      ],
      truncated: false,
    }
    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle(3)
    expect(g.g.held).toHaveLength(1)
    expect(mediaCalls(fake, 'c-old')).toBe(1)
    expect(notice(b)).toBe(true)

    g.g.held[0]!.release()
    await settle(6)
    expect(mediaCalls(fake, 'c-old')).toBe(1)
    expect(mediaCalls(fake, 'c-new')).toBe(1)
    expect(notice(b)).toBe(false)
    await b.done()
  })
})

describe('「部分图片已过期」只统计仍被引用的失败 id', () => {
  it('settings.changed 使旧 id 不再被引用（未点刷新）：提示消失，旧 id 不重试', async () => {
    fake.details[101] = withImg('old1')
    fake.media['old1'] = () => wiErr(404, 'media_expired')
    fake.media['new1'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(notice(b)).toBe(true)

    fake.details[101] = withImg('new1')
    b.sock.emit(env('settings.changed', { revision: 9 }))
    await settle(6)
    expect(notice(b)).toBe(false)
    expect(mediaCalls(fake, 'old1')).toBe(1)
    expect(mediaCalls(fake, 'new1')).toBe(1)
    await b.done()
  })

  it('附件里的过期图片：切到「附件」后提示出现；刷新后换新 id 成功则提示消失', async () => {
    fake.details[101] = detail(101, {
      attachments: [
        { name: 'shot.png', size: 9, is_image: true, media_id: 'att-old', blocked_origin: null },
      ],
    })
    fake.media['att-old'] = () => wiErr(404, 'media_expired')
    fake.media['att-new'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(notice(b)).toBe(false)
    await clickTab(b, '工单内容', '附件')
    expect(notice(b)).toBe(true)

    fake.details[101] = detail(101, {
      attachments: [
        { name: 'shot.png', size: 9, is_image: true, media_id: 'att-new', blocked_origin: null },
      ],
    })
    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle(6)
    expect(mediaCalls(fake, 'att-old')).toBe(1)
    expect(mediaCalls(fake, 'att-new')).toBe(1)
    expect(notice(b)).toBe(false)
    expect(b.wrapper.get('[data-testid=wi-attachment] img').attributes('src')).toMatch(/^blob:/)
    await b.done()
  })
})

describe('附件下载按钮', () => {
  beforeEach(() => {
    fake.details[101] = detail(101, {
      attachments: [
        { name: 'diagram.svg', size: 9, is_image: true, media_id: 'svg1', blocked_origin: null },
        { name: 'ok.png', size: 9, is_image: true, media_id: 'png1', blocked_origin: null },
        { name: 'spec.pdf', size: 1024, is_image: false, media_id: 'pdf1', blocked_origin: null },
        { name: 'ghost.png', size: null, is_image: true, media_id: null, blocked_origin: null },
        {
          name: 'evil.zip',
          size: 5,
          is_image: false,
          media_id: null,
          blocked_origin: 'https://evil.example:443',
        },
        { name: 'plain.txt', size: 5, is_image: false, media_id: null, blocked_origin: null },
      ],
    })
    fake.media['svg1'] = () => wiErr(415, 'unsupported_media')
    fake.media['png1'] = PNG
    fake.media['pdf1'] = PNG
  })

  it('凡有 media_id 都有「下载 <文件名>」；415 预览失败的 SVG 也有；无 media_id 的没有', async () => {
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '附件')
    const items = b.wrapper.findAll('[data-testid=wi-attachment]')
    expect(items).toHaveLength(6)
    const dl = (i: number) => items[i]!.findAll('button').map((x) => x.text())
    expect(dl(0)).toEqual(['下载 diagram.svg'])
    expect(dl(1)).toEqual(['下载 ok.png'])
    expect(dl(2)).toEqual(['下载 spec.pdf'])
    expect(dl(3)).toEqual([])
    expect(dl(4)).toEqual([])
    expect(dl(5)).toEqual([])
    expect(items[0]!.text()).toContain('非图片，可下载')
    expect(items[1]!.find('img').attributes('src')).toMatch(/^blob:/)
    expect(items[2]!.find('img').exists()).toBe(false)
    expect(items[4]!.find('[data-testid=attachment-blocked]').exists()).toBe(true)
    await b.done()
  })

  it('非图片（PDF）点击下载：带 Bearer 发请求，锚点 download 为文件名，使用 blob URL', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '附件')
    const btn = b.wrapper.findAll('button').find((x) => x.text() === '下载 spec.pdf')!
    await btn.trigger('click')
    await settle()
    const pdf = fake.calls.filter((c) => c.path === '/api/work-items/media/pdf1')
    expect(pdf.length).toBeGreaterThanOrEqual(1)
    expect(pdf.at(-1)!.auth).toBe('Bearer fake-token')
    expect(click).toHaveBeenCalledTimes(1)
    const a = click.mock.contexts[0] as HTMLAnchorElement
    expect(a.download).toBe('spec.pdf')
    expect(a.href.startsWith('blob:')).toBe(true)
    await b.done()
  })

  it('下载失败（媒体已过期）：在该附件下显示 role=alert 文案，页面不崩溃', async () => {
    fake.media['pdf1'] = () => wiErr(404, 'media_expired')
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '附件')
    const btn = b.wrapper.findAll('button').find((x) => x.text() === '下载 spec.pdf')!
    await btn.trigger('click')
    await settle()
    const item = b.wrapper.findAll('[data-testid=wi-attachment]')[2]!
    const alert = item.find('[role=alert]')
    expect(alert.exists()).toBe(true)
    expect(alert.text().length).toBeGreaterThan(0)
    await b.done()
  })

  it('预览 415 失败后（diagram.svg）点击下载仍可用，文件名正确', async () => {
    // 后端：预览（渲染时的第一次请求）415，之后的下载请求成功；下载不依赖预览状态
    let n = 0
    fake.media['svg1'] = () => (++n === 1 ? wiErr(415, 'unsupported_media') : PNG())
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '附件')
    const btn = b.wrapper.findAll('button').find((x) => x.text() === '下载 diagram.svg')!
    await btn.trigger('click')
    await flushPromises()
    await settle()
    expect(click).toHaveBeenCalledTimes(1)
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe('diagram.svg')
    await b.done()
  })

  it('边界：blocked_origin 与 media_id 同时存在时，凡有 media_id 即应显示下载（合同字面）', async () => {
    fake.details[101] = detail(101, {
      attachments: [
        {
          name: 'both.pdf',
          size: 3,
          is_image: false,
          media_id: 'b1',
          blocked_origin: 'https://x.example:443',
        },
      ],
    })
    fake.media['b1'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '附件')
    expect(b.wrapper.findAll('button').map((x) => x.text())).toContain('下载 both.pdf')
    await b.done()
  })
})

// 类型占位：避免未使用导入的 lint 报错
export type _Summary = S['WorkItemSummary']
