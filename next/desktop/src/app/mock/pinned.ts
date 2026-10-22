/** 侧栏「Pinned」区的 mock（置顶 / 保存查询）。后续切片换成真实数据。 */
export interface PinnedItem {
  id: string
  label: string
}

export function usePinned(): PinnedItem[] {
  return [
    { id: 'p1', label: 'web-portal 发布' },
    { id: 'p2', label: 'admin-console 仅发布' },
    { id: 'p3', label: '指派给我 · 7' },
  ]
}
