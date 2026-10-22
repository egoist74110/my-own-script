<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, inject } from 'vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import AlertToggle from '@/components/AlertToggle.vue'
import ClockBlock from '@/components/ClockBlock.vue'
import ConnectionBadge from '@/components/ConnectionBadge.vue'
import InfinityPlaceholder from '@/components/InfinityPlaceholder.vue'
import WarningBox from '@/components/WarningBox.vue'
import { useBackendStore } from '@/stores/backend'

const store = useBackendStore()
const runtime = inject(backendRuntimeKey, null)

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
</script>

<template>
  <section
    class="relative flex min-h-[560px] min-w-0 flex-[1_1_420px] items-center justify-center"
    aria-label="主视觉"
  >
    <InfinityPlaceholder />
    <WarningBox v-if="store.alert.active" />
  </section>

  <div class="flex min-w-0 max-w-[600px] flex-[1_1_480px] flex-col gap-[22px]">
    <div class="self-end">
      <ClockBlock />
    </div>

    <section
      class="glass flex flex-col gap-4 overflow-hidden px-7 pt-[26px] pb-6"
      aria-label="系统状态"
    >
      <div class="relative flex items-center justify-between">
        <span class="flex items-center gap-2 text-[10.5px] font-semibold tracking-[1.2px]"
          ><span class="sq" style="width: 4px; height: 4px"></span>SECTION · SYSTEM</span
        >
        <span class="chip">TOOLBOX.LOCAL</span>
      </div>
      <ConnectionBadge />
      <dl class="m-0 grid grid-cols-[auto_1fr] gap-x-[14px] gap-y-1.5">
        <dt class="text-[12.5px] font-medium text-[var(--mute)]">VERSION</dt>
        <dd class="mono m-0 text-[13px] font-medium" data-testid="health-version">
          {{ health.data.value?.version ?? store.version ?? '--' }}
        </dd>
        <dt class="text-[12.5px] font-medium text-[var(--mute)]">UPTIME</dt>
        <dd class="mono m-0 text-[13px] font-medium" data-testid="health-uptime">
          {{ health.data.value ? `${Math.round(health.data.value.uptime_s)} S` : '--' }}
        </dd>
      </dl>
      <AlertToggle />
    </section>
  </div>
</template>
