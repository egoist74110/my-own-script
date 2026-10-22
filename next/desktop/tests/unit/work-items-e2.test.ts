// S2-E2：CR-S2B-001/002/003 回归（假 fetch，按 openapi 形状；不连任何真实服务）。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSocket, env, resetSeq } from './helpers'
import { PNG, createWiFake, detail, summary, wiErr, type WiFake } from './wi-fake'
import { clickTab, openRow, openWi, settle, stubObjectUrls } from './wi-helpers'

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

const listCalls = () => fake.to('/api/work-items').filter((c) => c.path === '/api/work-items')

describe('CR-S2B-001：settings.changed 与在途请求', () => {
  it('首次列表请求在途时来源变化 + settings.changed：发第二次请求并显示新来源数据', async () => {
    fake.lists['proj:a|开发中'] = {
      items: [summary(1, { title: '旧来源' })],
      truncated: false,
      omitted: 0,
    }
    const base = fake.fetch
    const release: (() => void)[] = []
    let first = true
    const f = (async (req: Request) => {
      if (new URL(req.url).pathname === '/api/work-items' && first) {
        first = false
        const res = await base(req) // 旧来源的响应，先取下来，稍后才放行
        await new Promise<void>((r) => release.push(r))
        return res
      }
      return base(req)
    }) as typeof fetch
    const b = await openWi({ ...fake, fetch: f })
    expect(release).toHaveLength(1)
    // 同一 project_id 的来源（library/PAT）变了：同一键下现在应得到新数据
    fake.lists['proj:a|开发中'] = {
      items: [summary(2, { title: '新来源' })],
      truncated: false,
      omitted: 0,
    }
    b.sock.emit(env('settings.changed', { revision: 9 }))
    await settle()
    release[0]!()
    await settle()
    expect(listCalls().length).toBeGreaterThanOrEqual(2)
    expect(b.wrapper.text()).toContain('新来源')
    expect(b.wrapper.text()).not.toContain('旧来源')
    await b.done()
  })

  it('工单查询把 signal 传给 fetch：取消即中止请求', async () => {
    fake.lists['proj:a|开发中'] = { items: [summary(1)], truncated: false, omitted: 0 }
    const base = fake.fetch
    const signals: AbortSignal[] = []
    const f = (async (req: Request) => {
      if (new URL(req.url).pathname === '/api/work-items') {
        signals.push(req.signal)
        await new Promise(() => {}) // 永不返回
      }
      return base(req)
    }) as typeof fetch
    const b = await openWi({ ...fake, fetch: f })
    expect(signals).toHaveLength(1)
    b.sock.emit(env('settings.changed', { revision: 9 }))
    await settle()
    expect(signals[0]!.aborted).toBe(true)
    await b.done()
  })
})

describe('CR-S2B-002：刷新详情与过期计数', () => {
  it('旧 id 过期 → 刷新后换新 id 成功：提示消失，旧 id 只请求一次', async () => {
    fake.lists['proj:a|开发中'] = { items: [summary(101)], truncated: false, omitted: 0 }
    const withImg = (id: string) =>
      detail(101, {
        html: {
          description: { html: `<img data-media-id="${id}">` },
          repro_steps: null,
          acceptance_criteria: null,
        },
      })
    fake.details[101] = withImg('old1')
    fake.media['old1'] = () => wiErr(404, 'media_expired') as never
    fake.media['new1'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(b.wrapper.find('[data-testid=media-expired]').exists()).toBe(true)
    fake.details[101] = withImg('new1') // 后端登记表已换新 id
    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle(6)
    expect(fake.to('/api/work-items/media/old1')).toHaveLength(1)
    expect(fake.to('/api/work-items/media/new1')).toHaveLength(1)
    expect(b.wrapper.find('[data-testid=media-expired]').exists()).toBe(false)
    expect(
      Array.from(
        (b.wrapper.element as HTMLElement).querySelectorAll<HTMLImageElement>('.safe-html img'),
      ).some((i) => (i.getAttribute('src') ?? '').startsWith('blob:')),
    ).toBe(true)
    await b.done()
  })

  it('已打开的评论同样先重取再清失败条目', async () => {
    fake.lists['proj:a|开发中'] = { items: [summary(101)], truncated: false, omitted: 0 }
    fake.details[101] = detail(101)
    const cm = (id: string) => ({
      comments: [
        {
          id: 1,
          author: 'a',
          created_date: null,
          modified_date: null,
          html: `<img data-media-id="${id}">`,
        },
      ],
      truncated: false,
    })
    fake.comments[101] = cm('c-old')
    fake.media['c-old'] = () => wiErr(404, 'media_expired') as never
    fake.media['c-new'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '评论')
    expect(b.wrapper.find('[data-testid=media-expired]').exists()).toBe(true)
    fake.comments[101] = cm('c-new')
    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle(6)
    expect(fake.to('/api/work-items/media/c-old')).toHaveLength(1)
    expect(b.wrapper.find('[data-testid=media-expired]').exists()).toBe(false)
    await b.done()
  })
})

describe('CR-S2B-003：附件下载按钮', () => {
  it('is_image 附件（含预览失败的 SVG）有「下载」按钮且可下载；正常图片有缩略图和下载', async () => {
    fake.lists['proj:a|开发中'] = { items: [summary(101)], truncated: false, omitted: 0 }
    fake.details[101] = detail(101, {
      attachments: [
        { name: 'diagram.svg', size: 9, is_image: true, media_id: 'svg1', blocked_origin: null },
        { name: 'ok.png', size: 9, is_image: true, media_id: 'png1', blocked_origin: null },
      ],
    })
    fake.media['svg1'] = () => wiErr(415, 'unsupported_media') as never
    fake.media['png1'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '附件')
    const btns = b.wrapper.findAll('button').filter((x) => x.text().startsWith('下载'))
    expect(btns.map((x) => x.text())).toEqual(['下载 diagram.svg', '下载 ok.png'])
    expect(b.wrapper.get('[data-testid=wi-body] img').attributes('src')).toMatch(/^blob:/)
    // 点击 svg 的下载：415 的预览失败不影响下载（下载走同一接口；后端对 image 类型 415 时显示失败文案）
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await btns[1]!.trigger('click')
    await flushPromises()
    await settle()
    expect(click).toHaveBeenCalledTimes(1)
    // svg 的下载按钮同样会带 Bearer 发出请求（预览 1 次 + 下载 1 次）
    await btns[0]!.trigger('click')
    await settle()
    const svg = fake.to('/api/work-items/media/svg1')
    expect(svg).toHaveLength(2)
    expect(svg[1]!.auth).toBe('Bearer fake-token')
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe('ok.png')
    await b.done()
  })
})
