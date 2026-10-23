<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertCircle,
  AlertTriangle,
  Check,
  Clock,
  CornerDownLeft,
  Edit3,
  FileText,
  RotateCw,
  Search,
  Square,
  Terminal,
  Trash2,
  Wrench,
  XCircle,
} from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import Sheet from '@/components/Sheet.vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import {
  closeAiSession,
  decideAiApproval,
  deleteAiSession,
  fetchAiSessionEvents,
  interruptAiSession,
  resumeAiSession,
  sendAiMessage,
  toApiError,
  type AIEventData,
  type ApprovalDecision,
  type SessionView,
} from './api'
import { renderMarkdown } from './markdown'
import { formatAiError } from './terminal-protocol'

const props = defineProps<{
  session: SessionView
}>()

const emit = defineEmits<{
  updateSession: [session: SessionView]
  deleted: []
}>()

const runtime = inject(backendRuntimeKey)

const chatRoot = ref<HTMLElement | null>(null)
const flowContainer = ref<HTMLElement | null>(null)
const draft = ref('')
const sending = ref(false)
const actionInProgress = ref(false)
const actionError = ref<string | null>(null)

// 模态弹窗状态
const isCloseSheetOpen = ref(false)
const isDeleteSheetOpen = ref(false)
const isResumeSheetOpen = ref(false)
const resumeAckHighRisk = ref(false)

// 事件流与水位管理（遵循 S3C-F1/F2 及 S5D-T03 教训）
const events = ref<AIEventData[]>([])
const eventMap = new Map<number, AIEventData>()
const maxSeq = ref(0)
let isFetchingEvents = false
let removeEventListener: (() => void) | null = null

// 倒计时状态（审批卡 9 分钟到期）
const APPROVAL_TTL_SECONDS = 540 // 9 minutes
const approvalRemainingSeconds = ref(APPROVAL_TTL_SECONDS)
let countdownTimer: ReturnType<typeof setInterval> | null = null

// 待决审批对象与已决审批集合
interface PendingApproval {
  approvalId: string
  tool: string
  summary: string
  ts: string
}
const pendingApproval = ref<PendingApproval | null>(null)
const resolvedApprovalIds = new Set<string>()
const inFlightApprovalIds = new Set<string>()
const isExpired = computed(() =>
  Boolean(pendingApproval.value && approvalRemainingSeconds.value <= 0),
)

// 按 session_seq 插入并去重，保持升序
function addEvents(incoming: AIEventData[]) {
  let changed = false
  for (const ev of incoming) {
    if (ev.session_id !== props.session.id) continue
    if (typeof ev.session_seq !== 'number' || ev.session_seq < 1) continue
    if (eventMap.has(ev.session_seq)) {
      continue
    }
    eventMap.set(ev.session_seq, ev)
    if (ev.session_seq > maxSeq.value) {
      maxSeq.value = ev.session_seq
    }
    changed = true

    // 监听 approval 事件（在按 session_seq 去重之后执行）
    if (ev.kind === 'approval') {
      const p = ev.payload as {
        approval_id?: string
        tool?: string
        summary?: string
        state?: string
      }
      if (!p.approval_id) continue

      if (p.state === 'pending') {
        if (!resolvedApprovalIds.has(p.approval_id)) {
          pendingApproval.value = {
            approvalId: p.approval_id,
            tool: p.tool || '未知工具',
            summary: p.summary || '',
            ts: ev.ts,
          }
          startCountdown(ev.ts)
        }
      } else if (p.state === 'allowed' || p.state === 'denied' || p.state === 'expired') {
        resolvedApprovalIds.add(p.approval_id)
        if (pendingApproval.value?.approvalId === p.approval_id) {
          pendingApproval.value = null
          stopCountdown()
        }
      }
    }
  }
  if (changed) {
    events.value = Array.from(eventMap.values()).sort((a, b) => a.session_seq - b.session_seq)
    void scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  if (flowContainer.value) {
    flowContainer.value.scrollTop = flowContainer.value.scrollHeight
  }
}

// 单飞拉取远端事件
async function fetchMissingEvents() {
  if (isFetchingEvents) return
  const client = runtime?.api()
  if (!client) return
  isFetchingEvents = true
  try {
    const res = await fetchAiSessionEvents(client, props.session.id, maxSeq.value)
    if (Array.isArray(res.items) && res.items.length > 0) {
      addEvents(res.items as unknown as AIEventData[])
    }
  } catch {
    // 拉取失败静默处理，由 WS 或后续重试补齐
  } finally {
    isFetchingEvents = false
  }
}

// 倒计时管理
function startCountdown(startTimeStr?: string) {
  stopCountdown()
  let elapsed = 0
  if (startTimeStr) {
    const start = Date.parse(startTimeStr)
    if (!Number.isNaN(start)) {
      elapsed = Math.max(0, Math.floor((Date.now() - start) / 1000))
    }
  }
  approvalRemainingSeconds.value = Math.max(0, APPROVAL_TTL_SECONDS - elapsed)
  if (approvalRemainingSeconds.value <= 0) {
    return
  }
  countdownTimer = setInterval(() => {
    if (approvalRemainingSeconds.value > 0) {
      approvalRemainingSeconds.value--
      if (approvalRemainingSeconds.value <= 0) {
        stopCountdown()
      }
    } else {
      stopCountdown()
    }
  }, 1000)
}

function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}

