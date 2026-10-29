// 设置页的 API 辅助：错误归一化与类型别名。错误只携带后端给出的固定 code/message，
// 绝不带请求体（PAT 只出现在请求体里，不会进入 ApiError）。
import type { components } from '@/api/schema'

type S = components['schemas']
export type SettingsResponse = S['SettingsResponse']
export type ImportPreview = S['ImportPreview']
export type ImportState = S['ImportState']
export type AdoResponse = S['AdoResponse']
export type LibraryView = S['LibraryView']
export type Project = S['Project']
export type LocalRepoView = S['LocalRepoView']
export type CredentialStatus = S['CredentialStatus']
export type ConnectionResult = S['ConnectionResult']
export type TelegramView = S['TelegramView']
export type BotView = S['BotView']
export type TokenVerification = S['TokenVerification']
export type VerifiedBot = S['VerifiedBot']
export type TokenMutationResponse = S['TokenMutationResponse']
export type Control = S['Control']
export type OwnerView = S['OwnerView']
export type Notify = S['Notify']
export type PollerView = S['PollerView']
export type ACLView = S['ACLView']
export type ACLGroup = S['ACLGroup']
export type ACLMember = S['ACLMember']
export type ActivityResponse = S['ActivityResponse']
export type ActivityItem = S['ActivityItem']
export type BindCodeResponse = S['BindCodeResponse']
export type GroupCreate = S['GroupCreate']
export type GroupPatch = S['GroupPatch']
export type MemberCreate = S['MemberCreate']
export type MemberPatch = S['MemberPatch']
export interface TelegramStatusData {
  state: PollerView['state']
  since: string
  last_error_category?: string | null
}
export type TaskView = S['TaskView']

export type AIView = S['AIView']
export type ProfileView = S['ProfileView']
export type ProfileCreate = S['ProfileCreate']
export type ProfilePatch = S['ProfilePatch']
export type AISettingsPatch = S['AISettingsPatch']
export type CheckResponse = S['CheckResponse']
export type JobResponse = S['JobResponse']
export type ResolvedCLI = S['ResolvedCLI']
export type AgyAnalysis = S['AgyAnalysis']
export type AgyDefaults = S['AgyDefaults']
export type ClaudeAnalysis = S['ClaudeAnalysis']
export type ClaudeDefaults = S['ClaudeDefaults']
export type CodexAnalysis = S['CodexAnalysis']
export type CodexDefaults = S['CodexDefaults']
export type ModelPresets = S['ModelPresets']

export type MCPSnapshot = S['MCPSnapshot']
export type AdoMcp = S['AdoMcp']
export type FigmaMcp = S['FigmaMcp']
export type FigmaMcpView = S['FigmaMcpView']
export type LarkMcp = S['LarkMcp']
export type LarkMcpView = S['LarkMcpView']
export type LarkPatchStatus = S['LarkPatchStatus']
export type LarkTokenStatus = S['LarkTokenStatus']
export type LarkOwnershipRequest = S['LarkOwnershipRequest']
export type LarkActionRequest = S['LarkActionRequest']
export type RuntimeView = S['RuntimeView']
export type Runtime = S['Runtime']
export type NodeRuntime = S['NodeRuntime']
export type McpJobView = S['McpJobView']
export type MCPSettingsPatch = S['MCPSettingsPatch']
export type ClientConfig = S['ClientConfig']
export type SelfTestRequest = S['SelfTestRequest']
export type SelfTestResult = S['SelfTestResult']
export type CredentialPut = S['CredentialPut']
export type CredentialImport = S['CredentialImport']

export type ServicesSnapshot = S['ServicesSnapshot']
export type ServiceView = S['ServiceView']
export type CloudflaredView = S['CloudflaredView']
export type BinariesView = S['BinariesView']
export type BinaryInfo = S['BinaryInfo']
export type NetworkInfo = S['NetworkInfo']
export type ServicesConfig = S['ServicesConfig']
export type CloudflaredSettings = S['CloudflaredSettings']
export type CodeServerSettings = S['CodeServerSettings']
export type ServiceBinaries = S['ServiceBinaries']
export type SettingsResult = S['SettingsResult']
export type LogsResult = S['LogsResult']
export type TunnelCreate = S['TunnelCreate']
export type ActionRequest = S['ActionRequest']
export type ProtocolRequest = S['ProtocolRequest']
export type LegacyImport = S['LegacyImport']
export type SettingsPatch = S['SettingsPatch']

