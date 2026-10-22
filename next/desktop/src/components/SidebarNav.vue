<script setup lang="ts">
import { computed } from 'vue'
import { useBackendStore } from '@/stores/backend'
import { usePinned } from '@/app/mock/pinned'

interface NavItem {
  code: string
  label: string
  /** 可用路由；未实现的能力为 null，并标注计划切片号。 */
  to: string | null
  slice: string | null
}

const store = useBackendStore()
const pinned = usePinned()

const items: NavItem[] = [
  { code: '01', label: '总览', to: null, slice: 'S3' },
  { code: '02', label: '任务', to: '/tasks', slice: null },
  { code: '03', label: '工单', to: '/work-items', slice: null },
  { code: '04', label: 'AI 会话', to: '/ai', slice: null },
  { code: '05', label: 'MCP', to: null, slice: 'S6' },
  { code: '06', label: '服务', to: null, slice: 'S7' },
  { code: '07', label: 'VPN', to: null, slice: 'S8' },
  { code: '08', label: '设置', to: null, slice: 'S1' },
]
const taskBadge = computed(() => (store.alert.active ? '!' : null))
</script>

<template>
  <nav aria-label="分区" class="nav">
    <template v-for="n in items" :key="n.code">
      <RouterLink v-if="n.to" :to="n.to" class="item skew" :data-code="n.code">
        <span class="code ox">{{ n.code }}</span>
        <span class="name">{{ n.label }}</span>
        <span
          v-if="n.to === '/tasks' && taskBadge"
          class="badge ox"
          data-testid="nav-alert-badge"
          aria-label="有告警"
          >{{ taskBadge }}</span
        >
      </RouterLink>
      <span v-else class="item item-off skew" aria-disabled="true" :data-slice="n.slice">
        <span class="code ox">{{ n.code }}</span>
        <span class="name">{{ n.label }}</span>
        <span class="slice mono">{{ n.slice }}</span>
      </span>
    </template>
  </nav>
  <div class="pinned">
    <span class="lbl">Pinned</span>
    <a v-for="p in pinned" :key="p.id" href="#" class="pin" @click.prevent>{{ p.label }}</a>
  </div>
</template>

<style scoped>
.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: var(--target-min);
  padding: 0 10px;
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  color: #2a2e36;
}
a.item:hover {
  background: var(--soft);
}
a.item.router-link-active {
  background: var(--ink);
  color: #fff;
  font-weight: 700;
}
.code {
  width: 18px;
  font-size: 10.5px;
  font-weight: 700;
  color: var(--mute);
}
a.item.router-link-active .code {
  color: var(--acc);
}
.name {
  flex: 1;
}
.badge {
  font-size: 10.5px;
  font-weight: 700;
  padding: 0 6px;
  background: var(--warn);
  color: var(--ink);
}
.item-off {
  color: var(--mute);
  cursor: not-allowed;
}
.slice {
  font-size: 10px;
  padding: 0 5px;
  box-shadow: inset 0 0 0 1px var(--mute);
}
.pinned {
  margin-top: auto;
  padding: 10px 8px 2px;
  border-top: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pin {
  display: flex;
  align-items: center;
  min-height: var(--target-min);
  padding: 0 8px;
  text-decoration: none;
  color: #2a2e36;
  font-size: 12.5px;
}
.pin:hover {
  background: var(--soft);
}
</style>
