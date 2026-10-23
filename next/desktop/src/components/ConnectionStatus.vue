<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'
import AlertToggle from '@/components/AlertToggle.vue'
import StatusDot from '@/components/StatusDot.vue'

/**
 * 侧栏底部连接状态行（按钮）：只显示后端真实状态。点开为弹出层：后端状态、pid、心跳延迟、
 * 告警演示开关（只发 POST /api/system/alert）。告警时状态行变橙。VPN/TG/MCP 在各自切片前不显示。
 */
const store = useBackendStore()
const runtime = inject(backendRuntimeKey, null)

const LABEL = {
  connecting: '连接中',
  online: '在线',
  reconnecting: '重连中',
  offline: '离线',
} as const
const label = computed(() => LABEL[store.connection])
const dot = computed(() => (store.connection === 'online' && !store.alert.active ? 'ok' : 'warn'))
const pidText = computed(() => (store.pid !== null ? String(store.pid) : '—'))
const latencyText = computed(() => (store.latencyMs !== null ? `${store.latencyMs} ms` : '—'))

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

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)

async function toggle() {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    panel.value?.focus()
  }
}
function close(restoreFocus: boolean) {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}
function onDocPointer(e: Event) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) close(false)
}
// Esc 在文档级监听：焦点不在弹出层内（比如点过外面又回来）时也能关
function onDocKey(e: KeyboardEvent) {
  if (open.value && e.key === 'Escape') {
    e.stopPropagation()
    close(true)
  }
}
onMounted(() => {
  document.addEventListener('pointerdown', onDocPointer)
  document.addEventListener('keydown', onDocKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocPointer)
  document.removeEventListener('keydown', onDocKey)
})
</script>

<template>
  <div ref="root" class="conn" :data-alert="store.alert.active ? 'true' : 'false'">
    <button
      ref="trigger"
      type="button"
      class="row"
      aria-haspopup="dialog"
      :aria-expanded="open"
      data-testid="connection-trigger"
      @click="toggle"
    >
      <StatusDot :state="dot" />
      <span role="status" data-testid="connection" class="txt">
        <span :data-state="store.connection">后端 {{ label }}</span>
      </span>
    </button>
    <div
      v-if="open"
      ref="panel"
      class="pop"
      role="dialog"
      aria-label="连接状态"
      tabindex="-1"
      data-testid="connection-popover"
    >
      <dl class="kv">
        <dt>后端状态</dt>
        <dd data-testid="connection-state">{{ label }}</dd>
        <dt>pid</dt>
        <dd class="mono" data-testid="connection-pid">{{ pidText }}</dd>
        <dt>心跳延迟</dt>
        <dd class="mono" data-testid="connection-latency">{{ latencyText }}</dd>
        <template v-if="version">
          <dt>版本</dt>
          <dd class="mono" data-testid="health-version">{{ version }}</dd>
        </template>
      </dl>
      <AlertToggle />
    </div>
  </div>
</template>

<style scoped>
.conn {
  position: relative;
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: var(--ctl-h);
  padding: 0 8px;
  border: 0;
  border-radius: var(--r-ctl);
  background: transparent;
  color: var(--mute-tint);
  font: inherit;
  font-size: var(--text-sub);
  text-align: left;
  cursor: pointer;
}
.row:hover {
  background: color-mix(in srgb, var(--ink) 5%, transparent);
}
.conn[data-alert='true'] .row {
  color: var(--st-stopping-fg);
  background: var(--st-stopping-bg);
}
.pop {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  z-index: 30;
  width: 260px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-radius: var(--r-group);
  background: var(--bg-window);
  color: var(--ink);
  font-size: var(--text-body);
  box-shadow:
    0 0 0 0.5px var(--line),
    0 8px 24px rgba(0, 0, 0, 0.2);
}
.kv {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px 12px;
  margin: 0;
}
.kv dt {
  color: var(--mute);
}
.kv dd {
  margin: 0;
  text-align: right;
}
</style>
