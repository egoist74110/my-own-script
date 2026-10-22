// S2-B 独立测试：HTML 前端清洗、SafeHtml 渲染、链接拦截、媒体占位。
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '@/api/client'
import SafeHtml from '@/components/SafeHtml.vue'
import { createMediaCache } from '@/components/media'
import { ALLOWED_TAGS, sanitizeHtml } from '@/components/safe-html'

const h = vi.hoisted(() => ({ tauriCalls: [] as unknown[][] }))
vi.mock('@tauri-apps/plugin-opener', () => ({
  openUrl: async (...args: unknown[]) => {
    h.tauriCalls.push(args)
  },
}))

const OK_TAG = new Set<string>(ALLOWED_TAGS)
const OK_ATTR = new Set([
  'href',
  'alt',
  'colspan',
  'rowspan',
  'data-media-id',
  'data-blocked-origin',
  'rel',
])

function parse(html: string): HTMLElement {
  const d = document.createElement('div')
  d.innerHTML = sanitizeHtml(html)
  return d
}

/** 返回清洗结果中违反合同的地方（空数组 = 合格）。 */
function violations(root: Element): string[] {
  const out: string[] = []
  for (const el of root.querySelectorAll('*')) {
    const tag = el.tagName.toLowerCase()
    if (!OK_TAG.has(tag)) out.push(`tag:${tag}`)
    for (const a of el.attributes) {
      const n = a.name.toLowerCase()
      if (!OK_ATTR.has(n)) out.push(`attr:${tag}@${n}`)
      // eslint-disable-next-line no-control-regex
      if (n === 'href' && !/^(https?|mailto):/i.test(a.value.replace(/[\u0000- ]/g, ''))) {
        out.push(`href:${a.value}`)
      }
    }
  }
  return out
}

const PAYLOADS = [
  '<ScRiPt>alert(1)</sCrIpT>',
  '<IMG SRC=x ONERROR=alert(1)>',
  '<a href="jav&#x09;ascript:alert(1)">x</a>',
  '<a href="&#0000106&#0000097&#0000118&#0000097script:alert(1)">x</a>',
  '<a href="  javascript:alert(1)">x</a>',
  '<a href="java\nscript:alert(1)">x</a>',
  '<a href="data:text/html,<script>alert(1)</script>">x</a>',
  '<a href="vbscript:msgbox(1)">x</a>',
  '<table><tr><td><a href="javascript:alert(1)">t</a></td></tr></table>',
  '<base href="https://evil.example/">',
  '<meta http-equiv="refresh" content="0;url=javascript:alert(1)">',
  '<link rel="import" href="https://evil.example/x.html">',
  '<style>@import "https://evil.example/x.css";</style><p>p</p>',
  '<img src="https://evil.example/x.png" srcset="https://evil.example/y.png 2x">',
  '<img data-media-id="m1" src="blob:null/x">',
  '<svg onload="alert(1)"><script>alert(1)</script></svg>',
  '<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>',
  '<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
  '<form action="javascript:alert(1)"><input formaction="javascript:alert(1)"><button>b</button></form>',
  '<iframe src="javascript:alert(1)"></iframe>',
  '<object data="javascript:alert(1)"></object><embed src="javascript:alert(1)">',
  '<details open ontoggle="alert(1)"><summary>s</summary></details>',
  '<p style="background:url(javascript:alert(1))" class="c" id="i">p</p>',
  '<a href="https://ok.example/" target="_top" xlink:href="javascript:alert(1)" onclick="alert(1)">ok</a>',
  '<span data-blocked-origin="<img src=x onerror=alert(1)>">x</span>',
  '<img alt="a" data-media-id="a&quot;onerror=alert(1)" src=x>',
  '<textarea><img src=x onerror=alert(1)></textarea>',
  '<template><img src=x onerror=alert(1)></template>',
  '<xmp><img src=x onerror=alert(1)></xmp>',
  '<a href="https://ok.example/"><img src="x" onerror="alert(1)"></a>',
  '<a href="https://ok.example/" style="x">ok</a>',
  '<input onfocus=alert(1) autofocus>',
  '<A HREF="JAVASCRIPT:alert(1)">upper</A>',
  '<a href="https://ok.example/" rel="external" class="k">y</a>',
]

