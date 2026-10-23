<script setup lang="ts">
import { computed, ref } from 'vue'
import { Plus, Square, Terminal } from 'lucide-vue-next'
import ApprovalBar from '@/components/ApprovalBar.vue'
import Button from '@/components/Button.vue'
import Inspector from '@/components/Inspector.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import SearchField from '@/components/SearchField.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import StatusPill from '@/components/StatusPill.vue'
import TextField from '@/components/TextField.vue'
import ToolbarButton from '@/components/ToolbarButton.vue'
import type { PillState } from '@/components/pill'
import { tabTriggerId } from '@/components/tabs'
import { useAiSessions, type SessionState } from './mock/sessions'

const { sessions, filters, messages, approvals, pending, context, tools, send, decide } =
  useAiSessions()

const filter = ref('all')
const selectedId = ref('s1')
const query = ref('')
const draft = ref('')

const list = computed(() =>
  sessions.value.filter((s) => {
    if (filter.value !== 'all' && s.kind !== filter.value) return false
    const q = query.value.trim().toLowerCase()
    return !q || `${s.title} ${s.repo}`.toLowerCase().includes(q)
  }),
)
const selected = computed(() => sessions.value.find((s) => s.id === selectedId.value))
const msgs = computed(() => messages(selectedId.value))
const decided = computed(() => approvals(selectedId.value))
const pendingCmd = computed(() => pending(selectedId.value))
const ctxInfo = computed(() => context(selectedId.value))
const toolStats = computed(() => tools(selectedId.value))
const PILL: Record<SessionState, PillState | null> = {
  approve: 'verify',
  run: 'running',
  done: 'success',
  old: null,
}
const PILL_TEXT: Partial<Record<SessionState, string>> = { approve: '待审批' }
const DECISION = { once: '已允许一次', always: '本会话总是允许', deny: '已拒绝' } as const
const allowed = computed(() =>
  decided.value.filter((a) => a.decision === 'always').map((a) => a.command),
)

function submit() {
  if (!draft.value.trim()) return
  send(selectedId.value, draft.value)
  draft.value = ''
}
</script>