export type VpnSnapshot = S['VpnSnapshot']
export type VpnConfig = S['VpnConfig']
export type VpnClient = S['VpnClient']
export type VpnLogin = S['VpnLogin']
export type VpnClientView = S['VpnClientView']
export type VpnRunView = S['VpnRunView']
export type VpnRunList = S['VpnRunList']
export type VpnRunRequest = S['VpnRunRequest']
export type VpnSettingsPatch = S['VpnSettingsPatch']
export type BrowserProfileCleared = S['BrowserProfileCleared']
export type CredentialWrite = S['CredentialWrite']
export type CredentialConfigured = S['CredentialConfigured']
export type LegacyCredentialsImport = S['LegacyCredentialsImport']
export type TotpImport = S['TotpImport']
export type ManualMfa = S['ManualMfa']
export type ManualMfaResult = S['ManualMfaResult']

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
  /** `in_use` 时后端列出的引用任务名。 */
  get tasks(): string[] {
    const t = this.detail.tasks
    return Array.isArray(t) ? t.filter((x): x is string => typeof x === 'string') : []
  }
}

function toApiError(status: number, body: unknown): ApiError {
  const detail =
    typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined
  if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>
    const code = typeof d.code === 'string' ? d.code : 'unknown'
    const message =
      typeof d.message === 'string' && d.message
        ? d.message
        : (SERVICES_ERROR_MESSAGES[code] ??
          MCP_ERROR_MESSAGES[code] ??
          TELEGRAM_ERROR_MESSAGES[code] ??
          `请求失败（HTTP ${status}）`)
    return new ApiError(status, code, message, d)
  }
  return new ApiError(status, 'unknown', `请求失败（HTTP ${status}）`)
}

interface Result {
  data?: unknown
  error?: unknown
  response: Response
}

/** 解开 openapi-fetch 结果：非 2xx 抛 ApiError；网络异常抛 `network`（不保留原始异常文本）。 */
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

/** PAT 最小长度（前端先挡，与后端约定一致）。返回错误文案或 null。 */
export const PAT_MIN_LENGTH = 8
export const patError = (value: string): string | null =>
  value.length < PAT_MIN_LENGTH ? `PAT 至少 ${PAT_MIN_LENGTH} 个字符` : null

