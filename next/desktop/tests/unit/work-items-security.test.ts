// S2-B 安全：XSS 语料、blob 图片、Bearer、媒体生命周期（revoke）、链接不导航。
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openUrl } from '@tauri-apps/plugin-opener'
import { FakeSocket, resetSeq } from './helpers'
import { PNG, createWiFake, detail, summary, wiErr, type WiFake } from './wi-fake'
import { clickTab, openRow, openWi, settle, stubObjectUrls, type WiBoot } from './wi-helpers'

vi.mock('@tauri-apps/plugin-opener', () => ({ openUrl: vi.fn(async () => {}) }))

let fake: WiFake
let urls: ReturnType<typeof stubObjectUrls>
beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
  urls = stubObjectUrls()
  fake = createWiFake()
  fake.lists['proj:a|开发中'] = {
    items: [summary(101), summary(102)],
    truncated: false,
    omitted: 0,
  }
})
afterEach(() => {
  document.body.innerHTML = ''
  urls.restore()
  delete (globalThis as Record<string, unknown>).__TAURI_INTERNALS__
  delete (window as unknown as Record<string, unknown>).__x
  vi.restoreAllMocks()
})

const withDesc = (id: number, html: string) => {
  fake.details[id] = detail(id, {
    html: { description: { html }, repro_steps: null, acceptance_criteria: null },
  })
}
const body = (b: WiBoot) => b.wrapper.get('section[aria-label=工单详情]').element as HTMLElement

const CORPUS: [string, string][] = [
  ['script', '<script>window.__x=1</script><p>ok</p>'],
  ['onerror 且带原始 src', '<img src="http://evil.test/a.png" onerror="window.__x=1"><p>ok</p>'],
  ['on* 事件', '<div onclick="window.__x=1" onmouseover="window.__x=1">x</div>'],
  ['javascript: href', '<a href="javascript:window.__x=1">x</a>'],
  [
    '实体编码 javascript:',
    '<a href="&#106;avascript:window.__x=1">x</a><a href="jav&#x09;ascript:1">y</a>',
  ],
  ['style 注入', '<p style="background:url(http://evil.test/x)">x</p><style>p{color:red}</style>'],
  ['svg onload', '<svg onload="window.__x=1"><circle r="1"/></svg>'],
  [
    'iframe',
    '<iframe src="http://evil.test"></iframe><iframe srcdoc="<script>1</script>"></iframe>',
  ],
  ['srcset', '<img srcset="http://evil.test/a.png 1x" src="http://evil.test/a.png">'],
  [
    'form/object/embed/math',
    '<form action="http://evil.test"><input name=a></form><object data="x"></object><embed src="x"><math><mi>x</mi></math>',
  ],
  [
    '嵌套畸形',
    '<scr<script>ipt>window.__x=1</script><img src=x onerror=window.__x=1//><a href=" javascript:1">z</a>',
  ],
  ['data: 图片', '<img src="data:image/svg+xml;base64,PHN2Zy8+" data-media-id="">'],
]

function assertSafe(root: HTMLElement) {
  expect(
    root.querySelector('script, iframe, svg, style, object, embed, form, input, math'),
  ).toBeNull()
  for (const el of root.querySelectorAll('.safe-html *')) {
    for (const a of Array.from(el.attributes)) {
      expect(a.name.startsWith('on'), `${el.tagName}[${a.name}]`).toBe(false)
      const own = a.name === 'class' && a.value === 'media-ph' // 组件自己生成的占位
      expect(
        ['style', 'srcset', 'srcdoc', 'class', 'id', 'target'].includes(a.name) && !own,
        a.name,
      ).toBe(false)
      if (a.name === 'href') expect(a.value).toMatch(/^(https?:|mailto:)/i)
    }
  }
  for (const img of root.querySelectorAll('img')) {
    const src = img.getAttribute('src')
    if (src !== null) expect(src.startsWith('blob:'), src).toBe(true)
    expect(img.hasAttribute('srcset')).toBe(false)
  }
  expect((window as unknown as Record<string, unknown>).__x).toBeUndefined()
}