<template>
  <div class="ai">
    <section aria-label="会话列表" class="sessions">
      <header class="topbar" data-tauri-drag-region>
        <h1>AI 会话</h1>
        <span class="grow"></span>
        <ToolbarButton label="新会话"><Plus :size="16" aria-hidden="true" /></ToolbarButton>
      </header>
      <div class="filters">
        <SearchField v-model="query" label="搜索会话" placeholder="搜索会话" />
        <SegmentedControl
          v-model="filter"
          :items="filters"
          label="按 AI 筛选"
          panel-id="ai-sessions-panel"
          fill
        />
      </div>
      <div
        id="ai-sessions-panel"
        role="tabpanel"
        :aria-labelledby="tabTriggerId('ai-sessions-panel', filter)"
        class="slist"
      >
        <ul class="b-list">
          <li v-for="s in list" :key="s.id">
            <button
              type="button"
              class="sess b-row"
              :aria-current="s.id === selectedId ? 'true' : undefined"
              :data-selected="s.id === selectedId ? 'true' : 'false'"
              :data-testid="`session-${s.id}`"
              @click="selectedId = s.id"
            >
              <span class="b-row-l1">
                <span class="badge" :data-kind="s.kind" aria-hidden="true">{{ s.abbr }}</span>
                <span class="b-row-title">{{ s.title }}</span>
              </span>
              <span class="b-row-l2">
                <span class="mono">{{ s.repo }}</span>
                <span aria-hidden="true">·</span>
                <StatusPill
                  v-if="PILL[s.state]"
                  :state="PILL[s.state]!"
                  :title="PILL_TEXT[s.state] ?? undefined"
                />
                <span v-else>{{ s.note }}</span>
                <span class="sr-only">{{ s.note }}</span>
              </span>
            </button>
          </li>
        </ul>
      </div>
    </section>

    <section v-if="selected" aria-label="对话" class="chat">
      <header class="topbar" data-tauri-drag-region>
        <strong class="ct">{{ selected.title }}</strong>
        <span class="mono sub">{{ selected.repo }}</span>
        <span class="grow"></span>
        <span class="chip">逐条审批</span>
        <ToolbarButton label="中断"><Square :size="14" aria-hidden="true" /></ToolbarButton>
        <ToolbarButton label="在终端打开"><Terminal :size="16" aria-hidden="true" /></ToolbarButton>
        <InspectorToggle />
      </header>

      <div class="flow">
        <div
          v-for="(m, i) in msgs"
          :key="`${selectedId}-${i}`"
          class="msg"
          :data-role="m.role"
          data-testid="message"
        >
          <span class="who">{{ m.who }}</span>
          <div v-if="m.role === 'ai'" class="bubble ai-b">
            <div v-if="m.tools?.length" class="tools">
              <div v-for="t in m.tools" :key="t.k + t.a" class="tool">
                <span class="tick" aria-hidden="true">✓</span>
                <b class="tk">{{ t.k }}</b>
                <span class="mono ta">{{ t.a }}</span>
                <span class="mono sub">{{ t.r }}</span>
              </div>
            </div>
            <p>
              <template v-for="(part, j) in m.body" :key="j"
                ><code v-if="typeof part !== 'string'" class="mono">{{ part.code }}</code
                ><template v-else>{{ part }}</template></template
              >
            </p>
          </div>
          <div v-else class="bubble you-b">
            <p>
              <template v-for="(part, j) in m.body" :key="j">{{
                typeof part === 'string' ? part : part.code
              }}</template>
            </p>
          </div>
        </div>
        <p
          v-for="(a, i) in decided"
          :key="i"
          class="decided mono"
          :data-decision="a.decision"
          data-testid="decision-log"
        >
          {{ DECISION[a.decision] }}：{{ a.command }}
        </p>
        <ApprovalBar
          v-if="pendingCmd"
          :command="pendingCmd"
          @decide="(d) => decide(selectedId, d)"
        />
      </div>

      <form class="composer" @submit.prevent="submit">
        <TextField
          v-model="draft"
          class="grow"
          label="给 AI 的消息"
          placeholder="继续追问 · / 命令 · @ 引用文件"
          multiline
        />
        <Button type="submit" variant="primary">发送</Button>
      </form>
    </section>

    <Inspector v-if="selected && ctxInfo" label="会话检查器">
      <div class="ctx" data-testid="ai-inspector">
        <div class="ctx-block">
          <div class="ctx-head">
            <span class="lbl">上下文用量</span><span class="pct">{{ ctxInfo.pct }}%</span>
          </div>
          <div
            class="meter"
            role="meter"
            aria-label="上下文占用"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="ctxInfo.pct"
          >
            <span :style="{ width: `${ctxInfo.pct}%` }"></span>
          </div>
          <dl>
            <template v-for="r in ctxInfo.rows" :key="r.k">
              <dt>{{ r.k }}</dt>
              <dd class="mono">{{ r.v }}</dd>
            </template>
          </dl>
        </div>
        <div class="ctx-block">
          <span class="lbl">目录 · 分支 · 关联工单</span>
          <dl>
            <dt>目录</dt>
            <dd class="mono">~/code/{{ selected.repo }}</dd>
            <dt>分支</dt>
            <dd class="mono">main</dd>
            <dt>关联工单</dt>
            <dd class="mono">{{ selected.title.match(/#\d+/)?.[0] ?? '—' }}</dd>
          </dl>
        </div>
        <div class="ctx-block">
          <span class="lbl">工具调用统计</span>
          <dl>
            <template v-for="t in toolStats" :key="t.k + t.a">
              <dt>{{ t.k }}</dt>
              <dd class="mono">{{ t.r }}</dd>
            </template>
          </dl>
        </div>
        <div class="ctx-block">
          <span class="lbl">已允许命令</span>
          <p v-if="!allowed.length" class="none">本会话尚未允许任何命令</p>
          <ul v-else class="allowed">
            <li v-for="c in allowed" :key="c" class="mono">{{ c }}</li>
          </ul>
        </div>
      </div>
    </Inspector>
  </div>
</template>

<style scoped>
.ai {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
}
.topbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
  height: var(--topbar-h);
  padding: 0 12px 0 16px;
  box-sizing: border-box;
}
h1 {
  margin: 0;
  font-size: var(--text-page);
  font-weight: 700;
}
.grow {
  flex: 1;
}
.sessions {
  flex: 0 0 var(--list-w);
  width: var(--list-w);
  display: flex;
  flex-direction: column;
  background: var(--bg-list);
  border-right: 1px solid var(--line);
  min-width: 0;
}
.filters {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 12px 10px;
}
.slist {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.sess .b-row-l1 {
  align-items: center;
}
.sess {
  padding-left: 14px;
}
.badge {
  flex: none;
  min-width: 22px;
  height: 18px;
  padding: 0 4px;
  border-radius: 4px;
  display: inline-grid;
  place-items: center;
  font-size: 10.5px;
  font-weight: 700;
  background: var(--ctl);
  color: var(--ink);
}
.chat {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.chat .topbar {
  border-bottom: 1px solid var(--line);
}
.ct {
  font-size: var(--text-page);
}
.sub {
  font-size: var(--text-sub);
  color: var(--mute);
}
.chip {
  font-size: var(--text-sub);
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--ctl);
  color: var(--mute-tint);
}
.flow {
  flex: 1;
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: auto;
}
.msg {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 760px;
}
.msg[data-role='user'] {
  align-self: flex-end;
  align-items: flex-end;
}
.who {
  font-size: var(--text-sub);
  color: var(--mute);
}
.bubble {
  padding: 8px 12px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.you-b {
  background: var(--accent);
  color: var(--on-accent);
}
.ai-b {
  background: var(--ctl);
}
.bubble p {
  margin: 0;
  font-size: var(--text-long);
  line-height: 1.65;
}
.tools {
  display: flex;
  flex-direction: column;
  border-radius: var(--r-ctl);
  background: var(--bg-window);
  box-shadow: inset 0 0 0 1px var(--line);
}
.tool {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 28px;
  padding: 0 10px;
  font-size: var(--text-sub);
}
.tick {
  color: var(--st-success-fg);
}
.tk {
  width: 44px;
}
.ta {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
code {
  font-size: var(--text-sub);
  padding: 0 4px;
  border-radius: 4px;
  background: var(--bg-window);
}
.decided {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.composer {
  margin: 0 16px 16px;
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.ctx {
  display: flex;
  flex-direction: column;
  flex: 1;
}
.ctx-block {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-bottom: 1px solid var(--line);
  font-size: var(--text-sub);
}
.ctx-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.pct {
  font-size: var(--text-page);
  font-weight: 700;
}
.meter {
  height: 6px;
  border-radius: 3px;
  background: var(--ctl);
  overflow: hidden;
}
.meter span {
  display: block;
  height: 100%;
  background: var(--accent);
}
dl {
  margin: 4px 0 0;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 5px 12px;
}
dt {
  color: var(--mute);
}
dd {
  margin: 0;
  text-align: right;
  overflow-wrap: anywhere;
}
.none {
  margin: 0;
  color: var(--mute);
}
.allowed {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
