/** 设置页分区 id；同时是 /settings/:tab 路由的合法取值。`vpn` 不是独立分区：落在“服务”分区并滚到 VPN 卡片。 */
export const SETTINGS_TAB_IDS = [
  'import',
  'ado',
  'repos',
  'credentials',
  'telegram',
  'ai',
  'mcp',
  'services',
  'general',
] as const

export const SETTINGS_VPN_ANCHOR = 'settings-vpn'

/** 路由参数 → 分区；未知返回 null。 */
export function tabFromParam(p: unknown): string | null {
  const v = Array.isArray(p) ? p[0] : p
  if (v === 'vpn') return 'services'
  return typeof v === 'string' && (SETTINGS_TAB_IDS as readonly string[]).includes(v) ? v : null
}