describe('清洗：白名单（危险载荷逐条检查）', () => {
  PAYLOADS.forEach((p, i) => {
    it(`payload #${i} 清洗后不含违规标签/属性/协议`, () => {
      expect(violations(parse(p))).toEqual([])
    })
  })

  it('清洗后不保留 <style> 的内容文本', () => {
    expect(
      parse('<style>@import "https://evil.example/x.css";</style><p>p</p>').textContent,
    ).not.toContain('@import')
  })

  it('https 链接保留 href，去掉 target，强制 rel=noopener noreferrer', () => {
    const a = parse('<a href="https://ok.example/p?q=1" target="_top">去</a>').querySelector('a')!
    expect(a.getAttribute('href')).toBe('https://ok.example/p?q=1')
    expect(a.hasAttribute('target')).toBe(false)
    expect(a.getAttribute('rel')).toBe('noopener noreferrer')
  })

  it('mailto 链接允许保留，ftp 等其他协议删除 href', () => {
    expect(parse('<a href="mailto:a@b.test">m</a>').querySelector('a')!.getAttribute('href')).toBe(
      'mailto:a@b.test',
    )
    expect(parse('<a href="ftp://x.test/a">f</a>').querySelector('a')!.hasAttribute('href')).toBe(
      false,
    )
  })

  it('data-media-id 原样保留（含尖括号等字符），不被解释为标签', () => {
    const root = parse('<img data-media-id="&lt;b&gt;x" alt="图">')
    expect(root.querySelector('img')!.getAttribute('data-media-id')).toBe('<b>x')
    expect(root.querySelector('b')).toBeNull()
  })

  it('未列入白名单的 data-* 属性（如 data-foo）被删除', () => {
    const root = parse('<span data-foo="1" data-blocked-origin="https://a.test">x</span>')
    expect(root.querySelector('span')!.hasAttribute('data-foo')).toBe(false)
    expect(root.querySelector('span')!.getAttribute('data-blocked-origin')).toBe('https://a.test')
  })
})

