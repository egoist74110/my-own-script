<script setup lang="ts">
import { computed } from 'vue'
import SidebarNav from '@/components/SidebarNav.vue'
import { useBackendStore } from '@/stores/backend'

const store = useBackendStore()
// 根节点 --denied 只由 store.alert（后端 system.alert 事件）决定
const hudStyle = computed(() => ({ '--denied': String(store.denied) }))
</script>

<template>
  <div class="hud relative min-h-screen overflow-hidden" :style="hudStyle" data-testid="hud-root">
    <div
      aria-hidden="true"
      class="absolute inset-0"
      style="
        background: radial-gradient(
          60% 55% at 50% 48%,
          color-mix(in srgb, var(--card) 70%, transparent),
          transparent 70%
        );
      "
    ></div>

    <div class="relative box-border flex min-h-screen flex-wrap gap-7 px-11 pt-10 pb-7">
      <aside
        aria-label="系统侧栏"
        class="relative flex min-w-[260px] flex-[0_1_300px] flex-col gap-[26px]"
      >
        <div data-tauri-drag-region class="h-5"></div>
        <div class="inline-flex flex-col leading-none">
          <span class="text-[44px] font-bold tracking-[1px]">TOOLBOX</span>
          <span class="mt-2 text-sm font-medium tracking-[3.1px] whitespace-nowrap"
            >DEPLOY · INTEGRATE · OPERATE</span
          >
          <span class="mt-1 text-[37px] whitespace-nowrap"
            ><span class="font-light">CONTROL</span> <span class="font-bold">OS</span></span
          >
        </div>
        <div class="flex gap-4">
          <span aria-hidden="true" class="h-[220px] w-[13px] flex-none bg-[var(--ink)]"></span>
          <div class="flex min-w-0 flex-col gap-3">
            <span class="chip">TOOLBOX DATABASE</span>
            <p class="micro m-0">
              本机控制终端。负责同步、构建、发布、工单分析与 AI
              会话；所有凭据只经后端，界面不持有密钥。
            </p>
            <span class="block h-px w-[180px] bg-[var(--mute)]"></span>
            <span class="chip">CAPABILITY INDEX</span>
            <p class="micro m-0">S0 · 仅总览可用，其余能力随切片上线。</p>
          </div>
        </div>
        <SidebarNav />
        <div class="flex-1"></div>
        <div class="flex items-center gap-3">
          <span class="h-3.5 w-[46px] bg-[var(--ink)]"></span>
          <span class="text-base font-bold tracking-[0.6px]">{{
            store.alert.active ? 'DEFENSE SECTION · LOCKDOWN' : 'CONTROL SECTION · ONLINE'
          }}</span>
        </div>
      </aside>

      <RouterView />

      <footer
        class="micro flex basis-full flex-wrap items-center justify-between gap-4"
        data-testid="about"
      >
        <span>
          VISUAL LANGUAGE ADAPTED FROM RHINE-LOCK (AGPL-3.0) · FONTS MONTSERRAT / JETBRAINS MONO
          (SIL OFL) · SEE NEXT/THIRD_PARTY.MD
        </span>
        <span class="text-base font-bold tracking-[1.2px] text-[var(--ink)]"
          >POWERED BY TOOLBOX</span
        >
      </footer>
    </div>
  </div>
</template>