const formattedCountdown = computed(() => {
  const total = approvalRemainingSeconds.value
  const mins = Math.floor(total / 60)
  const secs = total % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
})

// 监听 WS 事件并初次加载
function initStream() {
  events.value = []
  eventMap.clear()
  maxSeq.value = 0
  pendingApproval.value = null
  resolvedApprovalIds.clear()
  inFlightApprovalIds.clear()
  stopCountdown()

  // 1. 先订阅 WS
  runtime?.subscribeAi?.(props.session.id, 0)

  // 2. 注册 WS 监听器
  removeEventListener?.()
  removeEventListener =
    runtime?.onEvent?.((envelope) => {
      if (envelope.topic === 'ai') {
        if (envelope.type === 'ai.event') {
          const evData = envelope.data as unknown as AIEventData
          if (evData.session_id === props.session.id) {
            addEvents([evData])
          }
        } else if (envelope.type === 'ai.session') {
          const sData = envelope.data as {
            session_id: string
            state: SessionView['state']
            ended_reason?: string | null
            last_seq: number
          }
          if (sData.session_id === props.session.id) {
            // 对账 last_seq，更新会话状态
            if (sData.last_seq >= props.session.last_seq) {
              emit('updateSession', {
                ...props.session,
                state: sData.state,
                ended_reason: sData.ended_reason ?? props.session.ended_reason,
                last_seq: sData.last_seq,
              })
            }
            if (sData.state !== 'awaiting_approval') {
              pendingApproval.value = null
              stopCountdown()
            }
          }
        }
      }
    }) ?? null

  // 3. 拉取已有的历史事件
  void fetchMissingEvents()
}

watch(
  () => props.session.id,
  () => {
    initStream()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  stopCountdown()
  removeEventListener?.()
  runtime?.unsubscribeAi?.(props.session.id)
})

// 归一化聚合展示项：将事件流转换为结构化消息回合
interface ToolItem {
  id: string
  tool: string
  summary: string
  resultText?: string
  isError?: boolean
  hasResult: boolean
}

interface TurnBlock {
  turnId: number
  userText?: string
  thinkingText?: string
  assistantText?: string
  tools: ToolItem[]
  status?: 'completed' | 'failed' | 'interrupted'
  category?: string
  notices: string[]
  errors: string[]
}

