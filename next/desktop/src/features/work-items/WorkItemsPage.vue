<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { ChevronLeft, ChevronRight, FileText, RefreshCw } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import Inspector from '@/components/Inspector.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import SearchField from '@/components/SearchField.vue'
import Skeleton from '@/components/Skeleton.vue'
import Tag from '@/components/Tag.vue'
import ToolbarButton from '@/components/ToolbarButton.vue'
import { tabTriggerId } from '@/components/tabs'
import BoardRoute from './BoardRoute.vue'
import ErrorNotice from './ErrorNotice.vue'
import WorkItemDetail from './WorkItemDetail.vue'
import WorkItemRow from './WorkItemRow.vue'
import {
  DEFAULT_COLUMN,
  DEFAULT_PAGE_SIZE,
  PAGE_SIZES,
  badShape,
  unwrap,
  type AdoResponse,
  type WorkItemDetail as WiDetail,
  type WorkItemSummary,
} from './api'
import { formatMonthDay, kindColor } from './format'
import { QUERY_DEFAULTS, WI_KEY, projectKey, useBoardColumns, useWiApi } from './queries'
import { loadSelection, saveSelection } from './selection'
import './panes.css'

const { api, online, qc, store } = useWiApi()

// settings.changed：library/PAT/项目可能变了，使项目列表与全部工单查询失效
// 先取消在途请求再失效：否则 invalidate 会复用在途请求，旧来源的响应回来后清掉失效标记（CR-S2B-001）
watch(
  () => store.settingsRevision,
  async () => {
    await qc.cancelQueries({ queryKey: WI_KEY })
    await qc.invalidateQueries({ queryKey: WI_KEY })
  },
)

const ado = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: [...WI_KEY, 'ado'],
  enabled: online,
  queryFn: async ({ signal }): Promise<AdoResponse> => {
    const d = await unwrap(api().GET('/api/ado', { signal }))
    if (!Array.isArray(d?.projects) || !Array.isArray(d.libraries)) throw badShape()
    return d
  },
})
const projects = computed(() => ado.data.value?.projects ?? [])
function projectLabel(p: { library_id: string; project: string }): string {
  const lib = ado.data.value?.libraries.find((l) => l.id === p.library_id)
  return `${lib?.name ?? p.library_id} / ${p.project}`
}

// 看板列以接口为准（顺序即线路顺序），读不到时退回内置五列
const { columns: boardColumns, defaultColumn } = useBoardColumns()

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
// 当前列不在接口给的列里（例如保存的列已不存在）：退回接口默认列，再退回第一列
watch(boardColumns, (cols) => {
  if (cols.includes(column.value)) return
  const dflt = defaultColumn.value
  column.value = (dflt && cols.includes(dflt) ? dflt : cols[0]) ?? DEFAULT_COLUMN
})
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
  queryFn: async ({ signal }) => {
    const d = await unwrap(
      api().GET('/api/work-items', {
        signal,
        params: { query: { project_id: projectId.value!, column: column.value as never } },
      }),
    )
    if (!Array.isArray(d?.items)) throw badShape()
    return d
  },
})
const items = computed<WorkItemSummary[]>(() => list.data.value?.items ?? [])

// 每站条数：只有读过的列才有数（缓存里的列表），没读过的站留空，不为凑数多发请求
const cacheTick = ref(0)
const stopCache = qc.getQueryCache().subscribe(() => cacheTick.value++)
onBeforeUnmount(stopCache)
const columnCounts = computed<Record<string, string | undefined>>(() => {
  void cacheTick.value
  const out: Record<string, string | undefined> = {}
  for (const c of boardColumns.value) {
    const d = qc.getQueryData<{ items?: unknown[]; truncated?: boolean }>([
      ...projectKey(projectId.value ?? ''),
      'list',
      c,
    ])
    if (d && Array.isArray(d.items)) out[c] = `${d.items.length}${d.truncated ? '+' : ''}`
  }
  return out
})
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
const selectedDetail = ref<WiDetail | null>(null)
const projectName = computed(
  () => projects.value.find((p) => p.id === projectId.value)?.project ?? '',
)
const subtitle = computed(() =>
  [projectName.value, list.data.value ? `${column.value} ${items.value.length} 项` : column.value]
    .filter(Boolean)
    .join('，'),
)
const inspectorRows = computed(() => {
  const x = selectedDetail.value
  if (!x) return []
  return [
    ['优先级', x.priority === null || x.priority === undefined ? '—' : `P${x.priority}`],
    ['指派', x.assigned_to ?? '未指派'],
    ['看板列', x.board_column ?? '—'],
    ['严重度', x.severity ?? '—'],
    ['区域', x.area_path ?? '—'],
    ['迭代', x.iteration_path ?? '—'],
  ] as [string, string][]
})
const refreshing = computed(() => ado.isFetching.value || list.isFetching.value)
</script>

