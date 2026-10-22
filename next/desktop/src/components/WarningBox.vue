<script setup lang="ts">
import { computed } from 'vue'
import { useBackendStore } from '@/stores/backend'

const store = useBackendStore()
const rows = computed(() => {
  const a = store.alert
  const out = [
    { t: 'SYSTEM ALERT RAISED', hot: false },
    { t: a.reason ? a.reason.toUpperCase() : 'NO REASON GIVEN', hot: false },
    { t: `CHANGED AT ${a.changed_at || '--'}`, hot: false },
    { t: 'SOURCE · system.alert', hot: true },
  ]
  return out
})
</script>

<template>
  <div
    role="alert"
    class="absolute top-[44%] left-1/2 w-[380px] max-w-full -translate-x-[36%] -translate-y-1/2"
    data-testid="warning-box"
  >
    <div
      aria-hidden="true"
      class="absolute"
      style="
        inset: -140px -160px;
        background: radial-gradient(closest-side, rgba(5, 5, 6, 0.94) 50%, transparent);
      "
    ></div>
    <div
      class="relative flex flex-col items-center px-7 pt-[26px] pb-6"
      style="background: #060607; border: 1px solid rgba(255, 123, 0, 0.3)"
    >
      <svg class="anim-blink" aria-hidden="true" width="30" height="27" viewBox="0 0 30 27">
        <path
          d="M15 1 L29 26 L1 26 Z"
          fill="none"
          stroke="#ff7b00"
          stroke-width="2"
          stroke-linejoin="miter"
        />
        <rect x="14" y="9" width="2" height="9" fill="#ff7b00" />
        <rect x="14" y="20" width="2" height="2" fill="#ff7b00" />
      </svg>
      <div
        class="mt-[15px] flex h-12 w-full items-center justify-between text-[30px] tracking-[6px]"
        style="border: 2px solid #ff7b00; color: #ff7b00"
      >
        <span class="h-full w-[9px]" style="background: #ff7b00"></span>WARNING<span
          class="h-full w-[9px]"
          style="background: #ff7b00"
        ></span>
      </div>
      <div
        v-for="(r, i) in rows"
        :key="i"
        class="anim-row-in mt-[9px] flex w-full items-center justify-between text-[11px] font-medium tracking-[1px]"
        :style="{ color: r.hot ? '#ff7b00' : '#cfcdc8', animationDelay: `${0.26 + i * 0.24}s` }"
      >
        <span>{{ r.t }}</span>
        <span
          class="h-2 w-2"
          :style="{
            border: '1px solid currentColor',
            background: r.hot ? '#ff7b00' : 'transparent',
          }"
        ></span>
      </div>
    </div>
  </div>
</template>