const turnBlocks = computed(() => {
  const blocks: TurnBlock[] = []
  let current: TurnBlock = {
    turnId: 0,
    tools: [],
    notices: [],
    errors: [],
  }

  // 首回合若有 initial_prompt 则作为第一条用户消息
  for (const ev of events.value) {
    if (ev.kind === 'turn_started') {
      if (current.userText || current.assistantText || current.tools.length > 0) {
        blocks.push(current)
      }
      const p = ev.payload as { text?: string; message?: string }
      current = {
        turnId: ev.session_seq,
        userText: p.text || p.message || '',
        tools: [],
        notices: [],
        errors: [],
      }
    } else if (ev.kind === 'thinking') {
      const p = ev.payload as { text?: string }
      if (p.text) {
        current.thinkingText = (current.thinkingText || '') + p.text
      }
    } else if (ev.kind === 'assistant') {
      const p = ev.payload as { text?: string }
      if (p.text) {
        current.assistantText = (current.assistantText || '') + p.text
      }
    } else if (ev.kind === 'tool_use') {
      const p = ev.payload as { tool?: string; tool_use_id?: string; summary?: string }
      current.tools.push({
        id: p.tool_use_id || `tool-${ev.session_seq}`,
        tool: p.tool || '未知工具',
        summary: p.summary || '',
        hasResult: false,
      })
    } else if (ev.kind === 'tool_result') {
      const p = ev.payload as { tool_use_id?: string; text?: string; is_error?: boolean }
      const tool = current.tools.find((t) => t.id === p.tool_use_id)
      if (tool) {
        tool.hasResult = true
        tool.resultText = p.text || ''
        tool.isError = Boolean(p.is_error)
      } else {
        // 如果未匹配到，补加一条
        current.tools.push({
          id: p.tool_use_id || `tool-${ev.session_seq}`,
          tool: '工具结果',
          summary: '',
          resultText: p.text || '',
          isError: Boolean(p.is_error),
          hasResult: true,
        })
      }
    } else if (ev.kind === 'notice') {
      const p = ev.payload as { reason?: string; count?: number }
      if (p.reason === 'suppressed') {
        current.notices.push(`已合并限流 ${p.count ?? 0} 条高频输出`)
      }
    } else if (ev.kind === 'error') {
      const p = ev.payload as { category?: string; text?: string }
      current.errors.push(`${p.category ? '[' + p.category + '] ' : ''}${p.text || '执行出错'}`)
    } else if (ev.kind === 'turn_completed') {
      current.status = 'completed'
    } else if (ev.kind === 'turn_failed') {
      const p = ev.payload as { status?: 'failed' | 'interrupted'; category?: string }
      current.status = p.status || 'failed'
      current.category = p.category
    }
  }
  if (current.userText || current.assistantText || current.tools.length > 0 || current.status) {
    blocks.push(current)
  }
  return blocks
})

// 工具类别与图标映射
function toolCategory(name: string): { label: string; icon: string } {
  const n = name.toLowerCase()
  if (n.includes('read') || n.includes('file') || n.includes('view')) {
    return { label: '读取', icon: 'file' }
  }
  if (n.includes('search') || n.includes('grep') || n.includes('find') || n.includes('glob')) {
    return { label: '搜索', icon: 'search' }
  }
  if (n.includes('edit') || n.includes('write') || n.includes('replace') || n.includes('patch')) {
    return { label: '编辑', icon: 'edit' }
  }
  if (n.includes('run') || n.includes('bash') || n.includes('exec') || n.includes('command')) {
    return { label: '运行', icon: 'terminal' }
  }
  return { label: name, icon: 'wrench' }
}

// 审批处理：本次允许 / 会话允许 / 拒绝
async function handleApproval(decision: ApprovalDecision['decision']) {
  if (!pendingApproval.value) return
  const apId = pendingApproval.value.approvalId
  if (!apId || inFlightApprovalIds.has(apId) || actionInProgress.value || isExpired.value) return
  const client = runtime?.api()
  if (!client) return

  inFlightApprovalIds.add(apId)
  actionInProgress.value = true
  actionError.value = null
  try {
    await decideAiApproval(client, props.session.id, apId, { decision })
    resolvedApprovalIds.add(apId)
    pendingApproval.value = null
    stopCountdown()
    void fetchMissingEvents()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    const code = (apiErr as { code?: string }).code
    if (code === 'approval_settled' || code === 'approval_expired') {
      resolvedApprovalIds.add(apId)
      pendingApproval.value = null
      stopCountdown()
    }
    actionError.value = formatAiError(code, '审批提交失败')
  } finally {
    actionInProgress.value = false
    inFlightApprovalIds.delete(apId)
  }
}