<template>
  <div class="wi">
    <section aria-label="工单列表" class="listcol">
      <header class="topbar" data-tauri-drag-region>
        <div class="ttl">
          <h1>工单</h1>
          <span class="sub">{{ subtitle }}</span>
        </div>
        <span class="grow"></span>
        <ToolbarButton label="刷新" :aria-busy="refreshing" data-testid="refresh" @click="refresh"
          ><RefreshCw :size="16" aria-hidden="true"
        /></ToolbarButton>
      </header>
      <div class="filters">
        <SearchField v-model="keyword" label="搜索工单" placeholder="标题、#编号" />
        <BoardRoute
          v-model="column"
          :columns="boardColumns"
          :counts="columnCounts"
          label="看板列"
          panel-id="wi-list-panel"
        />
      </div>

      <div
        id="wi-list-panel"
        role="tabpanel"
        :aria-labelledby="tabTriggerId('wi-list-panel', column)"
        :aria-busy="list.isPending.value && projectId !== null"
        class="listbody"
      >
        <ErrorNotice v-if="ado.error.value" :error="ado.error.value" retry @retry="ado.refetch()" />
        <EmptyState
          v-else-if="ado.isSuccess.value && !projects.length"
          :icon="FileText"
          title="没有 ADO 项目"
          description="还没有配置 ADO 项目。在设置中添加组织地址和项目后，工单会显示在这里。"
          data-testid="no-projects"
        >
          <template #actions>
            <RouterLink to="/settings" class="link-btn">前往设置</RouterLink>
          </template>
        </EmptyState>
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
          <ul class="rows">
            <li v-for="w in rows" :key="w.id">
              <WorkItemRow
                :id="w.id"
                :title="w.title"
                :assignee="w.assigned_to"
                :priority="w.priority"
                :date="formatMonthDay(w.changed_date)"
                :type="w.type"
                :kind-color="kindColor(w.type)"
                :selected="w.id === selectedId"
                :data-testid="`wi-row-${w.id}`"
                @click="selectedId = w.id"
              />
            </li>
          </ul>
          <template v-if="list.isPending.value && projectId">
            <Skeleton />
            <p class="sr-only" role="status">读取工单中…</p>
          </template>
          <p v-else-if="rows.length === 0" class="empty">没有匹配的工单</p>
        </template>
      </div>

      <nav v-if="filtered.length > 0" class="pager" aria-label="分页">
        <label class="sel-wrap">
          <span class="sr-only">每页条数</span>
          <select v-model.number="pageSize" class="sel" data-testid="page-size">
            <option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }} 条/页</option>
          </select>
        </label>
        <span class="info" data-testid="page-info"
          >第 {{ page }} / {{ totalPages }} 页，共 {{ filtered.length }} 条</span
        >
        <span class="pg-btns">
          <ToolbarButton
            label="上一页"
            :disabled="page <= 1"
            data-testid="prev-page"
            @click="page--"
            ><ChevronLeft :size="16" aria-hidden="true"
          /></ToolbarButton>
          <ToolbarButton
            label="下一页"
            :disabled="page >= totalPages"
            data-testid="next-page"
            @click="page++"
            ><ChevronRight :size="16" aria-hidden="true"
          /></ToolbarButton>
        </span>
      </nav>
    </section>

    <div class="detailcol">
      <header class="topbar" data-tauri-drag-region>
        <label class="sel-wrap">
          <span class="sr-only">项目</span>
          <select
            v-model="projectId"
            class="sel strong"
            data-testid="project-select"
            :disabled="!projects.length"
          >
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ projectLabel(p) }}</option>
          </select>
        </label>
        <label class="sel-wrap">
          <span class="sr-only">指派人</span>
          <select v-model="assignee" class="sel" data-testid="assignee-select">
            <option value="">全部指派人</option>
            <option :value="UNASSIGNED">未指派</option>
            <option v-for="a in assignees" :key="a" :value="a">{{ a }}</option>
          </select>
        </label>
        <span class="grow"></span>
        <InspectorToggle />
      </header>
      <section aria-label="工单详情" class="detailbody">
        <WorkItemDetail
          v-if="selectedId !== null && projectId"
          :id="selectedId"
          :key="`${projectId}:${selectedId}`"
          :project-id="projectId"
          @select="selectedId = $event"
          @loaded="selectedDetail = $event"
        />
        <p v-else class="none">在左侧选择一个工单查看详情</p>
      </section>
    </div>

    <Inspector label="工单检查器">
      <div class="insp">
        <template v-if="selectedDetail">
          <dl class="props" data-testid="wi-props">
            <dt>状态</dt>
            <dd>
              <span class="st"
                ><span
                  class="kd"
                  :style="{ background: kindColor(selectedDetail.type) }"
                  aria-hidden="true"
                ></span
                >{{ selectedDetail.state ?? '—' }}</span
              >
            </dd>
            <template v-for="[k, v] in inspectorRows" :key="k">
              <dt>{{ k }}</dt>
              <dd>{{ v }}</dd>
            </template>
            <template v-if="selectedDetail.tags?.length">
              <dt>标签</dt>
              <dd>
                <ul class="tags" aria-label="标签">
                  <li v-for="t in selectedDetail.tags ?? []" :key="t">
                    <Tag>{{ t }}</Tag>
                  </li>
                </ul>
              </dd>
            </template>
          </dl>
        </template>
        <div v-if="!selectedDetail" class="ai" data-testid="wi-ai" aria-disabled="true">
          <strong>AI 分析</strong>
          <p class="note">
            即将推出：AI 分析（MCP 分析、复制提示词、AI 会话）将在 S5 提供，当前不可用。
          </p>
          <fieldset disabled class="ai-actions">
            <legend class="sr-only">AI 分析操作（S5 提供）</legend>
            <Button disabled>复制提示词</Button>
            <Button variant="primary" disabled>开始分析</Button>
          </fieldset>
        </div>
      </div>
    </Inspector>
  </div>
