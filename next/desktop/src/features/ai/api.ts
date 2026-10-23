// AI 模块 API 辅助：错误归一化、请求解包与类型引用
import type { ApiClient } from '@/api/client'
import type { components } from '@/api/schema'
import { AI_ERROR_MESSAGES } from './terminal-protocol'

export type AIView = components['schemas']['AIView']
export type SessionView = components['schemas']['SessionView']
export type SessionList = components['schemas']['SessionList']
export type SessionCreate = components['schemas']['SessionCreate']
export type ProfileView = components['schemas']['ProfileView']
export type CheckResponse = components['schemas']['CheckResponse']
export type JobResponse = components['schemas']['JobResponse']
export type AISettingsPatch = components['schemas']['AISettingsPatch']
export type ProfileCreate = components['schemas']['ProfileCreate']
export type ProfilePatch = components['schemas']['ProfilePatch']
export type MutationResponse = components['schemas']['MutationResponse']
export type RepoView = components['schemas']['RepoView']
export type AgyDefaults = components['schemas']['AgyDefaults']
export type ClaudeDefaults = components['schemas']['ClaudeDefaults']
export type CodexDefaults = components['schemas']['CodexDefaults']
export type AgyAnalysis = components['schemas']['AgyAnalysis']
export type ClaudeAnalysis = components['schemas']['ClaudeAnalysis']
export type CodexAnalysis = components['schemas']['CodexAnalysis']
export type ModelPresets = components['schemas']['ModelPresets']
export type AgyModels = components['schemas']['AgyModels']
export type ResumeCandidates = components['schemas']['ResumeCandidates']
export type ResumeCandidate = components['schemas']['ResumeCandidate']
export type AIEventsResponse = components['schemas']['AIEventsResponse']
export type AIEventData = components['schemas']['AIEventData']
export type SendMessage = components['schemas']['SendMessage']
export type SendResult = components['schemas']['SendResult']
export type ApprovalDecision = components['schemas']['ApprovalDecision']
export type ApprovalResult = components['schemas']['ApprovalResult']
export type ResumeSession = components['schemas']['ResumeSession']
export type AnalysisRequest = components['schemas']['AnalysisRequest']
export type PromptResponse = components['schemas']['PromptResponse']
export type AIBotsView = components['schemas']['AIBotsView']
export type AIBotView = components['schemas']['AIBotView']
export type AIBotControlView = components['schemas']['AIBotControlView']
export type AIBotEnableRequest = components['schemas']['AIBotEnableRequest']

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function toApiError(status: number, body: unknown): ApiError {
  let defaultCode = 'unknown'
  if (status === 503) defaultCode = 'ai_store_unavailable'
  else if (status === 422) defaultCode = 'validation_error'
  else if (status === 404) defaultCode = 'not_found'
  else if (status === 409) defaultCode = 'conflict'

  const detail =
    typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined

  let code = defaultCode
  let detailObj: Record<string, unknown> = {}

  if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
    detailObj = detail as Record<string, unknown>
    if (typeof detailObj.code === 'string') {
      code = detailObj.code
    }
  } else if (typeof (body as { code?: unknown })?.code === 'string') {
    code = (body as { code: string }).code
  }

  // 严格按 code 映射中文文案，不得原样回显服务端的原始 detail/message 字符串
  const message = AI_ERROR_MESSAGES[code] ?? `请求失败（HTTP ${status}）`
  return new ApiError(status, code, message, detailObj)
}

interface Result {
  data?: unknown
  error?: unknown
  response: Response
}

export async function unwrap<R extends Result>(req: Promise<R>): Promise<NonNullable<R['data']>> {
  let result: R
  try {
    result = await req
  } catch {
    throw new ApiError(0, 'network', '无法连接后端')
  }
  if (result.error !== undefined) throw toApiError(result.response.status, result.error)
  return result.data as NonNullable<R['data']>
}

export async function fetchAiOverview(api: ApiClient): Promise<AIView> {
  return unwrap(api.GET('/api/ai'))
}

