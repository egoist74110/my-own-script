<script setup lang="ts">
import { computed, inject, type Component } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import {
  Cable,
  CheckCircle2,
  FileText,
  MessageSquare,
  Server,
  Settings,
  ShieldCheck,
} from 'lucide-vue-next'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'
import { unwrap } from '@/features/tasks/api'
import ConnectionStatus from './ConnectionStatus.vue'

const runtime = inject(backendRuntimeKey)
const store = useBackendStore()
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
  /** 可用路由；未提供的能力为 null。 */
  to: string | null
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
      { label: '任务', to: '/tasks', icon: CheckCircle2, color: 'var(--accent-ink)' },
      { label: '工单', to: '/work-items', icon: FileText, color: 'var(--accent-ink)' },
      { label: 'AI 会话', to: '/ai', icon: MessageSquare, color: 'var(--accent-ink)' },
    ],
  },
  {
    title: '基础设施',
    items: [
      { label: 'MCP', to: null, icon: Cable, color: 'currentColor' },
      { label: '服务', to: null, icon: Server, color: 'currentColor' },
      { label: 'VPN', to: null, icon: ShieldCheck, color: 'currentColor' },
    ],
  },
]
</script>

<template>
  <div class="sidebar-inner">
    <nav aria-label="分区" class="nav">
      <section v-for="g in groups" :key="g.title" class="group">
        <h2 class="sec">{{ g.title }}</h2>
        <template v-for="n in g.items" :key="n.label">
          <RouterLink v-if="n.to" :to="n.to" class="item">
            <component :is="n.icon" :size="16" :style="{ color: n.color }" aria-hidden="true" />
            <span class="name">{{ n.label }}</span>
            <span
              v-if="n.to === '/tasks' && taskBadge"
              class="task-badge"
              data-testid="task-badge"
              >{{ taskBadge }}</span
            >
          </RouterLink>
          <span v-else class="item item-off" aria-disabled="true" title="尚未提供">
            <component :is="n.icon" :size="16" aria-hidden="true" />
            <span class="name">{{ n.label }}</span>
          </span>
        </template>
      </section>
    </nav>
    <div class="foot">
      <nav aria-label="设置">
        <RouterLink to="/settings" class="item">
          <Settings :size="16" aria-hidden="true" />
          <span class="name">设置</span>
        </RouterLink>
      </nav>
      <ConnectionStatus />
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
  padding: 14px 8px 4px;
  font-size: var(--text-group);
  font-weight: 600;
  color: var(--mute-tint);
}
.item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: var(--ctl-h);
  padding: 0 8px;
  border-radius: var(--r-ctl);
  color: var(--ink);
  text-decoration: none;
  font-size: var(--text-body);
}
.item:hover {
  background: color-mix(in srgb, var(--ink) 5%, transparent);
}
.item.router-link-active {
  background: var(--sidebar-sel);
  font-weight: 600;
}
.name {
  flex: 1;
}
.task-badge {
  margin-left: auto;
  font-size: var(--text-sub);
  font-weight: 500;
  color: var(--accent-ink);
}
.item-off {
  color: var(--disabled);
  cursor: default;
}
.item-off:hover {
  background: transparent;
}
.foot {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-top: 8px;
}
</style>
