<script setup lang="ts">
import { computed, ref } from 'vue'
import { Copy, RefreshCw } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppTabs from '@/components/AppTabs.vue'
import { tabTriggerId } from '@/components/tabs'
import BlockTag from '@/components/BlockTag.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import IconButton from '@/components/IconButton.vue'
import InspectorPanel from '@/components/InspectorPanel.vue'
import SearchBox from '@/components/SearchBox.vue'
import { useWorkItems } from './mock/work-items'

const { items, columns, agents, repos, promptFor } = useWorkItems()

const column = ref('开发中')
const query = ref('')
const selectedId = ref(48213)
const tab = ref('desc')
const agent = ref('claude')
const repo = ref(repos[0]!)
const copied = ref(false)
const started = ref(false)

const colTabs = computed(() =>
  columns.map((c) => ({
    value: c,
    label: c,
    count: items.value.filter((w) => w.column === c).length,
  })),
)
const rows = computed(() =>
  items.value.filter((w) => {
    if (w.column !== column.value) return false
    const q = query.value.trim().toLowerCase()
    return !q || `${w.title} #${w.id} ${w.who}`.toLowerCase().includes(q)
  }),
)
const selected = computed(() => items.value.find((w) => w.id === selectedId.value))
const detailTabs = computed(() => {
  const w = selected.value
  return [
    { value: 'desc', label: '描述' },
    { value: 'comments', label: '评论', count: w?.comments.length ?? 0 },
    { value: 'children', label: '子项', count: w?.children.length ?? 0 },
    { value: 'files', label: '附件', count: w?.attachments.length ?? 0 },
    { value: 'prs', label: '关联 PR', count: w?.prs.length ?? 0 },
  ]
})
const prompt = computed(() => (selected.value ? promptFor(selected.value) : ''))

function select(id: number) {
  selectedId.value = id
  tab.value = 'desc'
  copied.value = false
  started.value = false
}
function copyPrompt() {
  // mock：只改状态，不写剪贴板
  copied.value = true
}
</script>