export async function fetchAiSessions(
  api: ApiClient,
  state?: 'starting' | 'idle' | 'busy' | 'awaiting_approval' | 'closing' | 'ended' | 'failed',
  limit?: number,
): Promise<SessionList> {
  return unwrap(
    api.GET('/api/ai/sessions', {
      params: { query: { state, limit } },
    }),
  )
}

export async function fetchAiSession(api: ApiClient, sessionId: string): Promise<SessionView> {
  return unwrap(
    api.GET('/api/ai/sessions/{sid}', {
      params: { path: { sid: sessionId } },
    }),
  )
}

export async function createAiSession(api: ApiClient, body: SessionCreate): Promise<SessionView> {
  return unwrap(
    api.POST('/api/ai/sessions', {
      body,
    }),
  )
}

export async function interruptAiSession(api: ApiClient, sessionId: string): Promise<SessionView> {
  return unwrap(
    api.POST('/api/ai/sessions/{sid}/interrupt', {
      params: { path: { sid: sessionId } },
    }),
  )
}

export async function closeAiSession(api: ApiClient, sessionId: string): Promise<SessionView> {
  return unwrap(
    api.POST('/api/ai/sessions/{sid}/close', {
      params: { path: { sid: sessionId } },
    }),
  )
}

export async function deleteAiSession(api: ApiClient, sessionId: string): Promise<void> {
  await unwrap(
    api.DELETE('/api/ai/sessions/{sid}', {
      params: { path: { sid: sessionId } },
    }),
  )
}

export async function checkAiProfile(api: ApiClient, profileId: string): Promise<CheckResponse> {
  return unwrap(
    api.POST('/api/ai/profiles/{pid}/check', {
      params: { path: { pid: profileId } },
    }),
  )
}

export async function upgradeAiProfile(api: ApiClient, profileId: string): Promise<JobResponse> {
  return unwrap(
    api.POST('/api/ai/profiles/{pid}/upgrade', {
      params: { path: { pid: profileId } },
    }),
  )
}

export async function cancelAiJob(api: ApiClient, jobId: string): Promise<JobResponse> {
  return unwrap(
    api.POST('/api/ai/jobs/{jid}/cancel', {
      params: { path: { jid: jobId } },
    }),
  )
}

export async function createAiProfile(
  api: ApiClient,
  body: ProfileCreate,
): Promise<MutationResponse> {
  return unwrap(
    api.POST('/api/ai/profiles', {
      body,
    }),
  )
}

export async function patchAiProfile(
  api: ApiClient,
  profileId: string,
  body: ProfilePatch,
): Promise<MutationResponse> {
  return unwrap(
    api.PATCH('/api/ai/profiles/{pid}', {
      params: { path: { pid: profileId } },
      body,
    }),
  )
}

export async function deleteAiProfile(
  api: ApiClient,
  profileId: string,
  revision: number,
): Promise<MutationResponse> {
  return unwrap(
    api.DELETE('/api/ai/profiles/{pid}', {
      params: {
        path: { pid: profileId },
        query: { revision },
      },
    }),
  )
}

export async function patchAiSettings(
  api: ApiClient,
  body: AISettingsPatch,
): Promise<MutationResponse> {
  return unwrap(
    api.PATCH('/api/ai/settings', {
      body,
    }),
  )
}

export async function fetchAiAgyModels(api: ApiClient): Promise<AgyModels> {
  return unwrap(api.GET('/api/ai/agy-models'))
}

export async function fetchResumeCandidates(
  api: ApiClient,
  repoId: string,
  query?: string,
): Promise<ResumeCandidates> {
  return unwrap(
    api.GET('/api/ai/resume-candidates', {
      params: { query: { repo_id: repoId, cli: 'claude', ...(query ? { query } : {}) } },
    }),
  )
}

export async function fetchAiSessionEvents(
  api: ApiClient,
  sessionId: string,
  afterSeq = 0,
  limit = 200,
): Promise<AIEventsResponse> {
  return unwrap(
    api.GET('/api/ai/sessions/{sid}/events', {
      params: {
        path: { sid: sessionId },
        query: { after_seq: afterSeq, limit },
      },
    }),
  )
}