// 容器内快捷键 Y / A / N（严格保护：焦点在输入框/textarea/contenteditable 时禁止抢占）
function handleKeydown(e: KeyboardEvent) {
  const active = document.activeElement
  const isInput =
    active &&
    (active.tagName === 'INPUT' ||
      active.tagName === 'TEXTAREA' ||
      (active as HTMLElement).isContentEditable)
  if (isInput) return
  if (!chatRoot.value?.contains(active)) return
  if (!pendingApproval.value || props.session.state !== 'awaiting_approval') return
  if (isExpired.value || actionInProgress.value) return
  const apId = pendingApproval.value.approvalId
  if (!apId || inFlightApprovalIds.has(apId) || resolvedApprovalIds.has(apId)) return

  if (e.key === 'y' || e.key === 'Y') {
    e.preventDefault()
    void handleApproval('allow_once')
  } else if (e.key === 'a' || e.key === 'A') {
    e.preventDefault()
    void handleApproval('allow_session')
  } else if (e.key === 'n' || e.key === 'N') {
    e.preventDefault()
    void handleApproval('deny')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})

// 发送消息
async function sendMessage() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  const client = runtime?.api()
  if (!client) return

  sending.value = true
  actionError.value = null
  try {
    const res = await sendAiMessage(client, props.session.id, {
      request_id: crypto.randomUUID(),
      text,
    })
    draft.value = ''
    if (res.status === 'queued') {
      emit('updateSession', {
        ...props.session,
        queue_len: res.position,
      })
    }
    void fetchMissingEvents()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    const code = (apiErr as { code?: string }).code
    if (code === 'session_ended') {
      actionError.value = '会话已结束，无法发送消息'
    } else if (code === 'ai_queue_full') {
      actionError.value = '消息队列已满（最多 10 条），请等待当前回合处理完成'
    } else {
      actionError.value = formatAiError(code, '发送消息失败')
    }
  } finally {
    sending.value = false
  }
}

// 中断本轮
async function handleInterrupt() {
  const client = runtime?.api()
  if (!client) return
  actionInProgress.value = true
  actionError.value = null
  try {
    const updated = await interruptAiSession(client, props.session.id)
    emit('updateSession', updated)
    void fetchMissingEvents()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    actionError.value = formatAiError((apiErr as { code?: string }).code, '中断失败')
  } finally {
    actionInProgress.value = false
  }
}

// 关闭会话
async function handleConfirmClose() {
  const client = runtime?.api()
  if (!client) return
  actionInProgress.value = true
  actionError.value = null
  try {
    const updated = await closeAiSession(client, props.session.id)
    emit('updateSession', updated)
    isCloseSheetOpen.value = false
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    actionError.value = formatAiError((apiErr as { code?: string }).code, '关闭会话失败')
  } finally {
    actionInProgress.value = false
  }
}

// 删除会话
async function handleConfirmDelete() {
  const client = runtime?.api()
  if (!client) return
  actionInProgress.value = true
  actionError.value = null
  try {
    await deleteAiSession(client, props.session.id)
    isDeleteSheetOpen.value = false
    emit('deleted')
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    actionError.value = formatAiError((apiErr as { code?: string }).code, '删除会话失败')
  } finally {
    actionInProgress.value = false
  }
}

// 续聊已有会话
async function handleConfirmResume() {
  const client = runtime?.api()
  if (!client) return
  actionInProgress.value = true
  actionError.value = null
  try {
    const updated = await resumeAiSession(client, props.session.id, {
      request_id: crypto.randomUUID(),
      ack_high_risk: resumeAckHighRisk.value,
    })
    emit('updateSession', updated)
    isResumeSheetOpen.value = false
    void fetchMissingEvents()
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    const code = (apiErr as { code?: string }).code
    if (code === 'session_active') {
      actionError.value = '该会话仍在运行中，无法续聊'
    } else if (code === 'resume_unavailable') {
      actionError.value = '该会话无外部标识，不支持续聊'
    } else {
      actionError.value = formatAiError(code, '续聊失败')
    }
  } finally {
    actionInProgress.value = false
  }
}

const isEnded = computed(() => props.session.state === 'ended' || props.session.state === 'failed')
</script>

