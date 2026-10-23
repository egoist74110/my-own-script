<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { AlertTriangle, Plus, Square, Terminal, Trash2, XCircle } from 'lucide-vue-next'
import ApprovalBar from '@/components/ApprovalBar.vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Inspector from '@/components/Inspector.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import SearchField from '@/components/SearchField.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import Sheet from '@/components/Sheet.vue'
import StatusPill from '@/components/StatusPill.vue'
import TextField from '@/components/TextField.vue'
import ToolbarButton from '@/components/ToolbarButton.vue'
import type { PillState } from '@/components/pill'
import { tabTriggerId } from '@/components/tabs'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { closeAiSession, deleteAiSession, interruptAiSession, type SessionView } from './api'
import { useAiSessions, type SessionState as MockSessionState } from './mock/sessions'
import NewSessionSheet from './NewSessionSheet.vue'
import { formatAiError, formatEndedReason, formatSessionState } from './terminal-protocol'
import TerminalView from './TerminalView.vue'
import { useAiSessionsData } from './useAiSessionsData'

const router = useRouter()
const runtime = inject(backendRuntimeKey)

const {
  sessionsQuery,
  aiOverviewQuery,
  sessionStateOverrides,
  profiles,
  localRepos,
  online,
  invalidateSessions,
} = useAiSessionsData(runtime)

// R1 mock 数据保留（供 chat 会话与审批卡）
const {
  sessions: mockSessions,
  filters,
  messages,
  approvals,
  pending,
  context,
  tools,
  send,
  decide,
} = useAiSessions()

const filter = ref('all')
const selectedId = ref('s1')
const query = ref('')
const draft = ref('')

const isNewSheetOpen = ref(false)
const isCloseSheetOpen = ref(false)
const isDeleteSheetOpen = ref(false)
const actionInProgress = ref(false)
const actionError = ref<string | null>(null)

export interface DisplaySession {
  id: string
  kind: string
  abbr: string
  title: string
  repo: string
  state: string
  stateText: string
  pillState: PillState | null
  isTerminal: boolean
  isMock: boolean
  endedReason?: string | null
  exitCode?: number | null
  warnings?: string[]
  createdAt?: string
  rawReal?: SessionView
}

function abbrForCli(cli?: string | null): string {
  if (!cli) return 'AI'
  const c = cli.toLowerCase()
  if (c === 'claude' || c === 'claude_code') return 'CL'
  if (c === 'codex') return 'CX'
  if (c === 'agy' || c === 'gemini') return 'AG'
  return c.slice(0, 2).toUpperCase()
}

function mapPill(state: string): PillState | null {
  switch (state) {
    case 'starting':
    case 'busy':
      return 'running'
    case 'idle':
      return null
    case 'awaiting_approval':
      return 'verify'
    case 'ended':
      return 'success'
    case 'failed':
      return 'failed'
    default:
      return null
  }
}

// 合并真实会话与 mock 会话
const hasRealData = computed(() => {
  return sessionsQuery.isSuccess.value && Array.isArray(sessionsQuery.data.value?.items)
})

const sessionsErrorCode = computed(() => {
  const err = sessionsQuery.error.value
  return (err as { code?: string })?.code ?? null
})