describe('XSS 语料（后端形状输入）', () => {
  it.each(CORPUS)('描述：%s', async (_n, html) => {
    withDesc(101, html)
    const b = await openWi(fake)
    await openRow(b, 101)
    assertSafe(body(b))
    // 没有任何指向第三方的请求
    for (const c of fake.calls) expect(new URL(c.url).host).toBe('127.0.0.1:5555')
    await b.done()
  })

  it.each(CORPUS)('评论：%s', async (_n, html) => {
    withDesc(101, '<p>x</p>')
    fake.comments[101] = {
      comments: [{ id: 1, author: 'a', created_date: null, modified_date: null, html }],
      truncated: false,
    }
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '评论')
    assertSafe(body(b))
    await b.done()
  })

  it('历史字段值是纯文本：标签不会变成元素', async () => {
    withDesc(101, '<p>x</p>')
    fake.updates[101] = {
      updates: [
        {
          id: 1,
          rev: 1,
          revised_by: '<img src=x onerror=1>',
          revised_date: null,
          fields: [{ name: '<script>1</script>', old: '<b>a</b>', new: '<iframe></iframe>' }],
          relations_added: 0,
          relations_removed: 0,
        },
      ],
      truncated: false,
    }
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '历史')
    expect(
      body(b).querySelector('[data-testid=wi-body] img, [data-testid=wi-body] b, iframe, script'),
    ).toBeNull()
    expect(body(b).textContent).toContain('<iframe></iframe>')
    await b.done()
  })
})

