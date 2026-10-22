<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { inject } from 'vue'
import SafeHtml from '@/components/SafeHtml.vue'
import { mediaCacheKey } from '@/components/media'
import ErrorNotice from './ErrorNotice.vue'
import { ApiError, badShape, unwrap, type Comment } from './api'
import { formatDate } from './format'
import { QUERY_DEFAULTS, projectKey, useWiApi } from './queries'
import './panes.css'

const props = defineProps<{ projectId: string; id: number }>()
defineEmits<{ goHistory: [] }>()
const { api, online } = useWiApi()
const media = inject(mediaCacheKey, undefined)

const q = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: [...projectKey(props.projectId), 'comments', props.id],
  enabled: online,
  queryFn: async ({ signal }): Promise<{ comments: Comment[]; truncated: boolean }> => {
    const d = await unwrap(
      api().GET('/api/work-items/{id}/comments', {
        signal,
        params: { path: { id: props.id }, query: { project_id: props.projectId } },
      }),
    )
    if (!Array.isArray(d.comments)) throw badShape()
    return d
  },
})
</script>

<template>
  <div class="wi-pane" data-testid="wi-body" :aria-busy="q.isPending.value">
    <p v-if="q.isPending.value" class="wi-muted">读取评论中…</p>
    <template v-else-if="q.error.value">
      <div
        v-if="q.error.value instanceof ApiError && q.error.value.code === 'not_found'"
        class="wi-card"
        role="status"
        data-testid="comments-unsupported"
      >
        <span>该服务器不支持评论接口，可查看「历史」</span>
        <button type="button" class="wi-btn-link" @click="$emit('goHistory')">查看历史</button>
      </div>
      <ErrorNotice v-else :error="q.error.value" retry @retry="q.refetch()" />
    </template>
    <template v-else-if="q.data.value">
      <p v-if="!q.data.value.comments.length" class="wi-muted">暂无评论</p>
      <ul class="wi-list">
        <li v-for="c in q.data.value.comments" :key="c.id" class="wi-card">
          <span class="wi-card-h"
            >{{ c.author ?? '未知' }}
            <span class="wi-muted">· {{ formatDate(c.created_date) }}</span></span
          >
          <SafeHtml v-if="c.html" :html="c.html" :media="media" />
          <span v-else-if="c.omitted === 'too_large'" class="wi-muted">内容过大，未显示</span>
        </li>
      </ul>
      <p v-if="q.data.value.truncated" class="wi-muted">只显示前 100 条评论</p>
    </template>
  </div>
</template>

<style scoped>
.wi-btn-link {
  align-self: flex-start;
  min-height: var(--target-min);
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  font-weight: 600;
  text-decoration: underline;
  cursor: pointer;
  color: var(--ink);
}
</style>
