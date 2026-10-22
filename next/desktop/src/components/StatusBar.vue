<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, inject } from 'vue'
import { PanelRight } from 'lucide-vue-next'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'
import { useUiStore } from '@/stores/ui'
import { useShellStatus } from '@/app/mock/shell-status'
import AlertToggle from '@/components/AlertToggle.vue'
import IconButton from '@/components/IconButton.vue'
import StatusDot from '@/components/StatusDot.vue'

const store = useBackendStore()
const ui = useUiStore()
const runtime = inject(backendRuntimeKey, null)
const mock = useShellStatus()

const LABEL = {
  connecting: '连接中',
  online: '在线',
  reconnecting: '重连中',
  offline: '离线',
} as const
const label = computed(() => LABEL[store.connection])
const dot = computed(() => (store.connection === 'online' ? 'ok' : 'warn'))
const detail = computed(() => {
  if (store.connection !== 'online') return null
  const parts: string[] = []
  if (store.pid !== null) parts.push(`PID ${store.pid}`)
  if (store.latencyMs !== null) parts.push(`${store.latencyMs} MS`)
  return parts.join(' · ') || null
})

const health = useQuery({
  queryKey: ['health', computed(() => store.pid)],
  enabled: computed(() => store.connection === 'online'),
  retry: false,
  queryFn: async () => {
    const api = runtime?.api()
    if (!api) throw new Error('backend not connected')
    const { data, error } = await api.GET('/health')
    if (error !== undefined || !data) throw new Error('health failed')
    return data
  },
})
const version = computed(() => health.data.value?.version ?? store.version ?? null)
</script>

<template>
  <footer class="status mono" aria-label="状态栏">
    <span class="cell" role="status" data-testid="connection">
      <StatusDot :state="dot" />
      <span :data-state="store.connection">后端 {{ label }}</span>
      <span v-if="detail" data-testid="connection-detail">{{ detail }}</span>
      <span v-if="version" data-testid="health-version">{{ version }}</span>
    </span>
    <span v-for="m in mock.items" :key="m.key" class="cell" :data-testid="`status-${m.key}`">
      <StatusDot :state="m.state" />{{ m.text }}
    </span>
    <span class="cell" data-testid="status-pending">待处理 {{ mock.pending }}</span>
    <span class="grow"></span>
    <AlertToggle />
    <IconButton
      :label="ui.inspectorOpen ? '收起检查器' : '展开检查器'"
      :expanded="ui.inspectorOpen"
      data-testid="inspector-toggle"
      @click="ui.toggleInspector()"
    >
      <PanelRight :size="14" aria-hidden="true" />
    </IconButton>
  </footer>
</template>

<style scoped>
.status {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 16px;
  min-height: 36px;
  padding: 0 8px 0 12px;
  font-size: 11px;
  color: var(--mute);
  background: rgba(255, 255, 255, 0.7);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.8);
}
.cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.grow {
  flex: 1;
}
</style>
