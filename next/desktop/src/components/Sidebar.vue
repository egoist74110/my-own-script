<script setup lang="ts">
import { computed, inject, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import {
  Cable,
  FileText,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Server,
  Rocket,
  Settings,
  ShieldCheck,
} from 'lucide-vue-next'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'
import { useUiStore } from '@/stores/ui'
import { unwrap } from '@/features/tasks/api'
import ConnectionStatus from './ConnectionStatus.vue'

const runtime = inject(backendRuntimeKey)
const store = useBackendStore()
const ui = useUiStore()
const route = useRoute()
const online = computed(() => store.connection === 'online')

const tasksQuery = useQuery({
  queryKey: ['tasks'],
  enabled: online,
  queryFn: async ({ signal }) => {
    const api = runtime?.api()
    if (!api) return null
    return unwrap(api.GET('/api/tasks', { signal }))
  },
})

const activeRunsCount = computed(() => {
  const items = tasksQuery.data.value?.items
  if (!items || !Array.isArray(items)) return 0
  return items.filter((t) => Boolean(t.active_run_id)).length
})

const taskBadge = computed(() => {
  if (activeRunsCount.value > 0) {
    return `${activeRunsCount.value} 运行中`
  }
  return null
})

interface NavItem {
  label: string
  to: string
  icon: Component
  color: string
}
interface NavGroup {
  title: string
  items: NavItem[]
}

const groups: NavGroup[] = [
  {
    title: '工作',
    items: [
      { label: '任务', to: '/tasks', icon: Rocket, color: 'currentColor' },
      { label: '工单', to: '/work-items', icon: FileText, color: 'currentColor' },
      { label: 'AI 会话', to: '/ai', icon: MessageSquare, color: 'currentColor' },
    ],
  },
  {
    title: '基础设施',
    items: [
      { label: 'MCP', to: '/settings/mcp', icon: Cable, color: 'currentColor' },
      { label: '服务', to: '/settings/services', icon: Server, color: 'currentColor' },
      { label: 'VPN', to: '/settings/vpn', icon: ShieldCheck, color: 'currentColor' },
    ],
  },
]

const SETTINGS_ITEM = { label: '设置', to: '/settings' }
/** 高亮跟随当前路径：取所有入口里“最长的前缀匹配”，这样 /settings/mcp 只亮 MCP，不连带亮“设置”。 */
const activeTo = computed(() => {
  const path = route.path
  const all = [...groups.flatMap((g) => g.items), SETTINGS_ITEM]
  let best: string | null = null
  for (const n of all) {
    if ((path === n.to || path.startsWith(n.to + '/')) && (!best || n.to.length > best.length))
      best = n.to
  }
  return best
})

const expanded = computed(() => ui.sidebarMode !== 'compact')
const toggleLabel = computed(() => (expanded.value ? '收起导航' : '展开导航'))
</script>

<template>
  <div class="sidebar-inner" :data-mode="ui.sidebarMode" data-testid="sidebar">
    <nav aria-label="分区" class="nav">
      <section v-for="g in groups" :key="g.title" class="group">
        <h2 class="sec">{{ g.title }}</h2>
        <template v-for="n in g.items" :key="n.label">
          <RouterLink v-slot="{ href, navigate }" :to="n.to" custom>
            <a
              :href="href"
              class="item"
              :class="{ active: activeTo === n.to }"
              :title="n.label"
              :aria-current="activeTo === n.to ? 'page' : undefined"
              @click="navigate"
            >
              <component :is="n.icon" :size="17" :style="{ color: n.color }" aria-hidden="true" />
              <span class="name">{{ n.label }}</span>
              <span
                v-if="n.to === '/tasks' && taskBadge"
                class="task-badge"
                data-testid="task-badge"
                >{{ taskBadge }}</span
              >
              <span
                v-if="n.to === '/tasks' && taskBadge"
                class="task-badge-dot"
                aria-hidden="true"
              ></span>
            </a>
          </RouterLink>
        </template>
      </section>
    </nav>
    <div class="foot">
      <nav aria-label="设置">
        <RouterLink v-slot="{ href, navigate }" to="/settings" custom>
          <a
            :href="href"
            class="item"
            :class="{ active: activeTo === '/settings' }"
            title="设置"
            :aria-current="activeTo === '/settings' ? 'page' : undefined"
            @click="navigate"
          >
            <Settings :size="17" aria-hidden="true" />
            <span class="name">设置</span>
          </a>
        </RouterLink>
      </nav>
      <ConnectionStatus />
      <button
        type="button"
        class="item toggle"
        data-testid="sidebar-toggle"
        :aria-label="toggleLabel"
        :aria-expanded="expanded"
        :title="toggleLabel"
        @click="ui.toggleSidebar()"
      >
        <component :is="expanded ? PanelLeftClose : PanelLeftOpen" :size="17" aria-hidden="true" />
        <span class="name">{{ toggleLabel }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.sidebar-inner {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.nav {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
.group {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.sec {
  margin: 0;
  padding: 14px 10px 4px;
  font-size: var(--text-group);
  font-weight: 600;
  color: var(--mute-tint);
}
.item {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  min-height: 32px;
  padding: 0 10px;
  border-radius: var(--r-ctl);
  color: var(--mute);
  text-decoration: none;
  font-size: var(--text-body);
}
button.item {
  border: 0;
  background: transparent;
  font: inherit;
  font-size: var(--text-body);
  cursor: pointer;
  text-align: left;
}
.item:hover {
  background: color-mix(in srgb, var(--ink) 5%, transparent);
}
.item.active {
  background: var(--sidebar-sel);
  color: var(--ink);
  font-weight: 600;
}
.name {
  flex: 1;
}
.task-badge {
  margin-left: auto;
  font-size: var(--text-group);
  font-weight: 600;
  white-space: nowrap;
  color: var(--st-running-fg);
}
/* 窄侧栏没有地方放文字角标，改成图标右上角的小圆点 */
.task-badge-dot {
  display: none;
  position: absolute;
  top: 6px;
  right: 8px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--st-running-dot);
}
.foot {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-top: 8px;
}
/* 收起态：侧栏 76px（容纳红黄绿按钮），只显示图标；名称靠 title 悬停提示。由 ui store 的 sidebarMode 决定，不再直接依赖媒体查询 */
[data-mode='compact'] .sec,
[data-mode='compact'] .name,
[data-mode='compact'] .task-badge {
  display: none;
}
[data-mode='compact'] .item {
  justify-content: center;
  padding: 0;
}
[data-mode='compact'] .task-badge-dot {
  display: block;
}
</style>