describe('媒体：blob、Bearer、复用、占位', () => {
  const IMGS =
    '<p>图</p><img data-media-id="m1" alt="同源"><img data-media-id="m1" alt="再次"><img data-media-id="m2" alt="过期">'

  it('img 只出现 blob: src；请求带 Bearer；token 不在 URL / DOM / 存储；同 id 复用一个 blob', async () => {
    withDesc(101, IMGS)
    fake.media['m1'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    const imgs = Array.from(body(b).querySelectorAll('img'))
    const visible = imgs.filter((i) => !i.hidden)
    expect(visible).toHaveLength(2)
    for (const i of visible) expect(i.getAttribute('src')).toBe('blob:fake/1')
    for (const i of imgs.filter((x) => x.hidden)) expect(i.hasAttribute('src')).toBe(false)
    const m1 = fake.to('/api/work-items/media/m1')
    expect(m1).toHaveLength(1) // 同详情页同 id 一次请求
    expect(urls.create).toHaveBeenCalledTimes(1)
    for (const c of fake.to('/api/work-items/media/')) {
      expect(c.auth).toBe('Bearer fake-token')
      expect(c.url).not.toContain('fake-token')
      expect(c.url).not.toContain('?')
    }
    for (const c of fake.calls) expect(c.url).not.toContain('fake-token')
    expect(document.documentElement.outerHTML).not.toContain('fake-token')
    expect(JSON.stringify({ ...localStorage })).not.toContain('fake-token')
    expect(JSON.stringify({ ...sessionStorage })).not.toContain('fake-token')
    await b.done()
  })

  it('media_expired：占位 +「刷新详情」；点击后重取详情，不自动无限重试', async () => {
    withDesc(101, IMGS)
    fake.media['m1'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(body(b).textContent).toContain('图片已过期')
    expect(b.wrapper.get('[data-testid=media-expired]').text()).toContain('刷新详情')
    expect(fake.to('/api/work-items/media/m2')).toHaveLength(1)
    const before = fake.to('/api/work-items/101').length
    await b.wrapper.get('[data-testid=refresh-detail]').trigger('click')
    await settle()
    expect(fake.to('/api/work-items/101').length).toBe(before + 1)
    expect(fake.to('/api/work-items/media/m2')).toHaveLength(2) // 只在用户点击后重试一次
    await settle()
    expect(fake.to('/api/work-items/media/m2')).toHaveLength(2)
    await b.done()
  })

  it('blocked_origin：占位显示被拦截的 origin；内嵌图片占位', async () => {
    withDesc(
      101,
      '<span data-blocked-origin="https://cdn.example.test:443">[已拦截外部图片]</span><span data-blocked-origin="">[内嵌图片未显示]</span>',
    )
    const b = await openWi(fake)
    await openRow(b, 101)
    expect(body(b).textContent).toContain('已拦截外部图片 · https://cdn.example.test:443')
    expect(body(b).textContent).toContain('内嵌图片未显示')
    await b.done()
  })

  it('unsupported_media 与其他失败码：固定占位文案', async () => {
    withDesc(101, '<img data-media-id="u1"><img data-media-id="b1"><img data-media-id="n1">')
    fake.media['u1'] = () => wiErr(415, 'unsupported_media') as never
    fake.media['b1'] = () => wiErr(502, 'ado_request_failed', 'blocked_origin') as never
    fake.media['n1'] = () => wiErr(409, 'no_credential') as never
    const b = await openWi(fake)
    await openRow(b, 101)
    const t = body(b).textContent
    expect(t).toContain('非图片，可下载')
    expect(t).toContain('图片被拦截')
    expect(t).toContain('该代码库未配置 PAT')
    await b.done()
  })

  it('附件页：同源图片 blob 缩略图 / 被拦截 origin / 415 / 下载按钮', async () => {
    fake.details[101] = detail(101, {
      attachments: [
        { name: 'ok.png', size: 10, is_image: true, media_id: 'a1', blocked_origin: null },
        {
          name: 'x.png',
          size: 10,
          is_image: true,
          media_id: null,
          blocked_origin: 'https://cdn.example.test:443',
        },
        { name: 'bad.png', size: null, is_image: true, media_id: 'a2', blocked_origin: null },
        { name: 'doc.txt', size: 5, is_image: false, media_id: 'a3', blocked_origin: null },
      ],
    })
    fake.media['a1'] = PNG
    fake.media['a2'] = () => wiErr(415, 'unsupported_media') as never
    fake.media['a3'] = () =>
      new Response('hello', {
        status: 200,
        headers: { 'content-type': 'application/octet-stream' },
      })
    const b = await openWi(fake)
    await openRow(b, 101)
    await clickTab(b, '工单内容', '附件')
    const t = body(b).textContent!
    expect(t).toContain('已拦截外部附件 · https://cdn.example.test:443')
    expect(t).toContain('非图片，可下载')
    expect(body(b).querySelector('img')!.getAttribute('src')).toMatch(/^blob:/)
    // 下载：带 Bearer 取字节，用 blob: URL 触发下载
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const btn = b.wrapper.findAll('button').find((x) => x.text().startsWith('下载'))!
    await btn.trigger('click')
    await settle()
    expect(fake.to('/api/work-items/media/a3')[0]!.auth).toBe('Bearer fake-token')
    expect(click).toHaveBeenCalledTimes(1)
    const a = click.mock.contexts[0] as HTMLAnchorElement
    expect(a.download).toBe('doc.txt')
    expect(a.getAttribute('href')).toMatch(/^blob:/)
    await b.done()
    expect(urls.revoke).toHaveBeenCalled() // 卸载时连同下载用的 blob 一并回收
  })
})

describe('blob 生命周期：卸载 / 切换 revoke', () => {
  const setup = async () => {
    withDesc(101, '<img data-media-id="m1">')
    withDesc(102, '<img data-media-id="m3">')
    fake.media['m1'] = PNG
    fake.media['m3'] = PNG
    const b = await openWi(fake)
    await openRow(b, 101)
    return b
  }

  it('卸载页面时 revoke', async () => {
    const b = await setup()
    expect(urls.create).toHaveBeenCalledTimes(1)
    expect(urls.revoke).not.toHaveBeenCalled()
    await b.done()
    expect(urls.revoke).toHaveBeenCalledWith('blob:fake/1')
  })

  it('切换工单时 revoke 旧详情的 blob，新详情另取', async () => {
    const b = await setup()
    await openRow(b, 102)
    expect(urls.revoke).toHaveBeenCalledWith('blob:fake/1')
    expect(urls.create).toHaveBeenCalledTimes(2)
    await b.done()
    expect(urls.revoke).toHaveBeenCalledWith('blob:fake/2')
  })

  it('切换项目 / 看板列（详情被关闭）时 revoke', async () => {
    const b = await setup()
    await b.wrapper.get('[data-testid=project-select]').setValue('proj:b')
    await settle()
    expect(urls.revoke).toHaveBeenCalledWith('blob:fake/1')
    await b.done()
  })

  it('加载未完成就卸载：请求被中止，不会创建 blob', async () => {
    withDesc(101, '<img data-media-id="slow">')
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const base = fake.fetch
    const f = (async (req: Request) => {
      if (req.url.includes('/media/slow')) {
        await gate
        return PNG()
      }
      return base(req)
    }) as typeof fetch
    const b = await openWi({ ...fake, fetch: f })
    await openRow(b, 101)
    await b.done()
    release()
    await flushPromises()
    expect(urls.create).not.toHaveBeenCalled()
  })
})

describe('链接：WebView 永不导航', () => {
  const LINK = '<a href="https://example.test/x?a=1">外链</a>'
  const click = (el: Element, type = 'click') => {
    const ev = new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      button: type === 'auxclick' ? 1 : 0,
    })
    el.dispatchEvent(ev)
    return ev
  }

  it('dev:web：click 被拦截并 window.open(url,"_blank","noopener")；location 不变', async () => {
    withDesc(101, LINK + '<a href="mailto:a@b.test">m</a><a href="javascript:1">j</a>')
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const before = window.location.href
    const b = await openWi(fake)
    await openRow(b, 101)
    const links = Array.from(body(b).querySelectorAll('a'))
    const ev = click(links[0]!)
    expect(ev.defaultPrevented).toBe(true)
    expect(open).toHaveBeenCalledWith('https://example.test/x?a=1', '_blank', 'noopener')
    expect(window.location.href).toBe(before)
    // 辅助点击（中键）同样拦截
    expect(click(links[0]!, 'auxclick').defaultPrevented).toBe(true)
    // mailto 只拦截不打开；javascript: 的 href 已被清洗掉
    open.mockClear()
    expect(click(links[1]!).defaultPrevented).toBe(true)
    expect(open).not.toHaveBeenCalled()
    expect(links[2]!.hasAttribute('href')).toBe(false)
    // 链接带 rel=noopener noreferrer
    expect(links[0]!.getAttribute('rel')).toBe('noopener noreferrer')
    await b.done()
  })

  it('Tauri：走 opener 插件，不调用 window.open', async () => {
    withDesc(101, LINK)
    ;(globalThis as Record<string, unknown>).__TAURI_INTERNALS__ = {}
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const before = window.location.href
    const b = await openWi(fake)
    await openRow(b, 101)
    const ev = click(body(b).querySelector('a')!)
    await settle()
    expect(ev.defaultPrevented).toBe(true)
    expect(openUrl).toHaveBeenCalledWith('https://example.test/x?a=1')
    expect(open).not.toHaveBeenCalled()
    expect(window.location.href).toBe(before)
    await b.done()
  })

  it('「在浏览器打开」与关联超链接同样走 openExternal（dev：window.open）', async () => {
    fake.details[101] = detail(101, {
      links: [{ kind: 'hyperlink', label: '设计稿', url: 'https://example.test/design' }],
    })
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const b = await openWi(fake)
    await openRow(b, 101)
    await b.wrapper.get('[data-testid=open-web]').trigger('click')
    expect(open).toHaveBeenCalledWith(
      expect.stringMatching(/^https:\/\/ado\.example\.test\/tfs\/Col\/.+\/_workitems\/edit\/101$/),
      '_blank',
      'noopener',
    )
    open.mockClear()
    const link = b.wrapper
      .findAll('[data-testid=wi-links] button')
      .find((x) => x.text() === '设计稿')!
    await link.trigger('click')
    expect(open).toHaveBeenCalledWith('https://example.test/design', '_blank', 'noopener')
    await b.done()
  })

  it('非 http(s) 的 web_url 不会被打开', async () => {
    fake.details[101] = detail(101, { web_url: 'javascript:alert(1)' })
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const b = await openWi(fake)
    await openRow(b, 101)
    await b.wrapper.get('[data-testid=open-web]').trigger('click')
    expect(open).not.toHaveBeenCalled()
    await b.done()
  })
})
