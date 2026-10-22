<script setup lang="ts">
import { computed, ref } from 'vue'
import { Square, Terminal } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppTabs from '@/components/AppTabs.vue'
import ApprovalBar from '@/components/ApprovalBar.vue'
import BlockTag from '@/components/BlockTag.vue'
import EnergyBar from '@/components/EnergyBar.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import IconButton from '@/components/IconButton.vue'
import InspectorPanel from '@/components/InspectorPanel.vue'
import StatusDot from '@/components/StatusDot.vue'
import SearchBox from '@/components/SearchBox.vue'
import TextInput from '@/components/TextInput.vue'
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
const dot = (s: SessionState) => (s === 'approve' ? 'warn' : s === 'run' ? 'run' : 'idle')
const DECISION = { once: '已允许一次', always: '本会话总是允许', deny: '已拒绝' } as const

function submit() {
  if (!draft.value.trim()) return
  send(selectedId.value, draft.value)
  draft.value = ''
}
</script>

<template>
  <div class="split">
    <GlassPanel as="section" aria-label="会话列表" class="sessions">
      <header class="s-head">
        <BlockTag>04</BlockTag>
        <h1>AI 会话</h1>
        <span class="grow"></span>
        <AppButton>＋ 新会话</AppButton>
      </header>
      <div class="s-filters">
        <AppTabs v-model="filter" :items="filters" label="按 AI 筛选" />
        <SearchBox v-model="query" label="搜索会话" placeholder="搜索会话" />
      </div>
      <ul>
        <li v-for="s in list" :key="s.id">
          <button
            type="button"
            class="sess"
            :aria-current="s.id === selectedId ? 'true' : undefined"
            :data-selected="s.id === selectedId"
            :data-testid="`session-${s.id}`"
            @click="selectedId = s.id"
          >
            <span class="ox abbr cut-xs" aria-hidden="true">{{ s.abbr }}</span>
            <span class="st"
              ><span class="tt">{{ s.title }}</span
              ><span class="mono sub">{{ s.repo }} · {{ s.note }}</span></span
            >
            <StatusDot :state="dot(s.state)" />
          </button>
        </li>
      </ul>
    </GlassPanel>

    <GlassPanel v-if="selected" as="section" aria-label="对话" class="chat">
      <header class="c-head">
        <span class="ox abbr cut-xs dark" aria-hidden="true">{{ selected.abbr }}</span>
        <strong>{{ selected.title }}</strong>
        <span class="mono sub">{{ selected.repo }}</span>
        <span class="grow"></span>
        <span class="chip skew mono">逐条审批</span>
        <IconButton label="中断"><Square :size="13" aria-hidden="true" /></IconButton>
        <IconButton label="在终端打开"><Terminal :size="14" aria-hidden="true" /></IconButton>
      </header>

      <div class="flow">
        <div v-for="(m, i) in msgs" :key="`${selectedId}-${i}`" class="msg" data-testid="message">
          <span class="lbl who" :class="{ strong: m.role === 'ai' }">{{ m.who }}</span>
          <div v-if="m.role === 'ai'" class="reply">
            <div v-if="m.tools?.length" class="tools cut-xs">
              <div v-for="t in m.tools" :key="t.k + t.a" class="tool">
                <span class="tick" aria-hidden="true">✓</span>
                <b class="ox tk">{{ t.k }}</b>
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
          <p v-else>
            <template v-for="(part, j) in m.body" :key="j">{{
              typeof part === 'string' ? part : part.code
            }}</template>
          </p>
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
        <TextInput
          v-model="draft"
          class="grow"
          label="给 AI 的消息"
          placeholder="继续追问 · / 命令 · @ 引用文件"
          multiline
        />
        <AppButton type="submit">发送</AppButton>
      </form>
    </GlassPanel>
  </div>

  <InspectorPanel v-if="selected && ctxInfo" label="会话检查器">
    <div class="ctx" data-testid="ai-inspector">
      <div class="ctx-block">
        <div class="ctx-head">
          <span class="lbl">Context</span><span class="ox pct">{{ ctxInfo.pct }}%</span>
        </div>
        <EnergyBar
          :value="Math.round((ctxInfo.pct / 100) * ctxInfo.segments)"
          :segments="ctxInfo.segments"
          label="上下文占用"
        />
        <dl>
          <template v-for="r in ctxInfo.rows" :key="r.k">
            <dt class="lbl">{{ r.k }}</dt>
            <dd class="mono">{{ r.v }}</dd>
          </template>
        </dl>
      </div>
      <div class="ctx-block">
        <span class="lbl">工具调用统计</span>
        <dl>
          <template v-for="t in toolStats" :key="t.k + t.a">
            <dt class="lbl">{{ t.k }}</dt>
            <dd class="mono">{{ t.r }}</dd>
          </template>
        </dl>
      </div>
    </div>
  </InspectorPanel>
</template>

<style scoped>
.split {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  min-height: 0;
}
.sessions {
  flex: 0 1 270px;
  min-width: 230px;
  display: flex;
  flex-direction: column;
}
.s-head {
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid var(--line);
}
h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}
.grow {
  flex: 1;
}
.s-filters {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.sess {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 48px;
  padding: 0 12px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.sess:hover {
  background: rgba(255, 255, 255, 0.7);
}
.sess[data-selected='true'] {
  background: rgba(255, 255, 255, 0.85);
  box-shadow: inset 3px 0 0 var(--acc);
}
.abbr {
  flex: none;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 800;
  background: var(--faint);
}
.abbr.dark,
.sess[data-selected='true'] .abbr {
  background: var(--ink);
  color: var(--acc);
}
.st {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.tt {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub {
  font-size: 10.5px;
  color: var(--mute);
}
.chat {
  flex: 999 1 480px;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.c-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 10px 8px 14px;
  border-bottom: 1px solid var(--line);
}
.chip {
  font-size: 10.5px;
  padding: 3px 10px;
  background: rgba(20, 22, 26, 0.07);
}
.flow {
  flex: 1;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: auto;
}
.msg {
  display: flex;
  gap: 10px;
}
.who {
  width: 52px;
  flex: none;
  padding-top: 3px;
}
.who.strong {
  color: var(--ink);
}
.msg p,
.reply p {
  margin: 0;
  flex: 1;
  font-size: 13.5px;
  line-height: 1.7;
}
.reply {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tools {
  display: flex;
  flex-direction: column;
  background: rgba(20, 22, 26, 0.04);
}
.tool {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 32px;
  padding: 0 10px;
}
.tick {
  color: var(--ok-ink);
}
.tk {
  width: 44px;
  font-size: 11px;
}
.ta {
  flex: 1;
  min-width: 0;
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
code {
  font-size: 12px;
  padding: 0 5px;
  background: rgba(20, 22, 26, 0.07);
}
.decided {
  margin: 0;
  font-size: 12px;
  color: var(--mute);
}
.composer {
  margin: 0 12px 12px;
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
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-bottom: 1px solid var(--line);
}
.ctx-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.pct {
  font-size: 16px;
  font-weight: 700;
}
dl {
  margin: 4px 0 0;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 5px 12px;
}
dd {
  margin: 0;
  font-size: 11.5px;
  text-align: right;
}
</style>
