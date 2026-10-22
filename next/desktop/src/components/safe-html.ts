// 外部 HTML 的前端第二道清洗（后端 nh3 为第一道）。白名单与后端合同一致：
// 标签/属性显式列出；URI 只放 http/https/mailto；style/src/srcset/class/id/on* 一律不允许。
// 图片只能由代码把 `data-media-id` 换成 blob: src，HTML 本身不携带任何可加载地址。
import DOMPurify from 'dompurify'

export const ALLOWED_TAGS = [
  'p',
  'br',
  'div',
  'span',
  'b',
  'strong',
  'i',
  'em',
  'u',
  's',
  'strike',
  'sub',
  'sup',
  'ul',
  'ol',
  'li',
  'blockquote',
  'pre',
  'code',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'hr',
  'table',
  'thead',
  'tbody',
  'tfoot',
  'tr',
  'th',
  'td',
  'a',
  'img',
] as const
export const ALLOWED_ATTR = [
  'href',
  'alt',
  'colspan',
  'rowspan',
  'data-media-id',
  'data-blocked-origin',
] as const
const FORBID_ATTR = ['style', 'src', 'srcset', 'class', 'id', 'target', 'xlink:href']
const FORBID_TAGS = ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'svg', 'math']

const purify = DOMPurify(window)
// <a> 只保留 href；强制 rel（链接点击另由组件拦截，WebView 不导航）
purify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') node.setAttribute('rel', 'noopener noreferrer')
})

/** 清洗后返回 HTML 字符串。 */
export function sanitizeHtml(html: string): string {
  return purify.sanitize(html, {
    ALLOWED_TAGS: [...ALLOWED_TAGS],
    ALLOWED_ATTR: [...ALLOWED_ATTR],
    ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
    // 非 URI 属性默认也要过 ALLOWED_URI_REGEXP；这些属性的值不是 URL，须显式列为 URI 安全
    ADD_URI_SAFE_ATTR: ['data-media-id', 'data-blocked-origin', 'colspan', 'rowspan'],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    FORBID_ATTR,
    FORBID_TAGS,
    KEEP_CONTENT: true,
    RETURN_TRUSTED_TYPE: false,
  }) as string
}