<template>
  <div ref="chatRoot" class="chat-view" tabindex="0" data-testid="chat-view">
    <!-- 顶部操作条 -->
    <header class="chat-header">
      <div class="chat-meta">
        <span class="cli-badge" :data-cli="session.cli">{{ session.cli }}</span>
        <strong class="session-title">{{ session.repo?.name }}</strong>
        <span v-if="session.model" class="model-tag">{{ session.model }}</span>
        <span v-if="session.permission" class="perm-tag">{{ session.permission }}</span>
      </div>

      <div class="chat-actions">
        <!-- 续聊按钮：仅当已结束且存在外部 ID 时可用 -->
        <Button
          v-if="isEnded && session.has_external_id"
          variant="default"
          size="sm"
          data-testid="resume-session-btn"
          :disabled="actionInProgress"
          @click="isResumeSheetOpen = true"
        >
          <RotateCw :size="14" class="mr-1" aria-hidden="true" />
          续聊
        </Button>

        <!-- 中断按钮：运行中/待审批可用 -->
        <Button
          v-if="!isEnded"
          variant="default"
          size="sm"
          data-testid="interrupt-session-btn"
          :disabled="actionInProgress || session.state === 'idle'"
          @click="handleInterrupt"
        >
          <Square :size="14" class="mr-1" aria-hidden="true" />
          中断
        </Button>

        <!-- 关闭会话按钮 -->
        <Button
          v-if="!isEnded"
          variant="default"
          size="sm"
          data-testid="close-session-btn"
          :disabled="actionInProgress"
          @click="isCloseSheetOpen = true"
        >
          <XCircle :size="14" class="mr-1" aria-hidden="true" />
          结束
        </Button>

        <!-- 删除会话记录按钮 -->
        <Button
          v-if="isEnded"
          variant="destructive"
          size="sm"
          data-testid="delete-session-btn"
          :disabled="actionInProgress"
          @click="isDeleteSheetOpen = true"
        >
          <Trash2 :size="14" class="mr-1" aria-hidden="true" />
          删除
        </Button>

        <InspectorToggle />
      </div>
    </header>

    <!-- 错误横幅 -->
    <Banner v-if="actionError" kind="error" class="m-3" data-testid="chat-error-banner">
      {{ actionError }}
    </Banner>

    <!-- 会话流展示区 -->
    <div ref="flowContainer" class="chat-flow" data-testid="chat-flow">
      <!-- 空态：尚未产生事件 -->
      <div v-if="turnBlocks.length === 0" class="flow-empty" data-testid="flow-empty">
        <p class="text-sm text-neutral-400">已就绪，请输入消息开始对话</p>
      </div>

      <!-- 回合列表 -->
      <div v-for="b in turnBlocks" :key="b.turnId" class="turn-block" data-testid="turn-block">
        <!-- 用户气泡 -->
        <div v-if="b.userText" class="msg-bubble user-bubble" data-testid="user-message">
          <p class="bubble-text">{{ b.userText }}</p>
        </div>

        <!-- AI 回复区域 -->
        <div class="ai-response-box">
          <div class="ai-author-row">
            <span class="ai-name font-semibold">{{ session.cli }}</span>
          </div>

          <!-- 思考过程折叠卡片 -->
          <details v-if="b.thinkingText" class="thinking-details" data-testid="thinking-details">
            <summary class="thinking-summary">思考过程 (Thinking)</summary>
            <div class="thinking-content">
              <pre class="thinking-pre mono">{{ b.thinkingText }}</pre>
            </div>
          </details>

          <!-- 工具卡片组 -->
          <div v-if="b.tools.length > 0" class="tools-container" data-testid="tools-container">
            <div
              v-for="t in b.tools"
              :key="t.id"
              class="b-tool"
              :class="{ 'tool-error': t.isError }"
              :data-testid="`tool-card-${t.id}`"
            >
              <div class="tool-head">
                <span class="tool-icon" aria-hidden="true">
                  <FileText v-if="toolCategory(t.tool).icon === 'file'" :size="14" />
                  <Search v-else-if="toolCategory(t.tool).icon === 'search'" :size="14" />
                  <Edit3 v-else-if="toolCategory(t.tool).icon === 'edit'" :size="14" />
                  <Terminal v-else-if="toolCategory(t.tool).icon === 'terminal'" :size="14" />
                  <Wrench v-else :size="14" />
                </span>
                <span class="tool-label font-semibold">{{ toolCategory(t.tool).label }}</span>
                <span v-if="t.summary" class="tool-summary mono">{{ t.summary }}</span>
                <span class="tool-status ml-auto text-xs">
                  <span v-if="!t.hasResult" class="text-blue-600">调用中…</span>
                  <span
                    v-else-if="t.isError"
                    class="text-red-600 font-semibold flex items-center gap-1"
                  >
                    <AlertCircle :size="12" /> 失败
                  </span>
                  <span v-else class="text-emerald-600 flex items-center gap-1">
                    <Check :size="12" /> 完成
                  </span>
                </span>
              </div>
              <div v-if="t.resultText" class="tool-result-body mono" :class="{ error: t.isError }">
                {{ t.resultText }}
              </div>
            </div>
          </div>

          <!-- Assistant 正文（Markdown 经 DOMPurify 清洗） -->
          <div
            v-if="b.assistantText"
            class="assistant-markdown prose"
            data-testid="assistant-markdown"
            v-html="renderMarkdown(b.assistantText)"
          ></div>

          <!-- 通知与限流提示 -->
          <div v-for="(n, idx) in b.notices" :key="`notice-${idx}`" class="notice-badge">
            <AlertTriangle :size="12" class="text-amber-500 mr-1" />
            <span>{{ n }}</span>
          </div>

          <!-- 错误提示 -->
          <div v-for="(err, idx) in b.errors" :key="`err-${idx}`" class="error-badge">
            <AlertCircle :size="12" class="text-red-500 mr-1" />
            <span>{{ err }}</span>
          </div>

          <!-- 回合结束状态 -->
          <div v-if="b.status" class="turn-status-row" :data-status="b.status">
            <span v-if="b.status === 'completed'" class="status-chip success">
              <Check :size="12" class="mr-1" /> 回合完成
            </span>
            <span v-else class="status-chip failure">
              <AlertCircle :size="12" class="mr-1" />
              {{ b.status === 'interrupted' ? '已中断' : '回合失败' }}
              {{ b.category ? `(${b.category})` : '' }}
            </span>
          </div>
        </div>
      </div>

      <!-- 待决审批卡片：awaiting_approval 驱动 -->
      <div
        v-if="session.state === 'awaiting_approval' && pendingApproval"
        class="approval-card"
        role="group"
        aria-label="需要审批"
        data-testid="approval-card"
      >
        <div class="approval-header">
          <AlertTriangle :size="16" class="text-amber-600 mr-1.5" />
          <strong class="approval-title text-amber-900">
            {{ session.cli }} 请求执行命令/工具
          </strong>
          <span class="approval-timer ml-auto flex items-center text-xs text-amber-800">
            <Clock :size="12" class="mr-1" />
            <template v-if="isExpired">已过期 {{ formattedCountdown }}</template>
            <template v-else>剩余 {{ formattedCountdown }}</template>
          </span>
        </div>

        <div class="approval-details">
          <div class="approval-tool mono">
            <span class="font-bold mr-1">{{ pendingApproval.tool }}:</span>
            <span>{{ pendingApproval.summary }}</span>
          </div>
        </div>

        <div class="approval-buttons">
          <Button
            variant="primary"
            size="sm"
            data-testid="approval-allow-once"
            :disabled="actionInProgress || isExpired"
            @click="handleApproval('allow_once')"
          >
            允许一次 <kbd class="kbd-hint">Y</kbd>
          </Button>
          <Button
            variant="default"
            size="sm"
            data-testid="approval-allow-session"
            :disabled="actionInProgress || isExpired"
            @click="handleApproval('allow_session')"
          >
            本会话始终允许 <kbd class="kbd-hint">A</kbd>
          </Button>
          <Button
            variant="destructive"
            size="sm"
            data-testid="approval-deny"
            :disabled="actionInProgress || isExpired"
            @click="handleApproval('deny')"
          >
            拒绝 <kbd class="kbd-hint">N</kbd>
          </Button>
        </div>
      </div>

      <!-- 正在工作指示器：仅由 session.state === 'busy' 驱动 -->
      <div
        v-if="session.state === 'busy'"
        class="working-indicator"
        data-testid="working-indicator"
      >
        <span class="busy-dot" aria-hidden="true"></span>
        <span class="text-sm text-neutral-500">{{ session.cli }} 正在工作…</span>
      </div>
    </div>

    <!-- 底部输入框 Composer -->
    <footer class="chat-composer-wrap">
      <div v-if="session.queue_len > 0" class="queue-notice" data-testid="queue-indicator">
        已排队 {{ session.queue_len }} 条消息
      </div>

      <div class="composer-box">
        <textarea
          v-model="draft"
          rows="2"
          class="composer-textarea"
          data-testid="composer-textarea"
          :placeholder="
            isEnded ? '会话已结束' : '输入消息向 AI 提问（按 Enter 发送，Shift+Enter 换行）…'
          "
          :disabled="isEnded || sending"
          @keydown.enter.exact.prevent="sendMessage"
        ></textarea>

        <div class="composer-toolbar">
          <span class="grow"></span>
          <Button
            variant="primary"
            size="sm"
            data-testid="send-message-btn"
            :disabled="isEnded || sending || !draft.trim()"
            @click="sendMessage"
          >
            <CornerDownLeft :size="14" class="mr-1" aria-hidden="true" />
            发送
          </Button>
        </div>
      </div>
    </footer>

    <!-- 关闭确认 Sheet -->
    <Sheet
      :open="isCloseSheetOpen"
      title="结束对话会话"
      description="结束后 AI 会话将停止接收新消息。支持续聊的会话后续可在已结束列表中重新唤醒。"
      @update:open="isCloseSheetOpen = $event"
    >
      <div class="p-2">
        <p class="text-sm text-neutral-600 mb-4">确定要结束当前会话吗？</p>
        <div class="flex justify-end gap-2">
          <Button variant="default" :disabled="actionInProgress" @click="isCloseSheetOpen = false">
            取消
          </Button>
          <Button
            variant="destructive"
            data-testid="confirm-close-btn"
            :disabled="actionInProgress"
            @click="handleConfirmClose"
          >
            {{ actionInProgress ? '正在结束…' : '确认结束' }}
          </Button>
        </div>
      </div>
    </Sheet>

    <!-- 删除确认 Sheet -->
    <Sheet
      :open="isDeleteSheetOpen"
      title="删除会话记录"
      description="删除后将永久清除此会话及其历史事件。"
      @update:open="isDeleteSheetOpen = $event"
    >
      <div class="p-2">
        <p class="text-sm text-neutral-600 mb-4">确定要删除该会话记录吗？</p>
        <div class="flex justify-end gap-2">
          <Button variant="default" :disabled="actionInProgress" @click="isDeleteSheetOpen = false">
            取消
          </Button>
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

    <!-- 续聊确认 Sheet -->
    <Sheet
      :open="isResumeSheetOpen"
      title="续聊会话"
      description="以当前会话的历史上下文与外部 ID 创建一个新的延续会话。"
      @update:open="isResumeSheetOpen = $event"
    >
      <div class="p-2">
        <p class="text-sm text-neutral-600 mb-4">
          将重新启动当前会话进行续聊。若原会话包含高风险档位，请勾选二次确认。
        </p>
        <label class="flex items-center gap-2 mb-4 text-xs cursor-pointer">
          <input v-model="resumeAckHighRisk" type="checkbox" data-testid="resume-ack-checkbox" />
          <span>我确认已知晓高权限风险（如适用）</span>
        </label>
        <div class="flex justify-end gap-2">
          <Button variant="default" :disabled="actionInProgress" @click="isResumeSheetOpen = false">
            取消
          </Button>
          <Button
            variant="primary"
            data-testid="confirm-resume-btn"
            :disabled="actionInProgress"
            @click="handleConfirmResume"
          >
            {{ actionInProgress ? '正在续聊…' : '确认续聊' }}
          </Button>
        </div>
      </div>
    </Sheet>
  </div>