<template>
  <GlassPanel class="toolbar">
    <div class="title">
      <BlockTag>03</BlockTag>
      <h1>工单</h1>
    </div>
    <AppTabs v-model="column" :items="colTabs" label="看板列" panel-id="wi-list-panel" />
    <span class="grow"></span>
    <SearchBox v-model="query" label="搜索工单" placeholder="标题、#编号、负责人" />
    <IconButton label="刷新"><RefreshCw :size="14" aria-hidden="true" /></IconButton>
    <AppButton>＋ 新建工单</AppButton>
  </GlassPanel>

  <div class="cols">
    <GlassPanel
      id="wi-list-panel"
      as="section"
      role="tabpanel"
      :aria-labelledby="tabTriggerId('wi-list-panel', column)"
      class="list"
    >
      <ul>
        <li v-for="w in rows" :key="w.id">
          <button
            type="button"
            class="row"
            :aria-current="w.id === selectedId ? 'true' : undefined"
            :data-selected="w.id === selectedId"
            :data-testid="`wi-row-${w.id}`"
            @click="select(w.id)"
          >
            <span class="kind" :data-type="w.type" aria-hidden="true"></span>
            <span class="ox id">#{{ w.id }}</span>
            <span class="t"
              ><span class="tt">{{ w.title }}</span
              ><span class="sub">{{ w.type }} · {{ w.who }}</span></span
            >
            <span class="mono age">{{ w.age }}</span>
          </button>
        </li>
        <li v-if="rows.length === 0" class="empty">没有匹配的工单</li>
      </ul>
    </GlassPanel>

    <GlassPanel v-if="selected" as="section" aria-label="工单详情" class="detail">
      <header class="d-head">
        <div class="d-line">
          <span class="type ox skew" :data-type="selected.type">{{
            selected.type.toUpperCase()
          }}</span>
          <span class="ox idn">#{{ selected.id }}</span>
          <BlockTag>{{ selected.priority }}</BlockTag>
          <span class="st"><span class="sq" aria-hidden="true"></span>{{ selected.state }}</span>
          <span class="grow"></span>
          <IconButton label="复制链接"><Copy :size="14" aria-hidden="true" /></IconButton>
        </div>
        <h2>{{ selected.title }}</h2>
        <dl class="props">
          <template v-for="p in selected.props" :key="p.k">
            <dt class="lbl">{{ p.k }}</dt>
            <dd>{{ p.v }}</dd>
          </template>
        </dl>
      </header>
      <AppTabs v-model="tab" :items="detailTabs" label="工单内容" class="d-tabs">
        <div class="d-body" data-testid="wi-body">
          <template v-if="tab === 'desc'">
            <p v-for="(p, i) in selected.body" :key="i">{{ p }}</p>
          </template>
          <template v-else-if="tab === 'comments'">
            <div v-for="(c, i) in selected.comments" :key="i" class="comment">
              <span class="cw"
                >{{ c.who }} <span class="mono muted">· {{ c.when }}</span></span
              >
              <span>{{ c.text }}</span>
            </div>
            <p v-if="!selected.comments.length" class="muted">暂无评论</p>
          </template>
          <template v-else-if="tab === 'children'">
            <p v-for="c in selected.children" :key="c" class="mono">{{ c }}</p>
            <p v-if="!selected.children.length" class="muted">暂无子项</p>
          </template>
          <template v-else-if="tab === 'files'">
            <p
              v-for="a in selected.attachments"
              :key="a.name"
              class="mono"
              :data-blocked="a.blocked"
            >
              <template v-if="a.blocked">外部图片已拦截 · {{ a.host }}</template>
              <template v-else>{{ a.name }} · {{ a.size }}</template>
            </p>
            <p v-if="!selected.attachments.length" class="muted">暂无附件</p>
          </template>
          <template v-else>
            <p v-for="p in selected.prs" :key="p" class="mono">{{ p }}</p>
            <p v-if="!selected.prs.length" class="muted">暂无关联 PR</p>
          </template>
        </div>
      </AppTabs>
    </GlassPanel>
  </div>

  <InspectorPanel v-if="selected" label="AI 分析">
    <div class="ai" data-testid="wi-ai">
      <header class="a-head">
        <BlockTag>AGENT</BlockTag><strong>AI 分析</strong><span class="grow"></span
        ><span class="lbl">MCP · ADO</span>
      </header>
      <div role="radiogroup" aria-label="选择 AI" class="agents">
        <button
          v-for="a in agents"
          :key="a.id"
          type="button"
          role="radio"
          class="agent cut-xs"
          :aria-checked="agent === a.id"
          :data-testid="`agent-${a.id}`"
          @click="agent = a.id"
        >
          <span class="ox ini cut-xs" aria-hidden="true">{{ a.initial }}</span>
          <span class="an"
            ><span class="ox nm">{{ a.name }}</span
            ><span class="tr">{{ a.trait }}</span></span
          >
        </button>
      </div>
      <dl class="meta">
        <dt class="lbl">仓库</dt>
        <dd>
          <label class="sr-only" for="wi-repo">仓库</label>
          <select id="wi-repo" v-model="repo" class="sel mono">
            <option v-for="r in repos" :key="r" :value="r">{{ r }}</option>
          </select>
        </dd>
        <dt class="lbl">分支</dt>
        <dd class="mono small">fix/{{ selected.id }}-menu-cache（新建）</dd>
        <dt class="lbl">带入</dt>
        <dd class="small">
          描述 · 评论 {{ selected.comments.length }} · 附件 {{ selected.attachments.length }} · 子项
          {{ selected.children.length }}
        </dd>
      </dl>
      <div class="prompt-wrap">
        <span class="lbl">提示词预览</span>
        <pre class="prompt mono cut-xs" data-testid="wi-prompt">{{ prompt }}</pre>
      </div>
      <div class="a-actions">
        <AppButton variant="ghost" data-testid="copy-prompt" @click="copyPrompt">{{
          copied ? '已复制' : '复制提示词'
        }}</AppButton>
        <AppButton class="go" data-testid="start-analysis" @click="started = true">{{
          started ? '已开始（mock）' : '开始分析'
        }}</AppButton>
      </div>
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
.cols {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  min-height: 0;
}
.list {
  flex: 1 1 340px;
  max-width: 420px;
  min-width: 0;
  padding: 4px 0;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.row {
  display: grid;
  grid-template-columns: 14px 62px 1fr 36px;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 46px;
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
.kind[data-type='需求'] {
  background: var(--ink);
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
.muted {
  font-size: 11px;
  color: var(--mute);
  font-weight: 400;
}
.age {
  font-size: 11px;
  color: var(--mute);
  text-align: right;
}
.empty {
  padding: 16px;
  color: var(--mute);
}
.detail {
  flex: 999 1 420px;
  min-width: 0;
  display: flex;
  flex-direction: column;
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
}
.props {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(4, auto 1fr);
  gap: 6px 12px;
  align-items: center;
}
.props dd {
  margin: 0;
  font-size: 12.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.d-tabs {
  padding: 8px 14px 0;
}
.d-tabs :deep(.tab-panel) {
  margin: 0 -14px;
}
.d-body {
  padding: 12px 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13.5px;
  line-height: 1.75;
  color: #2a2e36;
  max-width: 680px;
}
.d-body p {
  margin: 0;
}
.comment {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  background: rgba(20, 22, 26, 0.04);
}
.cw {
  font-size: 12px;
  font-weight: 600;
}
.a-head {
  padding: 14px 16px 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid var(--line);
}
.ai {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.agents {
  padding: 10px 10px 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.agent {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 0 10px;
  border: 0;
  cursor: pointer;
  text-align: left;
  font: inherit;
  background: rgba(255, 255, 255, 0.55);
  color: var(--ink);
  box-shadow: inset 0 0 0 1px var(--line);
}
.agent[aria-checked='true'] {
  background: var(--ink);
  color: #fff;
  box-shadow: inset 0 0 0 1.5px var(--acc);
}
.ini {
  flex: none;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  font-size: 11.5px;
  font-weight: 800;
  background: var(--faint);
}
.agent[aria-checked='true'] .ini {
  background: var(--acc);
  color: var(--ink);
}
.an {
  display: flex;
  flex-direction: column;
}
.nm {
  font-size: 13px;
  font-weight: 700;
}
.tr {
  font-size: 11px;
  opacity: 0.8;
}
.meta {
  margin: 0;
  padding: 8px 16px 10px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 7px 12px;
  align-items: center;
  border-bottom: 1px solid var(--line);
}
.meta dd {
  margin: 0;
}
.small {
  font-size: 12px;
}
.sel {
  width: 100%;
  min-height: var(--target-min);
  padding: 0 8px;
  background: rgba(255, 255, 255, 0.75);
  border: 0;
  box-shadow: inset 0 0 0 1px var(--line);
  font-size: 11.5px;
  color: var(--ink);
}
.prompt-wrap {
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}
.prompt {
  flex: 1;
  min-height: 150px;
  margin: 0;
  padding: 10px 12px;
  background: rgba(20, 22, 26, 0.9);
  color: #d9dce3;
  font-size: 11px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow: auto;
}
.a-actions {
  padding: 0 16px 16px;
  display: flex;
  gap: 6px;
}
.go {
  flex: 1;
}
</style>