export async function sendAiMessage(
  api: ApiClient,
  sessionId: string,
  body: SendMessage,
): Promise<SendResult> {
  return unwrap(
    api.POST('/api/ai/sessions/{sid}/messages', {
      params: { path: { sid: sessionId } },
      body,
    }),
  )
}

export async function decideAiApproval(
  api: ApiClient,
  sessionId: string,
  approvalId: string,
  decision: ApprovalDecision,
): Promise<ApprovalResult> {
  return unwrap(
    api.POST('/api/ai/sessions/{sid}/approvals/{aid}', {
      params: {
        path: { sid: sessionId, aid: approvalId },
      },
      body: decision,
    }),
  )
}

export async function resumeAiSession(
  api: ApiClient,
  sessionId: string,
  body: ResumeSession,
): Promise<SessionView> {
  return unwrap(
    api.POST('/api/ai/sessions/{sid}/resume', {
      params: { path: { sid: sessionId } },
      body,
    }),
  )
}

export async function fetchTelegramAiBots(api: ApiClient): Promise<AIBotsView> {
  return unwrap(api.GET('/api/telegram/ai-bots'))
}

export async function putTelegramAiBotToken(
  api: ApiClient,
  aiId: 'claude_code' | 'codex' | 'gemini',
  token: string,
  revision: number,
): Promise<MutationResponse> {
  return unwrap(
    api.PUT('/api/telegram/ai-bots/{ai_id}/token', {
      params: { path: { ai_id: aiId } },
      body: { token, revision },
    }),
  )
}

export async function deleteTelegramAiBotToken(
  api: ApiClient,
  aiId: 'claude_code' | 'codex' | 'gemini',
  revision: number,
): Promise<MutationResponse> {
  return unwrap(
    api.DELETE('/api/telegram/ai-bots/{ai_id}/token', {
      params: {
        path: { ai_id: aiId },
        query: { revision },
      },
    }),
  )
}

export async function importLegacyTelegramAiBotToken(
  api: ApiClient,
  aiId: 'claude_code' | 'codex' | 'gemini',
  revision: number,
): Promise<MutationResponse> {
  return unwrap(
    api.POST('/api/telegram/ai-bots/{ai_id}/token/import-legacy', {
      params: { path: { ai_id: aiId } },
      body: { revision },
    }),
  )
}

export async function enableTelegramAiBot(
  api: ApiClient,
  aiId: 'claude_code' | 'codex' | 'gemini',
  body: AIBotEnableRequest,
): Promise<MutationResponse> {
  return unwrap(
    api.POST('/api/telegram/ai-bots/{ai_id}/control/enable', {
      params: { path: { ai_id: aiId } },
      body,
    }),
  )
}

export async function disableTelegramAiBot(
  api: ApiClient,
  aiId: 'claude_code' | 'codex' | 'gemini',
  revision: number,
): Promise<MutationResponse> {
  return unwrap(
    api.POST('/api/telegram/ai-bots/{ai_id}/control/disable', {
      params: { path: { ai_id: aiId } },
      body: { revision },
    }),
  )
}

export async function retryTelegramAiBot(
  api: ApiClient,
  aiId: 'claude_code' | 'codex' | 'gemini',
  revision: number,
): Promise<MutationResponse> {
  return unwrap(
    api.POST('/api/telegram/ai-bots/{ai_id}/control/retry', {
      params: { path: { ai_id: aiId } },
      body: { revision },
    }),
  )
}

export async function fetchWorkItemAiPrompt(
  api: ApiClient,
  id: number,
  projectId: string,
  cli: 'claude' | 'codex' | 'agy' = 'claude',
): Promise<PromptResponse> {
  return unwrap(
    api.GET('/api/work-items/{id}/ai-prompt', {
      params: {
        path: { id },
        query: { project_id: projectId, cli },
      },
    }),
  )
}

export async function createWorkItemAiAnalysis(
  api: ApiClient,
  id: number,
  body: AnalysisRequest,
): Promise<SessionView> {
  return unwrap(
    api.POST('/api/work-items/{id}/ai-analysis', {
      params: { path: { id } },
      body,
    }),
  )
}