const allSessions = computed<DisplaySession[]>(() => {
  // S5D-T01: GET 失败时不得显示 mock 会话冒充真实数据
  if (sessionsQuery.isError.value) {
    return []
  }

  if (hasRealData.value) {
    const items = sessionsQuery.data.value?.items ?? []
    return items.map((s) => {
      const override = sessionStateOverrides.value[s.id]
      const sSeq = typeof s.last_seq === 'number' ? s.last_seq : -1
      const oSeq = override && typeof override.last_seq === 'number' ? override.last_seq : -1

      // S5D-T03: 对账 last_seq。只有当 WS 事件水位严格高于 GET 快照时才使用覆盖层；否则使用较新的 GET 快照
      const useOverride = Boolean(override && oSeq > sSeq)
      const effectiveState = useOverride
        ? (override?.state ?? s.state)
        : (s.state ?? override?.state)
      const effectiveReason = useOverride
        ? (override?.ended_reason ?? s.ended_reason)
        : (s.ended_reason ?? override?.ended_reason)
      const effectiveExitCode = useOverride
        ? (override?.exit_code ?? s.exit_code)
        : (s.exit_code ?? override?.exit_code)
      return {
        id: s.id,
        kind: s.cli,
        abbr: abbrForCli(s.cli),
        title: `${s.repo?.name || '未知仓库'} (终端)`,
        repo: s.repo?.name || '',
        state: effectiveState,
        stateText: formatSessionState(effectiveState),
        pillState: mapPill(effectiveState),
        isTerminal: s.kind === 'terminal',
        isMock: false,
        endedReason: effectiveReason,
        exitCode: effectiveExitCode,
        warnings: s.warnings,
        createdAt: s.created_at,
        rawReal: s,
      }
    })
  }

  // 降级使用 mock 会话（仅供未接真接口/未返回 items 的旧测试与演示）
  if (!online.value || sessionsQuery.data.value?.items === undefined) {
    const MOCK_PILL: Record<MockSessionState, PillState | null> = {
      approve: 'verify',
      run: 'running',
      done: 'success',
      old: null,
    }
    return mockSessions.value.map((s) => ({
      id: s.id,
      kind: s.kind,
      abbr: s.abbr,
      title: s.title,
      repo: s.repo,
      state: s.state,
      stateText: s.note,
      pillState: MOCK_PILL[s.state],
      isTerminal: false,
      isMock: true,
    }))
  }

  return []
})

// 根据筛选器与搜索词过滤
const list = computed(() =>
  allSessions.value.filter((s) => {
    if (filter.value !== 'all' && s.kind !== filter.value) return false
    const q = query.value.trim().toLowerCase()
    return !q || `${s.title} ${s.repo}`.toLowerCase().includes(q)
  }),
)

// 仅在真实会话加载且当前选中的 ID 为初始占位值时，选中第一个真实会话
watch(
  allSessions,
  (sessions) => {
    if (sessions.length > 0 && selectedId.value === 's1' && !sessions.some((s) => s.id === 's1')) {
      selectedId.value = sessions[0]!.id
    }
  },
  { immediate: true },
)

const selected = computed(() => allSessions.value.find((s) => s.id === selectedId.value))

// 操作：中断、关闭、删除
async function handleInterrupt() {
  if (!selected.value || !selected.value.isTerminal) return
  const client = runtime?.api()
  if (!client) return
  actionInProgress.value = true
  actionError.value = null
  try {
    const updated = await interruptAiSession(client, selected.value.id)
    sessionStateOverrides.value[updated.id] = {
      ...sessionStateOverrides.value[updated.id],
      state: updated.state,
    }
    invalidateSessions()
  } catch (err: unknown) {
    actionError.value = err instanceof Error ? err.message : String(err)
  } finally {
    actionInProgress.value = false
  }
}

async function handleConfirmClose() {
  if (!selected.value || !selected.value.isTerminal) return
  const client = runtime?.api()
  if (!client) return
  actionInProgress.value = true
  actionError.value = null
  try {
    const updated = await closeAiSession(client, selected.value.id)
    sessionStateOverrides.value[updated.id] = {
      ...sessionStateOverrides.value[updated.id],
      state: updated.state,
      ended_reason: updated.ended_reason,
    }
    isCloseSheetOpen.value = false
    invalidateSessions()
  } catch (err: unknown) {
    actionError.value = err instanceof Error ? err.message : String(err)
  } finally {
    actionInProgress.value = false
  }
}

async function handleConfirmDelete() {
  if (!selected.value || !selected.value.isTerminal) return
  const client = runtime?.api()
  if (!client) return
  actionInProgress.value = true
  actionError.value = null
  try {
    await deleteAiSession(client, selected.value.id)
    isDeleteSheetOpen.value = false
    delete sessionStateOverrides.value[selected.value.id]
    invalidateSessions()
    const remaining = allSessions.value.filter((s) => s.id !== selected.value?.id)
    if (remaining.length > 0) {
      selectedId.value = remaining[0]!.id
    }
  } catch (err: unknown) {
    actionError.value = err instanceof Error ? err.message : String(err)
  } finally {
    actionInProgress.value = false
  }
}

function handleSessionCreated(newSession: SessionView) {
  invalidateSessions()
  selectedId.value = newSession.id
}

function handleJumpToRepos() {
  isNewSheetOpen.value = false
  void router.push('/settings')
}