describe('SafeHtml：链接点击拦截', () => {
  let originalLocation: string
  beforeEach(() => {
    originalLocation = window.location.href
    vi.spyOn(window, 'open').mockImplementation(() => null)
    h.tauriCalls.length = 0
  })
  afterEach(() => {
    delete (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
    document.body.innerHTML = ''
  })

  function mountHtml(html: string, media?: ReturnType<typeof createMediaCache>) {
    return mount(SafeHtml, { props: { html, media }, attachTo: document.body })
  }
  const click = (el: Element, type = 'click', button = 0) => {
    const ev = new MouseEvent(type, { bubbles: true, cancelable: true, button })
    el.dispatchEvent(ev)
    return ev
  }

  it('点击 https 链接：阻止默认、window.location 不变、dev 下 window.open(url,_blank,noopener)', () => {
    const w = mountHtml('<p><a href="https://ok.example/a?b=1">去看看</a></p>')
    const ev = click(w.find('a').element)
    expect(ev.defaultPrevented).toBe(true)
    expect(window.location.href).toBe(originalLocation)
    expect(window.open).toHaveBeenCalledWith('https://ok.example/a?b=1', '_blank', 'noopener')
  })

  it('链接内嵌套的元素被点击时仍按链接处理', () => {
    const w = mountHtml('<a href="https://ok.example/n"><b>粗体</b></a>')
    const ev = click(w.find('b').element)
    expect(ev.defaultPrevented).toBe(true)
    expect(window.open).toHaveBeenCalledWith('https://ok.example/n', '_blank', 'noopener')
  })

  it('中键辅助点击（auxclick）同样被拦截并打开', () => {
    const w = mountHtml('<a href="https://ok.example/m">m</a>')
    const ev = click(w.find('a').element, 'auxclick', 1)
    expect(ev.defaultPrevented).toBe(true)
    expect(window.open).toHaveBeenCalledWith('https://ok.example/m', '_blank', 'noopener')
  })

  it('mailto 链接：阻止默认，但不打开', () => {
    const w = mountHtml('<a href="mailto:a@b.test">m</a>')
    const ev = click(w.find('a').element)
    expect(ev.defaultPrevented).toBe(true)
    expect(window.open).not.toHaveBeenCalled()
  })

  it('带用户名/密码的 URL 不打开', () => {
    const w = mountHtml('<a href="https://user:pw@ok.example/">u</a>')
    click(w.find('a').element)
    expect(window.open).not.toHaveBeenCalled()
  })

  it('非链接区域的点击不被拦截', () => {
    const w = mountHtml('<p>纯文本</p>')
    const ev = click(w.find('p').element)
    expect(ev.defaultPrevented).toBe(false)
    expect(window.open).not.toHaveBeenCalled()
  })

  it('Tauri 运行时（__TAURI_INTERNALS__ 为对象）走 opener 插件 openUrl，不调用 window.open', async () => {
    ;(globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
    const w = mountHtml('<a href="https://ok.example/t">t</a>')
    click(w.find('a').element)
    await flushPromises()
    expect(h.tauriCalls).toEqual([['https://ok.example/t']])
    expect(window.open).not.toHaveBeenCalled()
  })

  it('Tauri 下非 http(s) 链接不调用 openUrl', async () => {
    ;(globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
    const w = mountHtml('<a href="mailto:a@b.test">m</a>')
    click(w.find('a').element)
    await flushPromises()
    expect(h.tauriCalls).toEqual([])
  })
})

describe('SafeHtml：图片与占位', () => {
  let urlN = 0
  const created: Blob[] = []
  beforeEach(() => {
    vi.spyOn(window, 'open').mockImplementation(() => null)
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: (b: Blob) => {
        created.push(b)
        return `blob:fake/${++urlN}`
      },
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: () => undefined,
    })
  })
  afterEach(() => {
    delete (URL as unknown as Record<string, unknown>).createObjectURL
    delete (URL as unknown as Record<string, unknown>).revokeObjectURL
    document.body.innerHTML = ''
  })

  it('外部 src 的图片：src 被删除，不发出请求，显示占位', () => {
    const w = mount(SafeHtml, {
      props: { html: '<img src="https://evil.example/x.png" alt="x">' },
      attachTo: document.body,
    })
    const img = w.find('img').element as HTMLImageElement
    expect(img.hasAttribute('src')).toBe(false)
    expect(img.hidden).toBe(true)
    expect(w.find('.media-ph').text()).toBe('图片未显示')
  })

  it('data-media-id 图片没有媒体缓存时显示「图片未显示」，不带 src', () => {
    const w = mount(SafeHtml, {
      props: { html: '<img data-media-id="m1" alt="甲">' },
      attachTo: document.body,
    })
    expect(w.find('img').element.hasAttribute('src')).toBe(false)
    expect(w.find('.media-ph').text()).toBe('图片未显示')
  })

  it('data-media-id 图片：加载中无 src；取到字节后才设为 blob: URL', async () => {
    const pending: { settle: (r: unknown) => void }[] = []
    const api = {
      GET: () =>
        new Promise((resolve) => {
          pending.push({ settle: resolve })
        }),
    } as unknown as ApiClient
    const media = createMediaCache(() => api)
    const w = mount(SafeHtml, {
      props: { html: '<p><img data-media-id="m1" alt="甲"></p>', media },
      attachTo: document.body,
    })
    await flushPromises()
    const img = w.find('img').element as HTMLImageElement
    expect(img.hasAttribute('src')).toBe(false)
    expect(w.find('.media-ph').text()).toBe('图片加载中…')
    pending[0]!.settle({ data: new Blob(['png']), response: new Response(null, { status: 200 }) })
    await flushPromises()
    expect(img.getAttribute('src')).toMatch(/^blob:fake\//)
    expect(img.hidden).toBe(false)
    expect(created.length).toBe(1)
  })

  it('媒体失败：占位显示固定文案（过期 / 被拦截）', async () => {
    const api = {
      GET: async () => ({
        error: { detail: { code: 'ado_request_failed', message: 'x', category: 'blocked_origin' } },
        response: new Response(null, { status: 502 }),
      }),
    } as unknown as ApiClient
    const w = mount(SafeHtml, {
      props: { html: '<img data-media-id="m2">', media: createMediaCache(() => api) },
      attachTo: document.body,
    })
    await flushPromises()
    expect(w.find('.media-ph').text()).toBe('图片被拦截')
    expect(w.find('img').element.hasAttribute('src')).toBe(false)
  })

  it('被拦截的外部图片：显示 origin（纯文本）；origin 含 HTML 时不产生元素', () => {
    const w = mount(SafeHtml, {
      props: {
        html: '<span data-blocked-origin="https://img.evil.example:443">x</span><span data-blocked-origin="<img src=x onerror=alert(1)>">y</span>',
      },
      attachTo: document.body,
    })
    const spans = w.findAll('span[role=img]')
    expect(spans[0]!.text()).toBe('已拦截外部图片 · https://img.evil.example:443')
    expect(spans[1]!.text()).toBe('已拦截外部图片 · <img src=x onerror=alert(1)>')
    expect(w.find('img').exists()).toBe(false)
  })

  it('data-blocked-origin 为空时显示「内嵌图片未显示」', () => {
    const w = mount(SafeHtml, {
      props: { html: '<span data-blocked-origin="">x</span>' },
      attachTo: document.body,
    })
    expect(w.find('span[role=img]').text()).toBe('内嵌图片未显示')
  })
})