export function originOf(url: string): string | null {
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

export const CATEGORY_TEXT: Record<ConnectionResult['category'], string> = {
  ok: '连接成功',
  unauthorized: '认证失败（PAT 无效或已过期）',
  forbidden: '权限不足',
  not_found: '地址或 collection 不存在',
  redirect: '被重定向（未跟随，PAT 未转发）',
  tls: 'TLS 证书错误',
  timeout: '连接超时',
  network: '网络不可达',
  bad_response: '响应格式异常',
  no_credential: '尚未保存 PAT',
}

export const SERVICES_ERROR_MESSAGES: Record<string, string> = {
  service_busy: '操作正在进行中或服务运行中，请稍后重试（运行中修改设置请先停止服务）',
  service_port_in_use: '端口已被占用，请检查是否有其他进程正在使用该端口',
  service_binary_missing: '未找到服务二进制执行文件，请检查安装路径',
  service_unsafe_config:
    'code-server 配置为无认证且监听非回环地址，已拒绝启动；请在其 config.yaml 中启用密码认证',
  tunnel_target_forbidden:
    '隧道目标地址不合法，仅允许显式端口的回环地址（localhost / 127.0.0.1 / [::1]）',
  tunnel_limit: '自定义隧道已达到数量上限',
  revision_conflict: '配置已被修改，请刷新后重试',
  validation_error: '输入格式不正确',
  not_found: '未找到指定条目',
  store_unavailable: '配置存储不可用',
  store_busy: '配置存储正忙',
}

export const MCP_ERROR_MESSAGES: Record<string, string> = {
  mcp_busy: '操作正在进行中或服务运行中，请稍后重试（运行中修改端口或 App ID 请先停止服务）',
  mcp_port_in_use: '端口已被占用，请检查旧应用或其他进程是否正在使用该端口',
  mcp_runtime_missing: '缺少运行组件，请先安装 Node / npm 运行组件',
  lark_owner_unconfirmed: '请先确认 Lark MCP 所有权（旧应用已停止）',
  lark_not_configured: '未配置 Lark App ID 或 App Secret',
  mcp_self_test_failed: 'MCP 自检失败',
  revision_conflict: '配置已被修改，请刷新后重试',
  not_found: '未找到指定条目',
  no_credential: '未配置凭据',
  store_unavailable: '配置存储不可用',
  store_busy: '配置存储正忙',
  validation_error: '输入格式不正确',
}

export const TELEGRAM_ERROR_MESSAGES: Record<string, string> = {
  validation_error: '输入格式不正确',
  telegram_active: 'Telegram 正在运行中，无法修改配置，请先停用',
  ack_required: '需要确认旧应用已停止轮询',
  webhook_set: '检测到 Telegram 已设置 Webhook',
  legacy_missing: '旧应用中未找到 Telegram Bot Token',
  owner_not_bound: '尚未绑定所有者',
  telegram_request_failed: 'Telegram 请求失败，请稍后重试',
  telegram_unreachable: '无法连接 Telegram，请检查网络或代理后重试',
  token_invalid: 'Token 无效或已被撤销，请重新录入',
  telegram_store_unavailable: 'Telegram 存储不可用（只读错误态）',
  revision_conflict: '配置已被修改，请刷新后重试',
  no_credential: '未配置 Bot Token',
  credential_backend_error: '凭据存储异常',
  store_unavailable: '配置存储不可用',
  store_busy: '配置存储正忙',
  busy: '系统正忙',
  not_found: '条目不存在',
}

export const POLLER_STATE_LABEL: Record<PollerView['state'], string> = {
  disabled: '已停用',
  starting: '启动中',
  polling: '轮询中',
  backoff: '等待退避',
  conflict: '轮询冲突',
  token_invalid: 'Token 无效',
  webhook_set: 'Webhook 已设置',
  store_unavailable: '存储不可用',
  stopping: '停止中',
}

export const POLLER_STATE_DESC: Partial<Record<PollerView['state'], string>> = {
  conflict:
    '另一个程序（可能是旧应用）正在轮询这个 Bot。请先在旧应用里停用对应的 Telegram 开关，再点“重试接管”',
  token_invalid: 'Token 无效，请核对并重新录入',
  webhook_set: '已在 Telegram 设置 Webhook，接管前需删除 Webhook',
  store_unavailable: 'Telegram 存储处于只读错误态，无法启动轮询',
}

/** 校验失败时的下一步提示（按 verify.code）。 */
export function verifyFailHint(code: TokenVerification['code']): string {
  if (code === 'token_invalid') return '请重新录入正确的 Token。'
  return '可能是网络问题，稍后点“重新检查”。'
}

export const TELEGRAM_TOKEN_REGEX = /^\d{5,16}:[A-Za-z0-9_-]{30,64}$/

export function isTelegramTokenValid(token: string): boolean {
  return TELEGRAM_TOKEN_REGEX.test(token.trim())
}

export const VPN_ERROR_MESSAGES: Record<string, string> = {
  vpn_busy: 'VPN 正在运行中或操作正在进行中，请稍后重试',
  vpn_client_missing: '未检测到 Check Point SASE 客户端，请先安装客户端',
  vpn_not_configured: 'VPN 凭据未配置，请先设置密码与 TOTP 种子',
  vpn_mfa_required: '需要输入 MFA 动态令牌',
  vpn_mfa_timeout: 'MFA 动态令牌输入超时',
  totp_ambiguous: '找到多个 TOTP 项目，请选择要导入的一项',
  totp_unsupported: '不支持的 TOTP 格式（仅支持 RFC 6238 6位/30秒/SHA1）',
  window_permission_missing:
    '缺少窗口自动化权限（屏幕录制或辅助功能），权限归属启动后端的宿主应用，请在 macOS 系统设置中授权后重启后端',
  client_stuck: '客户端退出超时或无响应',
  max_run_exceeded: 'VPN 连接超时，已达到单次运行最大时限',
  login_selector_missing: '登录页面元素未找到或页面结构发生变更',
  login_credentials_rejected: '用户名或密码被拒绝，请检查 VPN 凭据',
  login_mfa_rejected: 'MFA 令牌校验失败，请重试',
  login_timeout: '登录流程等待超时',
  login_callback_not_captured: '未捕获到登录成功回调深链',
  vpn_not_implemented: '该功能在当前后端版本中尚未实现（等待 S8-B 登录 worker 与窗口自动化集成）',
  vpn_profile_unsafe: 'Chrome 配置目录为符号链接或存在安全风险，已拒绝操作',
  revision_conflict: '配置已被修改，请刷新后重试',
  validation_error: '输入格式不正确',
  not_found: '指定的运行记录或条目不存在',
  store_unavailable: '配置存储不可用',
  store_busy: '配置存储正忙',
}

export const VPN_RUNG_LABELS: Record<number, string> = {
  0: '检查已连接',
  1: '档 A：启动客户端',
  2: '档 B：重启客户端',
  3: '档 C：浏览器 SSO 登录',
}

export const VPN_EVENT_LABELS: Record<string, string> = {
  rung0_connected: '已检测到 VPN 隧道连接，直接使用现有连接',
  rungA_open: '正在尝试打开客户端应用',
  rungB_restart: '正在重启客户端应用',
  window_connect: '正在客户端窗口中尝试点击 Connect',
  window_update: '检测到客户端更新提示，正在处理更新',
  rungC_login: '正在启动浏览器执行 SSO 登录',
  waiting_connection: '正在等待 VPN 隧道建立连接',
  done: 'VPN 连接已成功建立',
}

export function vpnErrorMessage(code?: string | null, fallback = 'VPN 操作失败'): string {
  if (!code) return fallback
  return VPN_ERROR_MESSAGES[code] || `${fallback}（错误码：${code}）`
}
