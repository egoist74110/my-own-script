/**
 * 工单页 mock 数据（虚构，人名以占位符代替）。页面只通过 useWorkItems() 取数，
 * 后续切片换成 ADO MCP / 后端接口时只改本文件与取数函数。
 */
import { ref } from 'vue'

export type WorkItemType = 'Bug' | '需求' | '任务'

export interface WorkItem {
  id: number
  type: WorkItemType
  title: string
  who: string
  age: string
  column: string
  priority: string
  state: string
  props: { k: string; v: string }[]
  body: string[]
  comments: { who: string; when: string; text: string }[]
  children: string[]
  attachments: { name: string; size: string; blocked?: boolean; host?: string }[]
  prs: string[]
}

export interface AiAgent {
  id: string
  initial: string
  name: string
  trait: string
}

const base = (
  id: number,
  type: WorkItemType,
  title: string,
  age: string,
  column: string,
): WorkItem => ({
  id,
  type,
  title,
  who: '[负责人]',
  age,
  column,
  priority: type === 'Bug' ? 'P1' : 'P2',
  state: column,
  props: [
    { k: '指派', v: '[负责人]' },
    { k: '迭代', v: 'Sprint 42' },
    { k: '区域', v: 'Portal / Auth' },
    { k: '标签', v: 'auth, cache' },
  ],
  body: ['描述占位：这是虚构的工单内容，用于界面演示。'],
  comments: [],
  children: [],
  attachments: [],
  prs: [],
})

export function useWorkItems() {
  const first: WorkItem = {
    ...base(48213, 'Bug', '登录后切换项目时，权限缓存未刷新导致菜单缺失', '2h', '开发中'),
    body: [
      '复现：普通成员登录 → 顶部切到第二个项目 → 左侧菜单只剩“首页”，刷新后恢复。',
      '预期：切换项目后立即按新项目角色重建菜单，不依赖整页刷新。',
      '环境：Chrome 130 / Safari 18，staging 与 prod 均可复现。',
    ],
    comments: [
      { who: '[测试]', when: '昨天 18:20', text: '二号项目的“只读成员”角色也能复现，管理员不会。' },
      { who: '[开发]', when: '昨天 19:05', text: '怀疑权限缓存键没有带项目 ID。' },
    ],
    children: ['#47991 菜单构建单测', '#47992 缓存键重构', '#47993 回归用例'],
    attachments: [
      { name: 'screenshot.png', size: '182 KB' },
      { name: '外部图片', size: '', blocked: true, host: 'cdn.example.invalid' },
    ],
    prs: ['PR !312 fix/48213-menu-cache'],
  }
  const items = ref<WorkItem[]>([
    first,
    base(48190, '需求', '报表导出支持按部门筛选并保留列宽', '5h', '待处理'),
    base(48177, 'Bug', '移动端上传头像在弱网下重复提交', '1d', '开发中'),
    base(48160, '任务', '升级网关依赖并补齐超时配置', '1d', '开发中'),
    base(48132, '需求', '审批流增加“抄送我的”视图', '2d', '待处理'),
    base(48101, 'Bug', '时区切换后日历事件偏移一小时', '3d', '测试中'),
    base(48088, '任务', '清理过期的 feature flag', '4d', '完成'),
    base(48071, 'Bug', '导出 CSV 中文文件名乱码', '5d', '测试中'),
  ])
  const columns = ['待处理', '开发中', '测试中', '完成']
  const agents: AiAgent[] = [
    { id: 'claude', initial: 'CL', name: 'Claude', trait: '常驻会话 · 逐条审批' },
    { id: 'codex', initial: 'CX', name: 'Codex', trait: '每轮 exec · 沙箱三档' },
    { id: 'agy', initial: 'AG', name: 'Antigravity', trait: '纯文本 · 按目录续聊' },
  ]
  const repos = ['~/code/web-portal', '~/code/admin-console']
  function promptFor(w: WorkItem): string {
    return [
      `# 工单 #${w.id}（${w.type} · ${w.priority}）`,
      w.title,
      '## 复现 / 预期 / 环境',
      `## 评论（${w.comments.length}）`,
      '## 任务：定位失效点，给最小修复，修改前先说明方案',
    ].join('\n')
  }
  return { items, columns, agents, repos, promptFor }
}
