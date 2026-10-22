<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { RefreshCw } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppTabs from '@/components/AppTabs.vue'
import { tabTriggerId } from '@/components/tabs'
import BlockTag from '@/components/BlockTag.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import IconButton from '@/components/IconButton.vue'
import InspectorPanel from '@/components/InspectorPanel.vue'
import SearchBox from '@/components/SearchBox.vue'
import ErrorNotice from './ErrorNotice.vue'
import WorkItemDetail from './WorkItemDetail.vue'
import {
  COLUMNS,
  DEFAULT_COLUMN,
  DEFAULT_PAGE_SIZE,
  PAGE_SIZES,
  badShape,
  unwrap,
  type AdoResponse,
  type WorkItemSummary,
} from './api'
import { formatDate } from './format'
import { QUERY_DEFAULTS, WI_KEY, projectKey, useWiApi } from './queries'
import { loadSelection, saveSelection } from './selection'
import './panes.css'

const { api, online, qc, store } = useWiApi()

// settings.changed：library/PAT/项目可能变了，使项目列表与全部工单查询失效
watch(
  () => store.settingsRevision,
  () => void qc.invalidateQueries({ queryKey: WI_KEY }),
)

const ado = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: [...WI_KEY, 'ado'],
  enabled: online,
  queryFn: async (): Promise<AdoResponse> => {
    const d = await unwrap(api().GET('/api/ado'))
    if (!Array.isArray(d?.projects) || !Array.isArray(d.libraries)) throw badShape()
    return d
  },
})
const projects = computed(() => ado.data.value?.projects ?? [])
function projectLabel(p: { library_id: string; project: string }): string {
  const lib = ado.data.value?.libraries.find((l) => l.id === p.library_id)
  return `${lib?.name ?? p.library_id} / ${p.project}`
}

const saved = loadSelection()
const projectId = ref<string | null>(null)
const column = ref<string>(saved.column ?? DEFAULT_COLUMN)
const selectedId = ref<number | null>(null)
const keyword = ref('')
const assignee = ref('')
const pageSize = ref<number>(DEFAULT_PAGE_SIZE)
const page = ref(1)

// 项目：已选且仍存在 → 保持；否则 保存的 → 后端 active → 第一个
watch(
  projects,
  (list) => {
    if (projectId.value && list.some((p) => p.id === projectId.value)) return
    const pick = [saved.project_id, ado.data.value?.active_project_id].find((id) =>
      list.some((p) => p.id === id),
    )
    projectId.value = pick ?? list[0]?.id ?? null
  },
  { immediate: true },
)
watch([projectId, column], ([p, c]) => {
  if (p) saveSelection({ project_id: p, column: c })
})
// 切换项目：清掉旧项目的查询，重置选择与筛选
watch(projectId, (p) => {
  qc.removeQueries({
    predicate: (q) =>
      q.queryKey[0] === 'work-items' && q.queryKey[1] === 'p' && q.queryKey[2] !== p,
  })
  selectedId.value = null
  keyword.value = ''
  assignee.value = ''
})
watch(column, () => {
  selectedId.value = null
  assignee.value = ''
})

const list = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: computed(() => [...projectKey(projectId.value ?? ''), 'list', column.value]),
  enabled: computed(() => online.value && projectId.value !== null),
  queryFn: async () => {
    const d = await unwrap(
      api().GET('/api/work-items', {
        params: { query: { project_id: projectId.value!, column: column.value as never } },
      }),
    )
    if (!Array.isArray(d?.items)) throw badShape()
    return d
  },
})
const items = computed<WorkItemSummary[]>(() => list.data.value?.items ?? [])

const colTabs = computed(() =>
  COLUMNS.map((c) => ({
    value: c,
    label: c,
    count: c === column.value && list.data.value ? items.value.length : undefined,
  })),
)
const assignees = computed(() =>
  [...new Set(items.value.map((w) => w.assigned_to).filter((x): x is string => !!x))].sort(),
)
const UNASSIGNED = '__none__'
const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase().replace(/^#/, '')
  return items.value.filter((w) => {
    if (
      assignee.value === UNASSIGNED
        ? w.assigned_to
        : assignee.value && w.assigned_to !== assignee.value
    )
      return false
    return !q || String(w.id).includes(q) || w.title.toLowerCase().includes(q)
  })
})
const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))
const rows = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value),
)
watch([keyword, assignee, pageSize, column, projectId], () => (page.value = 1))
watch(totalPages, (n) => {
  if (page.value > n) page.value = n
})

