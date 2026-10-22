<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import ErrorNotice from './ErrorNotice.vue'
import { badShape, unwrap, type Update } from './api'
import { formatDate } from './format'
import { QUERY_DEFAULTS, projectKey, useWiApi } from './queries'
import './panes.css'

const props = defineProps<{ projectId: string; id: number }>()
const { api, online } = useWiApi()

const q = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: [...projectKey(props.projectId), 'updates', props.id],
  enabled: online,
  queryFn: async (): Promise<{ updates: Update[]; truncated: boolean }> => {
    const d = await unwrap(
      api().GET('/api/work-items/{id}/updates', {
        params: { path: { id: props.id }, query: { project_id: props.projectId } },
      }),
    )
    if (!Array.isArray(d.updates)) throw badShape()
    return d
  },
})
</script>

<template>
  <div class="wi-pane" data-testid="wi-body" :aria-busy="q.isPending.value">
    <p v-if="q.isPending.value" class="wi-muted">读取历史中…</p>
    <ErrorNotice v-else-if="q.error.value" :error="q.error.value" retry @retry="q.refetch()" />
    <template v-else-if="q.data.value">
      <p v-if="!q.data.value.updates.length" class="wi-muted">暂无历史</p>
      <ul class="wi-list">
        <li v-for="u in q.data.value.updates" :key="u.id" class="wi-card">
          <span class="wi-card-h"
            >r{{ u.rev ?? '?' }} · {{ u.revised_by ?? '未知' }}
            <span class="wi-muted">· {{ formatDate(u.revised_date) }}</span></span
          >
          <!-- 历史值已是后端转好的纯文本，这里只做文本插值 -->
          <span v-for="(f, i) in u.fields" :key="i" class="f"
            >{{ f.name }}：<span class="wi-muted">{{ f.old || '（空）' }}</span> →
            {{ f.new || '（空）' }}</span
          >
          <span v-if="u.relations_added || u.relations_removed" class="wi-muted"
            >关联 +{{ u.relations_added }} / −{{ u.relations_removed }}</span
          >
        </li>
      </ul>
      <p v-if="q.data.value.truncated" class="wi-muted">只显示前 100 条历史</p>
    </template>
  </div>
</template>

<style scoped>
.f {
  font-size: 12.5px;
  overflow-wrap: anywhere;
}
</style>
