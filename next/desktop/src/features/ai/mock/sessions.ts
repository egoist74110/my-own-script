/**
 * AI 会话页 mock 数据（虚构）。页面只通过 useAiSessions() 取数；
 * 审批的 Y/A/N 只改本地 mock 状态，不连后端。
 */
import { ref } from 'vue'

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
  const tools: ToolCall[] = [
    { k: 'READ', a: 'src/auth/usePermissions.ts', r: '84 行' },
    { k: 'GREP', a: "queryKey: ['perm'", r: '3 处' },
    { k: 'EDIT', a: 'src/auth/usePermissions.ts', r: '+2 −1' },
  ]
  const pendingCommand = 'pnpm vitest run src/auth --reporter=dot'
  const context = {
    pct: 41,
    segments: 24,
    rows: [
      { k: 'Tokens', v: '82k / 200k' },
      { k: 'Tools', v: '12 次' },
      { k: 'Elapsed', v: '6m 02s' },
      { k: 'Model', v: 'opus · high' },
    ],
  }
  /** 审批记录与会话状态：只在前端 mock 里变化。 */
  const approvals = ref<ApprovalRecord[]>([])
  const pending = ref<string | null>(pendingCommand)
  function decide(decision: ApprovalRecord['decision']) {
    if (pending.value === null) return
    approvals.value.push({ command: pending.value, decision })
    pending.value = null
    const s = sessions.value.find((x) => x.id === 's1')
    if (s) {
      s.state = decision === 'deny' ? 'done' : 'run'
      s.note = decision === 'deny' ? '已拒绝' : '运行中'
    }
  }
  return { sessions, filters, tools, context, approvals, pending, decide }
}
