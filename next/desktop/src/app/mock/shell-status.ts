/** 状态栏里 VPN / TG / MCP / 待处理计数的 mock。后端状态用真实 store，不在这里。 */
export interface ShellStatusItem {
  key: string
  text: string
  state: 'ok' | 'run' | 'warn' | 'idle'
}

export function useShellStatus() {
  const items: ShellStatusItem[] = [
    { key: 'vpn', text: 'VPN 已连接', state: 'ok' },
    { key: 'tg', text: 'TG 在线', state: 'ok' },
    { key: 'mcp', text: 'MCP 2/3', state: 'ok' },
  ]
  return { items, pending: 3 }
}
