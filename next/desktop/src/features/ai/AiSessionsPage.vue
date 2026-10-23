<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AlertTriangle, Plus, Square, Terminal, Trash2, XCircle } from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Inspector from '@/components/Inspector.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import SearchField from '@/components/SearchField.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import Sheet from '@/components/Sheet.vue'
import StatusPill from '@/components/StatusPill.vue'
import ToolbarButton from '@/components/ToolbarButton.vue'
import type { PillState } from '@/components/pill'
import { tabTriggerId } from '@/components/tabs'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { closeAiSession, deleteAiSession, interruptAiSession, type SessionView } from './api'
import ChatView from './ChatView.vue'
import NewSessionSheet from './NewSessionSheet.vue'
import { formatAiError, formatEndedReason, formatSessionState } from './terminal-protocol'
import TerminalView from './TerminalView.vue'
import { useAiSessionsData } from './useAiSessionsData'

let route: ReturnType<typeof useRoute> | undefined
try {
  route = useRoute()
} catch {
  route = undefined
}
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

const AI_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'claude', label: 'Claude' },
  { value: 'codex', label: 'Codex' },
  { value: 'agy', label: 'agy' },
]

const filter = ref('all')
const selectedId = ref('')
const query = ref('')

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

function formatAiUsage(usage?: Record<string, unknown> | null): string[] {
  if (!usage) return []
  const parts: string[] = []
  if (typeof usage.turns === 'number') {
    parts.push(`${usage.turns} 回合`)
  }
  if (typeof usage.cost_usd === 'number') {
    parts.push(`$${usage.cost_usd.toFixed(2)}`)
  }
  const hasIn = usage.input_tokens !== undefined
  const hasOut = usage.output_tokens !== undefined
  if (hasIn || hasOut) {
    const inTokens = typeof usage.input_tokens === 'number' ? usage.input_tokens : 0
    const outTokens = typeof usage.output_tokens === 'number' ? usage.output_tokens : 0
    parts.push(`输入 ${inTokens} / 输出 ${outTokens}`)
  }
  if (parts.length === 0) {
    for (const [k, v] of Object.entries(usage)) {
      if (v !== null && v !== undefined) {
        parts.push(`${k}: ${v}`)
      }
    }
  }
  return parts
}

const hasRealData = computed(() => {
  return sessionsQuery.isSuccess.value && Array.isArray(sessionsQuery.data.value?.items)
})

const sessionsErrorCode = computed(() => {
  const err = sessionsQuery.error.value
  return (err as { code?: string })?.code ?? null
})

const allSessions = computed<DisplaySession[]>(() => {
  // 离线或 GET 失败或未返回 items 时返回空列表，绝不显示 mock 虚构数据
  if (!online.value || sessionsQuery.isError.value || !hasRealData.value) {
    return []
  }

  const items = sessionsQuery.data.value?.items ?? []
  return items.map((s) => {
    const override = sessionStateOverrides.value[s.id]
    const sSeq = typeof s.last_seq === 'number' ? s.last_seq : -1
    const oSeq = override && typeof override.last_seq === 'number' ? override.last_seq : -1

    // S5D-T03: 对账 last_seq。只有当 WS 事件水位严格高于 GET 快照时才使用覆盖层；否则使用较新的 GET 快照
    const useOverride = Boolean(override && oSeq > sSeq)
    const effectiveState = useOverride ? (override?.state ?? s.state) : (s.state ?? override?.state)
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
      title:
        s.kind === 'chat'
          ? `${s.repo?.name || '未知仓库'} (对话)`
          : `${s.repo?.name || '未知仓库'} (终端)`,
      repo: s.repo?.name || '',
      state: effectiveState,
      stateText: formatSessionState(effectiveState),
      pillState: mapPill(effectiveState),
      isTerminal: s.kind === 'terminal',
      endedReason: effectiveReason,
      exitCode: effectiveExitCode,
      warnings: s.warnings,
      createdAt: s.created_at,
      rawReal: s,
    }
  })
})

// 根据筛选器与搜索词过滤
const list = computed(() =>
  allSessions.value.filter((s) => {
    if (filter.value !== 'all' && s.kind !== filter.value) return false
    const q = query.value.trim().toLowerCase()
    return !q || `${s.title} ${s.repo}`.toLowerCase().includes(q)
  }),
)

watch(
  () => route?.query?.session,
  (sid) => {
    if (typeof sid === 'string' && sid) {
      selectedId.value = sid
    }
  },
  { immediate: true },
)