</template>

<style scoped>
.chat-view {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-card, #fff);
  outline: none;
}
.chat-header {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line, #e5e5ea);
  background: var(--bg-sub, #f9f9fb);
}
.chat-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cli-badge {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  background: var(--accent-sub, rgba(10, 99, 214, 0.12));
  color: var(--accent, #0a63d6);
}
.session-title {
  font-size: 13.5px;
}
.model-tag,
.perm-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--ctl, #ececf0);
  color: var(--mute, #6e6e73);
}
.chat-actions {
  display: flex;
  gap: 6px;
}
.chat-flow {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.flow-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
.turn-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.user-bubble {
  align-self: flex-end;
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 14px 14px 4px 14px;
  background: var(--accent, #0a63d6);
  color: #fff;
  font-size: 13.5px;
  line-height: 1.5;
  word-break: break-word;
}
.bubble-text {
  margin: 0;
  white-space: pre-wrap;
}
.ai-response-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 88%;
}
.ai-author-row {
  font-size: 12px;
  color: var(--mute, #6e6e73);
}
.thinking-details {
  border: 1px solid var(--line, #e5e5ea);
  border-radius: 6px;
  background: var(--bg-sub, #f9f9fb);
  font-size: 12px;
}
.thinking-summary {
  padding: 6px 10px;
  cursor: pointer;
  color: var(--mute, #6e6e73);
  font-weight: 500;
}
.thinking-content {
  padding: 8px 10px;
  border-top: 1px solid var(--line, #e5e5ea);
}
.thinking-pre {
  margin: 0;
  white-space: pre-wrap;
  font-size: 11.5px;
  color: var(--mute, #6e6e73);
  max-height: 200px;
  overflow-y: auto;
}
.tools-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.b-tool {
  display: flex;
  flex-direction: column;
  padding: 6px 10px;
  border-radius: 6px;
  background: var(--bg-sub, #f5f5f7);
  border: 1px solid var(--line, #e5e5ea);
  font-size: 12px;
}
.b-tool.tool-error {
  border-color: #fca5a5;
  background: #fef2f2;
}
.tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tool-icon {
  color: var(--mute, #6e6e73);
  display: flex;
  align-items: center;
}
.tool-label {
  color: var(--ink, #1f2937);
}
.tool-summary {
  color: var(--mute, #4b5563);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 400px;
}
.tool-result-body {
  margin-top: 4px;
  padding: 4px 6px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.03);
  font-size: 11px;
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}
.tool-result-body.error {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.06);
}
.assistant-markdown {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink, #1f2937);
  word-break: break-word;
}
.assistant-markdown :deep(p) {
  margin: 6px 0;
}
.assistant-markdown :deep(pre.code-block) {
  padding: 8px 12px;
  border-radius: 6px;
  background: #24292e;
  color: #f6f8fa;
  font-size: 12px;
  overflow-x: auto;
  margin: 8px 0;
}
.assistant-markdown :deep(code.inline-code) {
  padding: 2px 4px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.06);
  font-size: 12px;
}
.notice-badge,
.error-badge {
  display: inline-flex;
  align-items: center;
  font-size: 11.5px;
  padding: 4px 8px;
  border-radius: 4px;
  margin-top: 2px;
}
.notice-badge {
  background: #fef3c7;
  color: #92400e;
}
.error-badge {
  background: #fee2e2;
  color: #b91c1c;
}
.turn-status-row {
  margin-top: 4px;
}
.status-chip {
  display: inline-flex;
  align-items: center;
  font-size: 11.5px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
}
.status-chip.success {
  background: #ecfdf5;
  color: #065f46;
}
.status-chip.failure {
  background: #fef2f2;
  color: #991b1b;
}
.approval-card {
  border-radius: 8px;
  border: 1px solid #fcd34d;
  background: #fffbeb;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 88%;
}
.approval-header {
  display: flex;
  align-items: center;
}
.approval-details {
  padding: 8px 10px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #fef3c7;
  font-size: 12.5px;
}
.approval-buttons {
  display: flex;
  gap: 8px;
}
.kbd-hint {
  margin-left: 4px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.15);
  font-size: 10px;
}
.working-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
}
.busy-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent, #0a63d6);
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.4;
    transform: scale(0.85);
  }
}
.chat-composer-wrap {
  flex: none;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--line, #e5e5ea);
  background: var(--bg-card, #fff);
}
.queue-notice {
  font-size: 11px;
  color: var(--mute, #6e6e73);
  margin-bottom: 4px;
  padding-left: 2px;
}
.composer-box {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line, #d2d2d7);
  border-radius: 8px;
  background: #fff;
  padding: 6px 8px;
}
.composer-box:focus-within {
  outline: 2px solid var(--focus, #0a63d6);
}
.composer-textarea {
  border: none;
  outline: none;
  resize: none;
  font: inherit;
  font-size: 13.5px;
  width: 100%;
  background: transparent;
}
.composer-toolbar {
  display: flex;
  align-items: center;
  margin-top: 4px;
}
</style>
