<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import SafeHtml from '@/components/SafeHtml.vue'
import { createMediaCache, mediaCacheKey } from '@/components/media'
import { openExternal } from '@/components/open-external'
import AttachmentsPane from './AttachmentsPane.vue'
import ChildrenPane from './ChildrenPane.vue'
import CommentsPane from './CommentsPane.vue'
import ErrorNotice from './ErrorNotice.vue'
import HistoryPane from './HistoryPane.vue'
import { badShape, unwrap, type HtmlField, type WorkItemDetail } from './api'
import { formatDate, kindColor } from './format'
import { QUERY_DEFAULTS, projectKey, useWiApi } from './queries'
import './panes.css'

/**
 * 工单详情。本组件由页面以 `${projectId}:${id}` 作 key：切换工单/项目或离开页面即卸载，
 * 页面级媒体缓存随之 clear()（中止请求 + revokeObjectURL 全部 blob）。
 */
const props = defineProps<{ projectId: string; id: number }>()
const emit = defineEmits<{ select: [id: number]; loaded: [detail: WorkItemDetail | null] }>()
const { api, maybeApi, online, qc } = useWiApi()

const media = createMediaCache(maybeApi)
provide(mediaCacheKey, media)
onBeforeUnmount(() => media.clear())

const q = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: [...projectKey(props.projectId), 'detail', props.id],
  enabled: online,
  queryFn: async ({ signal }): Promise<WorkItemDetail> => {
    const d = await unwrap(
      api().GET('/api/work-items/{id}', {
        signal,
        params: { path: { id: props.id }, query: { project_id: props.projectId } },
      }),
    )
    if (typeof d?.id !== 'number' || !Array.isArray(d.attachments) || !d.html) throw badShape()
    return d
  },
})
const d = computed(() => q.data.value ?? null)

const tab = ref('desc')
const tabs = computed(() => [
  { value: 'desc', label: '描述' },
  { value: 'comments', label: '评论' },
  { value: 'children', label: '子项', count: d.value?.child_ids.length },
  { value: 'history', label: '历史' },
  { value: 'files', label: '附件', count: d.value?.attachments.length },
])

const sections = computed(() => {
  const h = d.value?.html
  if (!h) return []
  const all: [string, string, HtmlField | null | undefined][] = [
    ['desc', '描述', h.description],
    ['repro', '复现步骤', h.repro_steps],
    ['ac', '验收标准', h.acceptance_criteria],
  ]
  return all.filter(([, , f]) => f && (f.html || f.omitted))
})

// 检查器（页面级）需要详情数据：加载完成时上报，卸载时清空
watch(d, (x) => emit('loaded', x), { immediate: true })
onBeforeUnmount(() => emit('loaded', null))

const metaLine = computed(() => {
  const x = d.value
  if (!x) return ''
  const rev = x.rev === null || x.rev === undefined ? null : `r${x.rev}`
  return [
    x.assigned_to ?? '未指派',
    `创建 ${formatDate(x.created_date)}`,
    `更新 ${formatDate(x.changed_date)}`,
    rev,
  ]
    .filter(Boolean)
    .join(' · ')
})

// 先失效并等当前详情（及已打开的评论）重取完成，再清失败条目：
// 否则旧 id 会先被重试一遍，而新 id 成功后过期提示仍在（CR-S2B-002）
async function refreshDetail() {
  await qc.invalidateQueries({ queryKey: projectKey(props.projectId) })
  media.forgetFailed()
}
</script>

<template>
  <div class="detail" :aria-busy="q.isPending.value">
    <div v-if="q.isPending.value" class="wi-pane" role="status">
      <div class="skel" aria-hidden="true">
        <span class="bar" style="width: 30%"></span>
        <span class="bar tall" style="width: 70%"></span>
        <span class="bar" style="width: 45%"></span>
      </div>
      <p class="wi-muted">读取工单中…</p>
    </div>
    <ErrorNotice v-else-if="q.error.value" :error="q.error.value" retry @retry="q.refetch()" />
    <template v-else-if="d">
      <header class="d-head">
        <div class="d-line">
          <span class="type" :data-type="d.type ?? ''"
            ><span class="kd" :style="{ background: kindColor(d.type) }" aria-hidden="true"></span
            >{{ d.type ?? '—' }}</span
          >
          <span class="mono idn">#{{ d.id }}</span>
          <template v-if="d.parent_id">
            <span aria-hidden="true">·</span>
            <span class="parent-wrap"
              >父项
              <button
                type="button"
                class="parent"
                data-testid="open-parent"
                @click="emit('select', d.parent_id!)"
              >
                #{{ d.parent_id }}
              </button></span
            >
          </template>
        </div>
        <h2>{{ d.title }}</h2>
        <div class="meta">{{ metaLine }}</div>
      </header>
      <Banner
        v-if="media.expired.value > 0"
        kind="warn"
        role="status"
        class="expired"
        data-testid="media-expired"
      >
        部分图片已过期
        <template #actions>
          <Button data-testid="refresh-detail" @click="refreshDetail">刷新详情</Button>
        </template>
      </Banner>
      <SegmentedControl v-model="tab" :items="tabs" label="工单内容" class="d-tabs">
        <template #default="{ item }">
          <div v-if="item.value === 'desc'" class="wi-pane" data-testid="wi-body">
            <template v-for="[key, label, f] in sections" :key="key">
              <h3 v-if="sections.length > 1" class="wi-sec-h">{{ label }}</h3>
              <SafeHtml v-if="f?.html" :html="f.html" :media="media" />
              <p v-else class="wi-muted">内容过大，未显示</p>
            </template>
            <p v-if="!sections.length" class="wi-muted">暂无描述</p>
            <template v-if="d.links.length">
              <h3 class="wi-sec-h">关联</h3>
              <ul class="wi-list" data-testid="wi-links">
                <li v-for="(l, i) in d.links" :key="i">
                  <button v-if="l.url" type="button" class="link" @click="openExternal(l.url)">
                    {{ l.label }}
                  </button>
                  <span v-else>{{ l.label }}</span>
                </li>
              </ul>
            </template>
          </div>
          <CommentsPane
            v-else-if="item.value === 'comments'"
            :id="id"
            :project-id="projectId"
            @go-history="tab = 'history'"
          />
          <ChildrenPane
            v-else-if="item.value === 'children'"
            :id="id"
            :project-id="projectId"
            @select="emit('select', $event)"
          />
          <HistoryPane v-else-if="item.value === 'history'" :id="id" :project-id="projectId" />
          <AttachmentsPane v-else :attachments="d.attachments" />
        </template>
      </SegmentedControl>
    </template>
  </div>
</template>

<style scoped>
.detail {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
.d-head {
  padding: 22px 32px 0;
  max-width: 820px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.d-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.type {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--accent-ink);
  font-weight: 600;
}
.kd {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
h2 {
  margin: 2px 0 0;
  font-size: var(--text-title);
  line-height: 1.3;
  font-weight: 700;
  letter-spacing: -0.2px;
  overflow-wrap: anywhere;
}
.meta {
  font-size: 12.5px;
  color: var(--mute);
}
.d-tabs {
  padding: 14px 32px 0;
}
.d-tabs :deep(.tab-panel) {
  margin: 0 -32px;
}
.expired {
  margin: 12px 32px 0;
  max-width: 756px;
}
.parent,
.link {
  min-height: var(--target-min);
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
  color: var(--link);
  text-align: left;
}
.parent {
  min-width: var(--target-min);
}
.skel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bar {
  display: block;
  height: 10px;
  border-radius: 4px;
  background: var(--skeleton);
}
.bar.tall {
  height: 22px;
}
</style>