function refresh() {
  void qc.invalidateQueries({ queryKey: WI_KEY })
}
const refreshing = computed(() => ado.isFetching.value || list.isFetching.value)
</script>

<template>
  <GlassPanel class="toolbar">
    <div class="title">
      <BlockTag>03</BlockTag>
      <h1>工单</h1>
    </div>
    <label class="sel-wrap">
      <span class="sr-only">项目</span>
      <select
        v-model="projectId"
        class="sel"
        data-testid="project-select"
        :disabled="!projects.length"
      >
        <option v-for="p in projects" :key="p.id" :value="p.id">{{ projectLabel(p) }}</option>
      </select>
    </label>
    <AppTabs v-model="column" :items="colTabs" label="看板列" panel-id="wi-list-panel" />
    <span class="grow"></span>
    <label class="sel-wrap">
      <span class="sr-only">指派人</span>
      <select v-model="assignee" class="sel" data-testid="assignee-select">
        <option value="">全部指派人</option>
        <option :value="UNASSIGNED">未指派</option>
        <option v-for="a in assignees" :key="a" :value="a">{{ a }}</option>
      </select>
    </label>
    <SearchBox v-model="keyword" label="搜索工单" placeholder="标题、#编号" />
    <IconButton label="刷新" :aria-busy="refreshing" data-testid="refresh" @click="refresh"
      ><RefreshCw :size="14" aria-hidden="true"
    /></IconButton>
  </GlassPanel>

  <div class="cols">
    <GlassPanel
      id="wi-list-panel"
      as="section"
      role="tabpanel"
      :aria-labelledby="tabTriggerId('wi-list-panel', column)"
      :aria-busy="list.isPending.value && projectId !== null"
      class="list"
    >
      <ErrorNotice v-if="ado.error.value" :error="ado.error.value" retry @retry="ado.refetch()" />
      <div
        v-else-if="ado.isSuccess.value && !projects.length"
        class="empty-state"
        data-testid="no-projects"
      >
        <p>还没有配置 ADO 项目。</p>
        <RouterLink to="/settings" class="wi-link">前往设置</RouterLink>
      </div>
      <ErrorNotice
        v-else-if="list.error.value"
        :error="list.error.value"
        retry
        @retry="list.refetch()"
      />
      <template v-else>
        <p v-if="list.data.value?.truncated" class="note" data-testid="truncated">
          只显示前 500 条
        </p>
        <p v-if="list.data.value?.omitted" class="note" data-testid="omitted">
          有 {{ list.data.value.omitted }} 条无法读取，已跳过
        </p>
        <ul>
          <li v-for="w in rows" :key="w.id">
            <button
              type="button"
              class="row"
              :aria-current="w.id === selectedId ? 'true' : undefined"
              :data-selected="w.id === selectedId"
              :data-testid="`wi-row-${w.id}`"
              @click="selectedId = w.id"
            >
              <span class="kind" :data-type="w.type ?? ''" aria-hidden="true"></span>
              <span class="ox id">#{{ w.id }}</span>
              <span class="t">
                <span class="tt">{{ w.title }}</span>
                <span class="sub"
                  >{{ w.type ?? '—' }} · {{ w.assigned_to ?? '未指派' }} ·
                  {{ w.state ?? '—' }}</span
                >
              </span>
              <span class="mono meta"
                >{{ w.priority === null || w.priority === undefined ? '' : `P${w.priority}`
                }}<br />{{ formatDate(w.changed_date) }}</span
              >
            </button>
          </li>
          <li v-if="list.isPending.value && projectId" class="empty">读取工单中…</li>
          <li v-else-if="rows.length === 0" class="empty">没有匹配的工单</li>
        </ul>
        <nav v-if="filtered.length > 0" class="pager" aria-label="分页">
          <label class="sel-wrap">
            <span class="sr-only">每页条数</span>
            <select v-model.number="pageSize" class="sel" data-testid="page-size">
              <option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }} 条/页</option>
            </select>
          </label>
          <AppButton variant="ghost" :disabled="page <= 1" data-testid="prev-page" @click="page--"
            >上一页</AppButton
          >
          <span class="mono" data-testid="page-info"
            >{{ page }} / {{ totalPages }} · 共 {{ filtered.length }} 条</span
          >
          <AppButton
            variant="ghost"
            :disabled="page >= totalPages"
            data-testid="next-page"
            @click="page++"
            >下一页</AppButton
          >
        </nav>
      </template>
    </GlassPanel>

    <WorkItemDetail
      v-if="selectedId !== null && projectId"
      :id="selectedId"
      :key="`${projectId}:${selectedId}`"
      :project-id="projectId"
      @select="selectedId = $event"
    />
    <GlassPanel v-else as="section" aria-label="工单详情" class="detail-empty">
      <p class="wi-muted">在左侧选择一个工单查看详情</p>
    </GlassPanel>
  </div>

  <InspectorPanel label="AI 分析">
    <div class="ai" data-testid="wi-ai" aria-disabled="true">
      <header class="a-head"><BlockTag>S5</BlockTag><strong>AI 分析</strong></header>
      <p class="note">AI 分析（MCP 分析、复制提示词、AI 会话）将在 S5 提供，当前不可用。</p>
      <fieldset disabled class="ai-actions">
        <legend class="sr-only">AI 分析操作（S5 提供）</legend>
        <AppButton variant="ghost" disabled>复制提示词</AppButton>
        <AppButton disabled>开始分析</AppButton>
      </fieldset>
    </div>
  </InspectorPanel>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 14px;
}
.title {
  display: flex;
  align-items: center;
  gap: 8px;
}
h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}
.grow {
  flex: 1;
}
.sel-wrap {
  display: inline-flex;
}
.sel {
  min-height: var(--target-min);
  max-width: 240px;
  padding: 0 8px;
  background: rgba(255, 255, 255, 0.75);
  border: 0;
  box-shadow: inset 0 0 0 1px var(--line);
  font: inherit;
  font-size: 12.5px;
  color: var(--ink);
}
.cols {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  min-height: 0;
}
.list {
  flex: 1 1 380px;
  max-width: 520px;
  min-width: 0;
  padding: 4px 0;
  overflow: auto;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.row {
  display: grid;
  grid-template-columns: 14px 62px 1fr auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 52px;
  padding: 0 14px;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.row:hover {
  background: rgba(255, 255, 255, 0.7);
}
.row[data-selected='true'] {
  background: rgba(255, 255, 255, 0.85);
  box-shadow: inset 3px 0 0 var(--acc);
  font-weight: 700;
}
.kind {
  width: 8px;
  height: 8px;
  transform: rotate(45deg);
  background: #7a8090;
}
.kind[data-type='Bug'] {
  background: var(--warn);
}
.id {
  font-size: 12px;
  font-weight: 700;
}
.t {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.tt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub,
.note {
  font-size: 11px;
  color: var(--mute);
  font-weight: 400;
}
.meta {
  font-size: 11px;
  color: var(--mute);
  text-align: right;
  line-height: 1.4;
}
.note {
  margin: 0;
  padding: 8px 14px;
}
.empty {
  padding: 16px;
  color: var(--mute);
}
.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  font-size: 12px;
}
.empty-state,
.detail-empty {
  padding: 18px;
}
.detail-empty {
  flex: 999 1 420px;
  min-height: 120px;
}
.wi-link {
  color: var(--ink);
  font-weight: 600;
  text-decoration: underline;
}
.ai {
  display: flex;
  flex-direction: column;
  opacity: 0.7;
}
.a-head {
  padding: 14px 16px 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid var(--line);
}
.ai-actions {
  border: 0;
  margin: 0;
  padding: 0 16px 16px;
  display: flex;
  gap: 6px;
}
</style>