// Mock Chat 逻辑保留
const msgs = computed(() => messages(selectedId.value))
const decided = computed(() => approvals(selectedId.value))
const pendingCmd = computed(() => pending(selectedId.value))
const ctxInfo = computed(() => context(selectedId.value))
const toolStats = computed(() => tools(selectedId.value))
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
    <!-- 左栏：会话列表 -->
    <section aria-label="会话列表" class="sessions">
      <header class="topbar" data-tauri-drag-region>
        <h1>AI 会话</h1>
        <span class="grow"></span>
        <ToolbarButton label="新会话" data-testid="new-session-btn" @click="isNewSheetOpen = true">
          <Plus :size="16" aria-hidden="true" />
        </ToolbarButton>
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
        <!-- 错误态（含重试） -->
        <div v-if="sessionsQuery.isError.value" class="p-4" data-testid="sessions-error-state">
          <Banner kind="error" class="mb-3">
            {{ formatAiError(sessionsErrorCode, '获取 AI 会话列表失败') }}
          </Banner>
          <Button
            variant="default"
            size="sm"
            data-testid="retry-sessions-btn"
            @click="sessionsQuery.refetch()"
          >
            重试
          </Button>
        </div>

        <!-- 空态按设计稿 -->
        <div v-else-if="list.length === 0" class="empty-state" data-testid="sessions-empty-state">
          <Terminal :size="36" class="text-neutral-400 mb-2" aria-hidden="true" />
          <h2 class="empty-title">没有会话</h2>
          <p class="empty-desc">
            在本地仓库里启动 Claude、Codex 或 Antigravity；也可以从工单的“AI 分析”直接开一个。
          </p>
          <Button
            variant="primary"
            class="mt-3"
            data-testid="empty-new-session-btn"
            @click="isNewSheetOpen = true"
          >
            新会话…
          </Button>
        </div>

        <ul v-else class="b-list">
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
                <span v-if="s.warnings?.length" class="warning-badge" title="存在告警">
                  <AlertTriangle :size="12" class="text-amber-500" aria-hidden="true" />
                </span>
              </span>
              <span class="b-row-l2">
                <span class="mono">{{ s.repo }}</span>
                <span aria-hidden="true">·</span>
                <StatusPill v-if="s.pillState" :state="s.pillState" :title="s.stateText" />
                <span v-else>{{ s.stateText }}</span>
                <span
                  v-if="s.isTerminal && s.exitCode !== null && s.exitCode !== undefined"
                  class="exit-code"
                >
                  ({{ s.exitCode }})
                </span>
                <span class="sr-only">{{ s.stateText }}</span>
              </span>
            </button>
          </li>
        </ul>
      </div>
    </section>

    <!-- 中栏：终端视图 或 对话流 -->
    <section v-if="selected" aria-label="对话" class="chat">
      <!-- 顶部操作栏 -->
      <header class="topbar" data-tauri-drag-region>
        <span class="badge" :data-kind="selected.kind" aria-hidden="true">{{ selected.abbr }}</span>
        <strong class="ct">{{ selected.title }}</strong>
        <span class="mono sub">{{ selected.repo }}</span>
        <span class="grow"></span>

        <!-- 终端会话专有操作 -->
        <template v-if="selected.isTerminal">
          <StatusPill
            v-if="selected.pillState"
            :state="selected.pillState"
            :title="selected.stateText"
          />
          <ToolbarButton
            label="中断 (Ctrl-C)"
            data-testid="interrupt-btn"
            :disabled="
              actionInProgress || selected.state === 'ended' || selected.state === 'failed'
            "
            @click="handleInterrupt"
          >
            <Square :size="14" aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            label="关闭终端"
            data-testid="close-btn"
            :disabled="
              actionInProgress || selected.state === 'ended' || selected.state === 'failed'
            "
            @click="isCloseSheetOpen = true"
          >
            <XCircle :size="15" aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            v-if="selected.state === 'ended' || selected.state === 'failed'"
            label="删除会话"
            data-testid="delete-btn"
            :disabled="actionInProgress"
            @click="isDeleteSheetOpen = true"
          >
            <Trash2 :size="15" class="text-red-500" aria-hidden="true" />
          </ToolbarButton>
        </template>

        <!-- Chat 专属操作与标注 -->
        <template v-else>
          <span class="chip warn-chip" title="结构化会话将在 S5-B 接入">待 S5-B</span>
          <span class="chip">逐条审批</span>
          <ToolbarButton label="中断"><Square :size="14" aria-hidden="true" /></ToolbarButton>
          <ToolbarButton label="在终端打开"
            ><Terminal :size="16" aria-hidden="true"
          /></ToolbarButton>
        </template>

        <InspectorToggle />
      </header>

      <!-- 错误横幅 -->
      <Banner v-if="actionError" kind="error" class="m-2">
        {{ actionError }}
      </Banner>

      <!-- 终端视图 -->
      <TerminalView
        v-if="selected.isTerminal"
        :session-id="selected.id"
        :session-state="selected.state"
        :exit-code="selected.exitCode"
        :ended-reason="selected.endedReason"
      />

      <!-- Mock 对话流（待 S5-B） -->
      <template v-else>
        <div class="mock-notice-bar">
          <span>提示：当前为 Chat 会话预览（待 S5-B 接口接入，目前使用本地 Mock 数据）。</span>
        </div>
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
                <template v-for="(part, j) in m.body" :key="j">
                  <code v-if="typeof part !== 'string'" class="mono">{{ part.code }}</code>
                  <template v-else>{{ part }}</template>
                </template>
              </p>
            </div>
            <div v-else class="bubble you-b">
              <p>
                <template v-for="(part, j) in m.body" :key="j">
                  {{ typeof part === 'string' ? part : part.code }}
                </template>
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
      </template>
    </section>

    <!-- 右栏：检查器 -->
    <Inspector v-if="selected" label="会话检查器">
      <!-- 终端会话专有右栏信息：工具、仓库、开始时间、状态；隐藏 chat 专属指标 -->
      <div v-if="selected.isTerminal" class="ctx" data-testid="ai-terminal-inspector">
        <div class="ctx-block">
          <span class="lbl">终端会话信息</span>
          <dl>
            <dt>工具</dt>
            <dd class="mono">{{ selected.kind }}</dd>
            <dt>仓库</dt>
            <dd class="mono">{{ selected.repo }}</dd>
            <dt>状态</dt>
            <dd class="mono">{{ selected.stateText }}</dd>
            <dt v-if="selected.createdAt">开始时间</dt>
            <dd v-if="selected.createdAt" class="mono">
              {{ new Date(selected.createdAt).toLocaleTimeString() }}
            </dd>
            <dt v-if="selected.endedReason">结束原因</dt>
            <dd v-if="selected.endedReason" class="mono">
              {{ formatEndedReason(selected.endedReason) }}
            </dd>
            <dt v-if="selected.exitCode !== null && selected.exitCode !== undefined">退出码</dt>
            <dd v-if="selected.exitCode !== null && selected.exitCode !== undefined" class="mono">
              {{ selected.exitCode }}
            </dd>
            <dt v-if="selected.warnings?.length">告警信息</dt>
            <dd v-if="selected.warnings?.length" class="mono text-amber-600">
              {{ selected.warnings.join(', ') }}
            </dd>
          </dl>
        </div>
      </div>

      <!-- Mock Chat 检查器 -->
      <div v-else-if="ctxInfo" class="ctx" data-testid="ai-inspector">
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

    <!-- 新建会话 Sheet -->
    <NewSessionSheet
      v-model:open="isNewSheetOpen"
      :profiles="profiles"
      :local-repos="localRepos"
      :default-profile-id="aiOverviewQuery.data.value?.selected_profile_id"
      @created="handleSessionCreated"
      @jump-to-repos="handleJumpToRepos"
    />

    <!-- 关闭确认 Sheet -->
    <Sheet
      :open="isCloseSheetOpen"
      title="关闭终端会话"
      description="关闭终端将终止后台监督器与所有相关子进程组。已产生的终端输出在重新打开后不可继续输入。"
      @update:open="isCloseSheetOpen = $event"
    >
      <div class="p-2">
        <p class="text-sm text-neutral-600 dark:text-neutral-300">
          确定要关闭当前会话 <strong>{{ selected?.title }}</strong> 吗？
        </p>
        <div class="flex justify-end gap-2 mt-4">
          <Button variant="default" :disabled="actionInProgress" @click="isCloseSheetOpen = false"
            >取消</Button
          >
          <Button
            variant="destructive"
            data-testid="confirm-close-btn"
            :disabled="actionInProgress"
            @click="handleConfirmClose"
          >
            {{ actionInProgress ? '正在关闭…' : '确认关闭终端' }}
          </Button>
        </div>
      </div>
    </Sheet>

    <!-- 删除确认 Sheet -->
    <Sheet
      :open="isDeleteSheetOpen"
      title="删除终端会话记录"
      description="删除后将永久清除此会话记录与事件存储。"
      @update:open="isDeleteSheetOpen = $event"
    >
      <div class="p-2">
        <p class="text-sm text-neutral-600 dark:text-neutral-300">
          确定要删除会话 <strong>{{ selected?.title }}</strong> 的记录吗？
        </p>
        <div class="flex justify-end gap-2 mt-4">
          <Button variant="default" :disabled="actionInProgress" @click="isDeleteSheetOpen = false"
            >取消</Button
          >
          <Button
            variant="destructive"
            data-testid="confirm-delete-btn"
            :disabled="actionInProgress"
            @click="handleConfirmDelete"
          >
            {{ actionInProgress ? '正在删除…' : '确认删除' }}
          </Button>
        </div>
      </div>
    </Sheet>
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
  gap: 8px;
  height: var(--topbar-h);
  padding: 0 12px 0 16px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--line);
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
  overflow-y: auto;
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 24px;
  text-align: center;
}
.empty-title {
  margin: 4px 0 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.empty-desc {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.5;
}
.b-list {
  list-style: none;
  margin: 0;
  padding: 0 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.sess {
  width: 100%;
}
.badge {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10.5px;
  font-weight: 700;
  color: #fff;
  background: #6e6e73;
}
.badge[data-kind='claude'],
.badge[data-kind='claude_code'] {
  background: #c15f3c;
}
.badge[data-kind='codex'] {
  background: #007acc;
}
.badge[data-kind='agy'],
.badge[data-kind='gemini'] {
  background: #2563eb;
}
.warning-badge {
  display: inline-flex;
  align-items: center;
  margin-left: 4px;
}
.exit-code {
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.chat {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-window);
}
.ct {
  font-size: 13.5px;
  font-weight: 600;
}
.sub {
  font-size: 12px;
  color: var(--text-muted);
}
.chip {
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 11.5px;
  background: var(--bg-panel);
  color: var(--text-muted);
  border: 1px solid var(--line);
}
.warn-chip {
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.3);
}
.mock-notice-bar {
  padding: 6px 16px;
  background: rgba(245, 158, 11, 0.08);
  border-bottom: 1px solid rgba(245, 158, 11, 0.2);
  font-size: 12px;
  color: #b45309;
}
.flow {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.msg {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.msg[data-role='user'] {
  align-items: flex-end;
}
.who {
  font-size: 11.5px;
  color: var(--text-muted);
}
.bubble {
  max-width: 80%;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.5;
}
.you-b {
  background: var(--accent);
  color: #fff;
  border-bottom-right-radius: 2px;
}
.ai-b {
  background: var(--bg-panel);
  color: var(--text);
  border-bottom-left-radius: 2px;
}
.tools {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 6px;
  padding: 6px;
  background: var(--bg-window);
  border-radius: 6px;
  font-size: 12px;
}
.tool {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tick {
  color: #16a34a;
}
.tk {
  font-weight: 600;
}
.ta {
  color: var(--text-muted);
}
.decided {
  font-size: 12px;
  color: var(--text-muted);
  padding: 4px 8px;
  background: var(--bg-panel);
  border-radius: 4px;
}
.composer {
  flex: none;
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}
.ctx {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  font-size: 12.5px;
}
.ctx-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ctx-head {
  display: flex;
  justify-content: space-between;
}
.lbl {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-muted);
}
.pct {
  font-size: 12px;
  font-weight: 700;
}
.meter {
  height: 6px;
  border-radius: 3px;
  background: var(--bg-panel);
  overflow: hidden;
}
.meter span {
  display: block;
  height: 100%;
  background: var(--accent);
}
dl {
  margin: 0;
  display: grid;
  grid-template-columns: 70px 1fr;
  gap: 6px 8px;
}
dt {
  color: var(--text-muted);
}
dd {
  margin: 0;
  word-break: break-all;
}
.allowed {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.none {
  color: var(--text-muted);
  font-size: 12px;
  margin: 0;
}
</style>
