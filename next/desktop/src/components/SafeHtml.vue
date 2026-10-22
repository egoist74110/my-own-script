<script setup lang="ts">
import {
  effectScope,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
  type EffectScope,
} from 'vue'
import { mediaFailureText, type MediaCache } from './media'
import { openExternal } from './open-external'
import { sanitizeHtml } from './safe-html'

/**
 * 渲染后端已清洗过的 HTML，并在前端再清洗一遍（DOMPurify 白名单）。
 * - `<img data-media-id>` 由 `media` 取成 blob: URL 后才设置 src；加载中/失败显示占位，HTML 本身不携带可加载地址；
 * - `<span data-blocked-origin>` 显示被拦截的 origin；
 * - 链接点击/辅助点击一律拦截：用 openExternal 在系统浏览器打开，WebView 自身永不导航。
 */
const props = defineProps<{ html: string; media?: MediaCache }>()

const root = ref<HTMLElement | null>(null)
const clean = ref('')
let scope: EffectScope | null = null
let created: HTMLElement[] = []
const owner = {} // 向媒体缓存声明本组件当前引用的 id

watch(
  () => props.html,
  (h) => (clean.value = sanitizeHtml(h)),
  { immediate: true },
)

function placeholder(img: HTMLImageElement): HTMLSpanElement {
  const span = document.createElement('span')
  span.className = 'media-ph'
  span.setAttribute('role', 'img')
  img.insertAdjacentElement('afterend', span)
  created.push(span)
  return span
}

function hydrate() {
  scope?.stop()
  scope = effectScope()
  for (const n of created) n.remove()
  created = []
  props.media?.release(owner)
  const el = root.value
  if (!el) return
  // 被拦截的外部图片：只显示 origin（后端只给 scheme://host:port）
  for (const s of el.querySelectorAll<HTMLElement>('span[data-blocked-origin]')) {
    const origin = s.getAttribute('data-blocked-origin') ?? ''
    s.classList.add('media-ph')
    s.setAttribute('role', 'img')
    s.textContent = origin ? `已拦截外部图片 · ${origin}` : '内嵌图片未显示'
  }
  const media = props.media
  const imgs = el.querySelectorAll<HTMLImageElement>('img')
  scope.run(() => {
    for (const img of imgs) {
      const id = img.getAttribute('data-media-id')
      img.removeAttribute('src')
      img.removeAttribute('srcset')
      img.hidden = true
      const ph = placeholder(img)
      if (!id || !media) {
        ph.textContent = '图片未显示'
        continue
      }
      const entry = media.get(id, owner)
      ph.setAttribute('aria-label', img.getAttribute('alt') || '图片')
      watch(
        () => [entry.status, entry.url, entry.code, entry.category] as const,
        ([status, url, code, category]) => {
          if (status === 'ready' && url) {
            img.src = url
            img.hidden = false
            ph.hidden = true
          } else {
            img.removeAttribute('src')
            img.hidden = true
            ph.hidden = false
            ph.textContent = status === 'error' ? mediaFailureText(code, category) : '图片加载中…'
          }
        },
        { immediate: true },
      )
    }
  })
}

watch(
  clean,
  async () => {
    await nextTick()
    hydrate()
  },
  { flush: 'post' },
)
watch(() => props.media?.generation.value, hydrate, { flush: 'post' })
onMounted(hydrate)
onBeforeUnmount(() => {
  scope?.stop()
  props.media?.release(owner)
})

function onLink(ev: MouseEvent) {
  const a = (ev.target as Element | null)?.closest?.('a')
  if (!a || !root.value?.contains(a)) return
  ev.preventDefault()
  ev.stopPropagation()
  const href = a.getAttribute('href')
  if (href) void openExternal(href)
}
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div ref="root" class="safe-html" @click="onLink" @auxclick="onLink" v-html="clean"></div>
</template>

<style scoped>
.safe-html {
  overflow-wrap: anywhere;
}
.safe-html :deep(img) {
  max-width: 100%;
  height: auto;
}
.safe-html :deep(.media-ph) {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11.5px;
  color: var(--mute);
  background: rgba(20, 22, 26, 0.06);
  box-shadow: inset 0 0 0 1px var(--line);
}
.safe-html :deep(.media-ph[hidden]),
.safe-html :deep(img[hidden]) {
  display: none;
}
.safe-html :deep(a) {
  color: var(--ink);
  text-decoration: underline;
}
.safe-html :deep(table) {
  border-collapse: collapse;
  max-width: 100%;
}
.safe-html :deep(td),
.safe-html :deep(th) {
  padding: 4px 8px;
  box-shadow: inset 0 0 0 1px var(--line);
}
.safe-html :deep(pre) {
  overflow: auto;
  padding: 8px 10px;
  background: rgba(20, 22, 26, 0.06);
}
.safe-html :deep(blockquote) {
  margin: 0;
  padding-left: 10px;
  border-left: 3px solid var(--line);
}
</style>
