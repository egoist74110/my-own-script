<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, provide, ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppTabs from '@/components/AppTabs.vue'
import BlockTag from '@/components/BlockTag.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import SafeHtml from '@/components/SafeHtml.vue'
import { createMediaCache, mediaCacheKey } from '@/components/media'
import { openExternal } from '@/components/open-external'
import AttachmentsPane from './AttachmentsPane.vue'
import ChildrenPane from './ChildrenPane.vue'
import CommentsPane from './CommentsPane.vue'
import ErrorNotice from './ErrorNotice.vue'
import HistoryPane from './HistoryPane.vue'
import { badShape, unwrap, type HtmlField, type WorkItemDetail } from './api'
import { formatDate } from './format'
import { QUERY_DEFAULTS, projectKey, useWiApi } from './queries'
import './panes.css'

/**
 * 工单详情。本组件由页面以 `${projectId}:${id}` 作 key：切换工单/项目或离开页面即卸载，
 * 页面级媒体缓存随之 clear()（中止请求 + revokeObjectURL 全部 blob）。
 */
const props = defineProps<{ projectId: string; id: number }>()
const emit = defineEmits<{ select: [id: number] }>()
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

const props2 = computed(() => {
  const x = d.value
  if (!x) return []
  return [
    ['指派', x.assigned_to ?? '未指派'],
    ['看板列', x.board_column ?? '—'],
    ['严重度', x.severity ?? '—'],
    ['区域', x.area_path ?? '—'],
    ['迭代', x.iteration_path ?? '—'],
    ['创建', formatDate(x.created_date)],
    ['变更', formatDate(x.changed_date)],
    ['版本', x.rev === null || x.rev === undefined ? '—' : `r${x.rev}`],
  ].filter(([, v]) => v !== '—') as [string, string][]
})

// 先失效并等当前详情（及已打开的评论）重取完成，再清失败条目：
// 否则旧 id 会先被重试一遍，而新 id 成功后过期提示仍在（CR-S2B-002）
async function refreshDetail() {
  await qc.invalidateQueries({ queryKey: projectKey(props.projectId) })
  media.forgetFailed()
}
</script>

<template>
  <GlassPanel as="section" aria-label="工单详情" class="detail" :aria-busy="q.isPending.value">
    <p v-if="q.isPending.value" class="wi-pane wi-muted">读取工单中…</p>
    <ErrorNotice v-else-if="q.error.value" :error="q.error.value" retry @retry="q.refetch()" />
    <template v-else-if="d">
      <header class="d-head">
        <div class="d-line">
          <span class="type ox skew" :data-type="d.type ?? ''">{{
            (d.type ?? '').toUpperCase()
          }}</span>
          <span class="ox idn">#{{ d.id }}</span>
          <BlockTag v-if="d.priority !== null && d.priority !== undefined"
            >P{{ d.priority }}</BlockTag
          >
          <span class="st"><span class="sq" aria-hidden="true"></span>{{ d.state ?? '—' }}</span>
          <span class="grow"></span>
          <AppButton variant="ghost" data-testid="open-web" @click="openExternal(d.web_url)"
            >在浏览器打开</AppButton
          >
        </div>
        <h2>{{ d.title }}</h2>
        <dl class="props">
          <div v-for="[k, v] in props2" :key="k" class="pair">
            <dt class="lbl">{{ k }}</dt>
            <dd>{{ v }}</dd>
          </div>
          <div v-if="d.parent_id" class="pair">
            <dt class="lbl">父项</dt>
            <dd>
              <button
                type="button"
                class="parent"
                data-testid="open-parent"
                @click="emit('select', d.parent_id!)"
              >
                #{{ d.parent_id }}
              </button>
            </dd>
          </div>
        </dl>
        <ul v-if="d.tags?.length" class="tags" aria-label="标签">
          <li v-for="t in d.tags ?? []" :key="t">
            <BlockTag>{{ t }}</BlockTag>
          </li>
        </ul>
      </header>
      <p v-if="media.expired.value > 0" class="expired" role="status" data-testid="media-expired">
        部分图片已过期
        <AppButton variant="ghost" data-testid="refresh-detail" @click="refreshDetail"
          >刷新详情</AppButton
        >
      </p>
      <AppTabs v-model="tab" :items="tabs" label="工单内容" class="d-tabs">
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
      </AppTabs>
    </template>
  </GlassPanel>
</template>

<style scoped>
.detail {
  flex: 999 1 420px;
  min-width: 0;
  min-height: 280px;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
.grow {
  flex: 1;
}
.d-head {
  padding: 14px 18px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border-bottom: 1px solid var(--line);
}
.d-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.type {
  padding: 2px 12px;
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 1px;
  background: var(--faint);
  color: var(--ink);
}
.type[data-type='Bug'] {
  background: var(--warn);
}
.idn {
  font-size: 14px;
  font-weight: 700;
}
.st {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.sq {
  width: 7px;
  height: 7px;
  background: var(--acc);
}
h2 {
  margin: 0;
  font-size: 19px;
  line-height: 1.4;
  font-weight: 700;
  overflow-wrap: anywhere;
}
.props {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 4px 16px;
}
.pair {
  display: flex;
  gap: 8px;
  min-width: 0;
}
.props dd {
  margin: 0;
  font-size: 12.5px;
  font-weight: 500;
  overflow-wrap: anywhere;
}
.tags {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.d-tabs {
  padding: 8px 14px 0;
}
.d-tabs :deep(.tab-panel) {
  margin: 0 -14px;
}
.expired {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 18px;
  font-size: 12.5px;
  background: rgba(255, 140, 40, 0.14);
}
.parent,
.link {
  min-height: var(--target-min);
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  font-weight: 600;
  text-decoration: underline;
  cursor: pointer;
  color: var(--ink);
  text-align: left;
}
</style>
