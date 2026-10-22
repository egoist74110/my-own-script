<script setup lang="ts">
import { computed } from 'vue'
import { useBackendStore } from '@/stores/backend'

const store = useBackendStore()

const LABEL = {
  connecting: 'CONNECTING',
  online: 'ONLINE',
  reconnecting: 'RECONNECTING',
  offline: 'OFFLINE',
} as const

const label = computed(() => LABEL[store.connection])
const detail = computed(() => {
  if (store.connection !== 'online') return null
  const parts: string[] = []
  if (store.pid !== null) parts.push(`PID ${store.pid}`)
  if (store.latencyMs !== null) parts.push(`${store.latencyMs} MS`)
  return parts.join(' · ') || null
})
</script>

<template>
  <div class="flex items-center gap-2" role="status" data-testid="connection">
    <span
      class="mono inline-flex items-center gap-1.5 border px-2 py-0.5 text-[10.5px] tracking-[1px]"
      :class="
        store.connection === 'online'
          ? 'border-[var(--ink)] text-[var(--ink)]'
          : 'border-[var(--orange)] text-[var(--orange)]'
      "
      :data-state="store.connection"
    >
      <span
        class="inline-block h-1.5 w-1.5"
        :style="{
          background: store.connection === 'online' ? 'var(--accent-fill)' : 'var(--orange)',
        }"
        aria-hidden="true"
      ></span>
      {{ label }}
    </span>
    <span v-if="detail" class="micro" data-testid="connection-detail">{{ detail }}</span>
  </div>
</template>
