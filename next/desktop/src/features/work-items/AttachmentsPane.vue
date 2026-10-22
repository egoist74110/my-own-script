<script setup lang="ts">
import { inject, ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import { mediaCacheKey, mediaFailureText } from '@/components/media'
import type { Attachment } from './api'
import { formatBytes } from './format'
import './panes.css'

defineProps<{ attachments: Attachment[] }>()
const media = inject(mediaCacheKey, undefined)
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
        <template v-else-if="a.media_id && media">
          <template v-if="a.is_image">
            <span v-if="media.get(a.media_id).status === 'loading'" class="media-ph"
              >图片加载中…</span
            >
            <img
              v-else-if="media.get(a.media_id).status === 'ready'"
              :src="media.get(a.media_id).url ?? undefined"
              :alt="a.name"
              class="thumb"
            />
            <span v-else class="media-ph">{{
              mediaFailureText(media.get(a.media_id).code, media.get(a.media_id).category)
            }}</span>
          </template>
          <template v-else>
            <AppButton variant="ghost" @click="download(a)">下载 {{ a.name }}</AppButton>
            <span v-if="dlError[a.media_id]" class="media-ph" role="alert">{{
              dlError[a.media_id]
            }}</span>
          </template>
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
