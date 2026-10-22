<script setup lang="ts">
import { inject, onBeforeUnmount, ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import { mediaCacheKey, mediaFailureText } from '@/components/media'
import type { Attachment } from './api'
import { formatBytes } from './format'
import './panes.css'

const props = defineProps<{ attachments: Attachment[] }>()
const media = inject(mediaCacheKey, undefined)
const owner = {} // 向媒体缓存声明本面板当前引用的 id
watch(
  () => props.attachments,
  () => media?.release(owner),
)
onBeforeUnmount(() => media?.release(owner))
const dlError = ref<Record<string, string>>({})

async function download(a: Attachment) {
  if (!media || !a.media_id) return
  const fail = await media.download(a.media_id, a.name)
  dlError.value = {
    ...dlError.value,
    [a.media_id]: fail ? mediaFailureText(fail.code, fail.category) : '',
  }
}
</script>

<template>
  <div class="wi-pane" data-testid="wi-body">
    <p v-if="!attachments.length" class="wi-muted">暂无附件</p>
    <ul class="wi-list">
      <li
        v-for="(a, i) in attachments"
        :key="`${media?.generation.value ?? 0}:${a.media_id ?? `b${i}`}`"
        class="wi-card"
        data-testid="wi-attachment"
      >
        <span class="wi-card-h"
          >{{ a.name }} <span class="wi-muted">· {{ formatBytes(a.size) }}</span></span
        >
        <span v-if="a.blocked_origin !== null" class="media-ph" data-testid="attachment-blocked"
          >已拦截外部附件 · {{ a.blocked_origin || '未知来源' }}</span
        >
        <template v-if="a.media_id && media">
          <template v-if="a.is_image && a.blocked_origin === null">
            <span v-if="media.get(a.media_id, owner).status === 'loading'" class="media-ph"
              >图片加载中…</span
            >
            <img
              v-else-if="media.get(a.media_id, owner).status === 'ready'"
              :src="media.get(a.media_id, owner).url ?? undefined"
              :alt="a.name"
              class="thumb"
            />
            <span v-else class="media-ph">{{
              mediaFailureText(
                media.get(a.media_id, owner).code,
                media.get(a.media_id, owner).category,
              )
            }}</span>
          </template>
          <!-- 凡有 media_id 都可下载（图片附件另有缩略图；SVG/预览失败的也能下） -->
          <AppButton variant="ghost" @click="download(a)">下载 {{ a.name }}</AppButton>
          <span v-if="dlError[a.media_id]" class="media-ph" role="alert">{{
            dlError[a.media_id]
          }}</span>
        </template>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.thumb {
  max-width: 100%;
  max-height: 320px;
  align-self: flex-start;
}
.media-ph {
  align-self: flex-start;
  padding: 2px 8px;
  font-size: 11.5px;
  color: var(--mute);
  background: rgba(20, 22, 26, 0.06);
  box-shadow: inset 0 0 0 1px var(--line);
}
</style>
