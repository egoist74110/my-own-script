<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import ErrorNotice from './ErrorNotice.vue'
import { badShape, unwrap, type ChildItem } from './api'
import { QUERY_DEFAULTS, projectKey, useWiApi } from './queries'
import './panes.css'

const props = defineProps<{ projectId: string; id: number }>()
defineEmits<{ select: [id: number] }>()
const { api, online } = useWiApi()

const q = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: [...projectKey(props.projectId), 'children', props.id],
  enabled: online,
  queryFn: async ({ signal }): Promise<{ items: ChildItem[]; truncated: boolean }> => {
    const d = await unwrap(
      api().GET('/api/work-items/{id}/children', {
        signal,
        params: { path: { id: props.id }, query: { project_id: props.projectId } },
      }),
    )
    if (!Array.isArray(d.items)) throw badShape()
    return d
  },
})
</script>

<template>
  <div class="wi-pane" data-testid="wi-body" :aria-busy="q.isPending.value">
    <p v-if="q.isPending.value" class="wi-muted">读取子项中…</p>
    <ErrorNotice v-else-if="q.error.value" :error="q.error.value" retry @retry="q.refetch()" />
    <template v-else-if="q.data.value">
      <p v-if="!q.data.value.items.length" class="wi-muted">暂无子项</p>
      <ul class="wi-list">
        <li
          v-for="c in q.data.value.items"
          :key="c.id"
          :style="{ paddingLeft: `${(c.depth - 1) * 16}px` }"
        >
          <button
            type="button"
            class="child"
            :data-testid="`child-${c.id}`"
            @click="$emit('select', c.id)"
          >
            <span class="ox">#{{ c.id }}</span>
            <span class="tt">{{ c.title }}</span>
            <span class="wi-muted"
              >{{ c.type ?? '' }} · {{ c.state ?? '' }} · {{ c.assigned_to ?? '未指派' }}</span
            >
          </button>
        </li>
      </ul>
      <p v-if="q.data.value.truncated" class="wi-muted">子项过多，只显示部分</p>
    </template>
  </div>
</template>

<style scoped>
.child {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  min-height: var(--target-min);
  padding: 4px 10px;
  border: 0;
  background: rgba(20, 22, 26, 0.04);
  font: inherit;
  text-align: left;
  color: inherit;
  cursor: pointer;
}
.child:hover {
  background: rgba(20, 22, 26, 0.09);
}
.tt {
  font-weight: 600;
}
</style>