watch(
  allSessions,
  (sessions) => {
    if (sessions.length === 0) return
    const querySid = typeof route?.query?.session === 'string' ? route.query.session : ''
    if (!selectedId.value || !sessions.some((s) => s.id === selectedId.value)) {
      if (querySid && sessions.some((s) => s.id === querySid)) {
        selectedId.value = querySid
      } else {
        selectedId.value = sessions[0]!.id
      }
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

function handleSessionUpdated(updated: SessionView) {
  sessionStateOverrides.value[updated.id] = {
    ...sessionStateOverrides.value[updated.id],
    state: updated.state,
    ended_reason: updated.ended_reason,
    last_seq: updated.last_seq,
  }
  invalidateSessions()
}

function handleSessionDeleted() {
  if (selected.value) {
    delete sessionStateOverrides.value[selected.value.id]
  }
  invalidateSessions()
  const remaining = allSessions.value.filter((s) => s.id !== selected.value?.id)
  if (remaining.length > 0) {
    selectedId.value = remaining[0]!.id
  }
}

function handleJumpToRepos() {
  isNewSheetOpen.value = false
  void router.push('/settings')
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
          :items="AI_FILTERS"
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
        <!-- 后端离线态 -->
        <div v-if="!online" class="empty-state" data-testid="sessions-offline-state">
          <AlertTriangle :size="36" class="text-neutral-400 mb-2" aria-hidden="true" />
          <h2 class="empty-title">后端未连接</h2>
          <p class="empty-desc">后端服务未连接，请检查服务是否正在运行。</p>
        </div>

        <!-- 错误态（数据未返回 items 或 GET 出错，含重试） -->
        <div
          v-else-if="
            sessionsQuery.isError.value ||
            (!sessionsQuery.isPending.value && sessionsQuery.data.value?.items === undefined)
          "
          class="p-4"
          data-testid="sessions-error-state"
        >
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
                <StatusPill
                  v-if="s.pillState"
                  :state="s.pillState"
                  :label="s.state === 'awaiting_approval' ? '待审批' : undefined"
                  :title="s.stateText"
                />
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

    <!-- 真实 Chat 会话视图 -->
    <ChatView
      v-if="selected && !selected.isTerminal && selected.rawReal"
      :session="selected.rawReal"
      @update-session="handleSessionUpdated"
      @deleted="handleSessionDeleted"
    />

    <!-- 中栏：终端视图 -->
    <section v-else-if="selected && selected.isTerminal" aria-label="终端" class="chat">
      <!-- 顶部操作栏 -->
      <header class="topbar" data-tauri-drag-region>
        <span class="badge" :data-kind="selected.kind" aria-hidden="true">{{ selected.abbr }}</span>
        <strong class="ct">{{ selected.title }}</strong>
        <span class="mono sub">{{ selected.repo }}</span>
        <span class="grow"></span>

        <!-- 终端会话专有操作 -->
        <StatusPill
          v-if="selected.pillState"
          :state="selected.pillState"
          :title="selected.stateText"
        />
        <ToolbarButton
          label="中断 (Ctrl-C)"
          data-testid="interrupt-btn"
          :disabled="actionInProgress || selected.state === 'ended' || selected.state === 'failed'"
          @click="handleInterrupt"
        >
          <Square :size="14" aria-hidden="true" />
        </ToolbarButton>
        <ToolbarButton
          label="关闭终端"
          data-testid="close-btn"
          :disabled="actionInProgress || selected.state === 'ended' || selected.state === 'failed'"
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
        <InspectorToggle />
      </header>

      <!-- 错误横幅 -->
      <Banner v-if="actionError" kind="error" class="m-2">
        {{ actionError }}
      </Banner>

      <!-- 终端视图 -->
      <TerminalView
        :session-id="selected.id"
        :session-state="selected.state"
        :exit-code="selected.exitCode"
        :ended-reason="selected.endedReason"
      />
    </section>

    <!-- 中栏：未选择或离线/错误态 -->
    <div v-else class="empty-main" data-testid="empty-main-view">
      <header class="topbar" data-tauri-drag-region>
        <strong class="ct">AI 会话</strong>
        <span class="grow"></span>
        <InspectorToggle />
      </header>
      <div v-if="!online" class="empty-state" data-testid="main-offline-state">
        <AlertTriangle :size="48" class="text-neutral-400 mb-3" aria-hidden="true" />
        <h2 class="empty-title">后端未连接</h2>
        <p class="empty-desc">后端服务未连接，请检查服务是否正在运行。</p>
      </div>
      <div
        v-else-if="
          sessionsQuery.isError.value ||
          (!sessionsQuery.isPending.value && sessionsQuery.data.value?.items === undefined)
        "
        class="empty-state"
        data-testid="main-error-state"
      >
        <AlertTriangle :size="48" class="text-neutral-400 mb-3" aria-hidden="true" />
        <h2 class="empty-title">获取会话失败</h2>
        <p class="empty-desc">无法加载 AI 会话列表，请点击左侧重试。</p>
      </div>
      <div v-else class="empty-state" data-testid="main-empty-state">
        <Terminal :size="48" class="text-neutral-400 mb-3" aria-hidden="true" />
        <h2 class="empty-title">未选择会话</h2>
        <p class="empty-desc">在左侧选择一个会话，或新建会话开始使用。</p>
        <Button variant="primary" class="mt-3" @click="isNewSheetOpen = true">新会话…</Button>
      </div>
    </div>

    <!-- 右栏：会话检查器（终端与对话会话详情，切换不残留） -->
    <Inspector label="会话检查器">
      <div v-if="selected && selected.isTerminal" class="ctx" data-testid="ai-terminal-inspector">
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
      <div v-else-if="selected" class="ctx" data-testid="ai-chat-inspector">
        <div class="ctx-block">
          <span class="lbl">对话会话信息</span>
          <dl>
            <dt>工具</dt>
            <dd class="mono">{{ selected.rawReal?.cli || selected.kind }}</dd>
            <dt>仓库</dt>
            <dd class="mono">{{ selected.rawReal?.repo?.name || selected.repo }}</dd>
            <template v-if="(selected.rawReal as any)?.branch">
              <dt>分支</dt>
              <dd class="mono">{{ (selected.rawReal as any).branch }}</dd>
            </template>
            <template v-if="selected.rawReal?.purpose === 'work_item_analysis'">
              <dt>工单</dt>
              <dd class="mono">
                #{{ (selected.rawReal?.work_item_ref as any)?.id ?? '-' }}
                <span
                  v-if="(selected.rawReal?.work_item_ref as any)?.project_id"
                  class="text-xs text-neutral-500"
                >
                  ({{ (selected.rawReal?.work_item_ref as any)?.project_id }})
                </span>
              </dd>
            </template>
            <dt v-if="selected.createdAt">开始时间</dt>
            <dd v-if="selected.createdAt" class="mono">
              {{ new Date(selected.createdAt).toLocaleTimeString() }}
            </dd>
            <dt>来源</dt>
            <dd class="mono">
              {{ selected.rawReal?.origin?.kind === 'telegram' ? 'Telegram' : '桌面应用' }}
            </dd>
            <dt>状态</dt>
            <dd class="mono">{{ selected.stateText }}</dd>
            <template v-if="formatAiUsage(selected.rawReal?.usage).length > 0">
              <dt>用量</dt>
              <dd class="mono">
                <span
                  v-for="part in formatAiUsage(selected.rawReal?.usage)"
                  :key="part"
                  class="mr-2"
                >
                  {{ part }}
                </span>
              </dd>
            </template>
            <dt>本会话已允许</dt>
            <dd class="mono">
              <template v-if="(selected.rawReal as any)?.allowed_commands?.length">
                {{ (selected.rawReal as any).allowed_commands.join(', ') }}
              </template>
              <template v-else-if="(selected.rawReal as any)?.allowed_rules?.length">
                {{ (selected.rawReal as any).allowed_rules.join(', ') }}
              </template>
              <template v-else> 无 </template>
            </dd>
          </dl>
        </div>
      </div>
      <div v-else class="ctx p-4 text-neutral-400 text-xs">未选择会话</div>
    </Inspector>

    <!-- 新建会话 Sheet -->
    <NewSessionSheet
      v-model:open="isNewSheetOpen"
      :profiles="profiles"
      :local-repos="localRepos"
      :default-profile-id="aiOverviewQuery.data.value?.selected_profile_id"
      :model-presets="aiOverviewQuery.data.value?.model_presets"
      :defaults="aiOverviewQuery.data.value?.defaults"
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
.empty-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-window);
}
.empty-main .empty-state {
  flex: 1;
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
.lbl {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-muted);
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
</style>
