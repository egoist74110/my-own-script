/**
 * AI 会话页 mock 数据（虚构）。页面只通过 useAiSessions() 取数；
 * 审批的 Y/A/N 只改本地 mock 状态，不连后端。
 */
import { reactive, ref } from 'vue'

export type AiKind = 'claude' | 'codex' | 'agy'
export type SessionState = 'approve' | 'run' | 'done' | 'old'

export interface Session {
  id: string
  kind: AiKind
  abbr: string
  title: string
  repo: string
  note: string
  state: SessionState
}

export interface ToolCall {
  k: string
  a: string
  r: string
}

/** 消息正文：纯文本或行内代码片段。 */
export type MessagePart = string | { code: string }

export interface ChatMessage {
  role: 'user' | 'ai'
  who: string
  body: MessagePart[]
  tools?: ToolCall[]
}

export interface ContextInfo {
  pct: number
  segments: number
  rows: { k: string; v: string }[]
}

export interface ApprovalRecord {
  command: string
  decision: 'once' | 'always' | 'deny'
}

const S = (
  id: string,
  kind: AiKind,
  title: string,
  repo: string,
  note: string,
  state: SessionState,
): Session => ({
  id,
  kind,
  abbr: { claude: 'CL', codex: 'CX', agy: 'AG' }[kind],
  title,
  repo,
  note,
  state,
})

/** 每个会话独立的对话、已发送消息、审批记录与待审批命令。 */
interface Conversation {
  messages: ChatMessage[]
  approvals: ApprovalRecord[]
  pending: string | null
  context: ContextInfo
}

const ctx = (pct: number, tokens: string, tools: string, elapsed: string, model: string) => ({
  pct,
  segments: 24,
  rows: [
    { k: 'Tokens', v: tokens },
    { k: 'Tools', v: tools },
    { k: 'Elapsed', v: elapsed },
    { k: 'Model', v: model },
  ],
})

function seedConversations(): Record<string, Conversation> {
  const ai = (who: string, body: MessagePart[], tools?: ToolCall[]): ChatMessage => ({
    role: 'ai',
    who,
    body,
    tools,
  })
  const you = (text: string): ChatMessage => ({ role: 'user', who: 'You', body: [text] })
  return {
    s1: {
      messages: [
        you('分析工单 #48213：切项目后菜单丢失。先定位权限缓存在哪里失效，再给最小修复。'),
        ai(
          'Claude',
          [
            '问题在 ',
            { code: 'usePermissions' },
            '：缓存键只含用户 ID，切换项目不会让它失效。修复是把 projectId 加进 queryKey，并在切换项目时让旧键失效。',
          ],
          [
            { k: 'READ', a: 'src/auth/usePermissions.ts', r: '84 行' },
            { k: 'GREP', a: "queryKey: ['perm'", r: '3 处' },
            { k: 'EDIT', a: 'src/auth/usePermissions.ts', r: '+2 −1' },
          ],
        ),
      ],
      approvals: [],
      pending: 'pnpm vitest run src/auth --reporter=dot',
      context: ctx(41, '82k / 200k', '12 次', '6m 02s', 'opus · high'),
    },
    s2: {
      messages: [
        you('梳理网关各层的超时配置，列出不一致的地方。'),
        ai(
          'Codex',
          ['正在读取 ', { code: 'gateway.yaml' }, ' 与各服务的客户端超时设置。'],
          [{ k: 'READ', a: 'config/gateway.yaml', r: '212 行' }],
        ),
      ],
      approvals: [],
      pending: null,
      context: ctx(23, '46k / 200k', '5 次', '2m 40s', 'gpt · medium'),
    },
    s3: {
      messages: [
        you('报表导出的列宽在中文表头下被截断。'),
        ai('agy', ['已按表头字符宽度计算列宽并加上限，导出结果不再截断。']),
      ],
      approvals: [],
      pending: null,
      context: ctx(12, '24k / 200k', '3 次', '1m 15s', 'agy · default'),
    },
    s4: {
      messages: [you('弱网下按钮连点会重复提交，排查原因。'), ai('Claude', ['已归档的历史会话。'])],
      approvals: [],
      pending: null,
      context: ctx(58, '116k / 200k', '21 次', '14m 33s', 'opus · high'),
    },
    s5: {
      messages: [you('评估依赖升级的影响面。'), ai('Codex', ['已归档的历史会话。'])],
      approvals: [],
      pending: null,
      context: ctx(35, '70k / 200k', '9 次', '5m 10s', 'gpt · medium'),
    },
    s6: {
      messages: [you('CSV 导出中文文件名乱码。'), ai('Claude', ['已归档的历史会话。'])],
      approvals: [],
      pending: null,
      context: ctx(19, '38k / 200k', '6 次', '3m 21s', 'opus · high'),
    },
  }
}

export function useAiSessions() {
  const sessions = ref<Session[]>([
    S('s1', 'claude', '#48213 权限缓存未刷新', 'web-portal', '待审批', 'approve'),
    S('s2', 'codex', '网关超时配置梳理', 'api-gateway', '运行中', 'run'),
    S('s3', 'agy', '报表导出列宽', 'admin-console', '完成', 'done'),
    S('s4', 'claude', '弱网重复提交排查', 'mobile-bff', '昨天', 'old'),
    S('s5', 'codex', '依赖升级影响面', 'api-gateway', '周一', 'old'),
    S('s6', 'claude', 'CSV 中文文件名乱码', 'admin-console', '上周', 'old'),
  ])
  const filters = [
    { value: 'all', label: '全部' },
    { value: 'claude', label: 'Claude' },
    { value: 'codex', label: 'Codex' },
    { value: 'agy', label: 'agy' },
  ]
  /** 按会话 id 隔离的状态；只在前端 mock 里变化。 */
  const convs = reactive<Record<string, Conversation>>(seedConversations())
  const conv = (id: string): Conversation | undefined => convs[id]

  const messages = (id: string) => conv(id)?.messages ?? []
  const approvals = (id: string) => conv(id)?.approvals ?? []
  const pending = (id: string) => conv(id)?.pending ?? null
  const context = (id: string) => conv(id)?.context ?? null
  const tools = (id: string): ToolCall[] => messages(id).flatMap((m) => m.tools ?? [])

  function send(id: string, text: string) {
    const c = conv(id)
    const t = text.trim()
    if (!c || !t) return
    c.messages.push({ role: 'user', who: 'You', body: [t] })
  }
  function decide(id: string, decision: ApprovalRecord['decision']) {
    const c = conv(id)
    if (!c || c.pending === null) return
    c.approvals.push({ command: c.pending, decision })
    c.pending = null
    const s = sessions.value.find((x) => x.id === id)
    if (s) {
      s.state = decision === 'deny' ? 'done' : 'run'
      s.note = decision === 'deny' ? '已拒绝' : '运行中'
    }
  }
  return { sessions, filters, messages, approvals, pending, context, tools, send, decide }
}
