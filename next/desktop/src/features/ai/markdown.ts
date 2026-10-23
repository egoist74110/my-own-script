// 纯前端轻量 Markdown 格式化 + DOMPurify 安全清洗（无外部第三方重量依赖）
import { sanitizeHtml } from '@/components/safe-html'

export function renderMarkdown(md: string): string {
  if (!md) return ''

  // 1. 保护并转义代码块与行内代码
  const codeBlocks: string[] = []
  let html = md.replace(/```([\w-]*)\n([\s\S]*?)```/g, (_match, _lang, code) => {
    const escaped = code.trim().replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    const idx = codeBlocks.length
    codeBlocks.push(`<pre class="code-block"><code class="mono">${escaped}</code></pre>`)
    return `<!--CODE_BLOCK_${idx}-->`
  })

  const inlineCodes: string[] = []
  html = html.replace(/`([^`]+)`/g, (_match, code) => {
    const escaped = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    const idx = inlineCodes.length
    inlineCodes.push(`<code class="mono inline-code">${escaped}</code>`)
    return `<!--INLINE_CODE_${idx}-->`
  })

  // 粗体
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

  // 斜体
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>')

  // 标题
  html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>')
  html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>')
  html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>')

  // 引用
  html = html.replace(/^> (.*$)/gim, '<blockquote>$1</blockquote>')

  // 链接：仅保留 http/https 链接
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" rel="noopener noreferrer">$1</a>',
  )

  // 段落切分
  const paragraphs = html.split(/\n{2,}/).map((p) => {
    const trimmed = p.trim()
    if (!trimmed) return ''
    if (
      trimmed.startsWith('<!--CODE_BLOCK_') ||
      trimmed.startsWith('<h') ||
      trimmed.startsWith('<blockquote')
    ) {
      return trimmed
    }
    return `<p>${trimmed.replace(/\n/g, '<br/>')}</p>`
  })

  let combined = paragraphs.filter(Boolean).join('\n')

  combined = combined.replace(
    /<!--CODE_BLOCK_(\d+)-->/g,
    (_m, idx) => codeBlocks[Number(idx)] || '',
  )
  combined = combined.replace(
    /<!--INLINE_CODE_(\d+)-->/g,
    (_m, idx) => inlineCodes[Number(idx)] || '',
  )

  return sanitizeHtml(combined)
}