</template>

<style scoped>
.wi {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
}
.topbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 4px;
  height: var(--topbar-h);
  padding: 0 12px 0 16px;
  box-sizing: border-box;
}
.detailcol .topbar {
  border-bottom: 1px solid var(--line);
  padding-left: 12px;
}
.ttl {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  min-width: 0;
}
h1 {
  margin: 0;
  font-size: var(--text-page);
  font-weight: 700;
}
.sub {
  font-size: 11.5px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.grow {
  flex: 1;
}
.listcol {
  flex: 0 0 var(--list-w);
  width: var(--list-w);
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-list);
  border-right: 1px solid var(--line);
}
.filters {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 12px 10px;
}
.listbody {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
.rows {
  flex: none;
  margin: 0;
  padding: 2px 8px 12px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.note {
  margin: 0;
  padding: 6px 16px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.empty {
  margin: 0;
  padding: 16px;
  color: var(--mute);
}
.pager {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-top: 1px solid var(--line);
  font-size: var(--text-sub);
  color: var(--mute);
}
.info {
  flex: 1 0 auto;
  text-align: center;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.pg-btns {
  display: inline-flex;
  gap: 2px;
}
.sel-wrap {
  display: inline-flex;
}
.sel {
  min-height: var(--ctl-h);
  max-width: 240px;
  padding: 0 6px;
  border: 0;
  border-radius: var(--r-ctl);
  background: transparent;
  font: inherit;
  color: var(--mute);
}
.sel.strong {
  color: var(--ink);
  font-weight: 500;
}
.pager .sel {
  background: var(--ctl);
  color: var(--ink);
}
.link-btn {
  display: inline-flex;
  align-items: center;
  min-height: var(--ctl-h);
  padding: 0 12px;
  border-radius: var(--r-ctl);
  background: var(--accent);
  color: var(--on-accent);
  font-weight: 600;
  text-decoration: none;
}
.detailcol {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.detailbody {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.none {
  flex: 1;
  margin: 0;
  display: grid;
  place-items: center;
  color: var(--mute);
  font-size: var(--text-page);
}
.insp {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 18px 16px;
  font-size: var(--text-body);
}
.props {
  margin: 0;
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 9px 10px;
}
.props dt {
  color: var(--mute);
}
.props dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.st {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 500;
}
.kd {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.tags {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.ai {
  display: flex;
  flex-direction: column;
  gap: 8px;
  opacity: 0.75;
}
.ai .note {
  padding: 0;
}
.ai-actions {
  border: 0;
  margin: 0;
  padding: 0;
  display: flex;
  gap: 6px;
}
</style>
