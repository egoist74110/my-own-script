<script setup lang="ts">
import { provide, ref } from 'vue'
import { useBackendStore } from '@/stores/backend'
import { useUiStore } from '@/stores/ui'
import { inspectorHostKey } from '@/app/inspector'
import AlertBanner from '@/components/AlertBanner.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import SidebarNav from '@/components/SidebarNav.vue'
import StatusBar from '@/components/StatusBar.vue'

const store = useBackendStore()
const ui = useUiStore()
const inspectorHost = ref<HTMLElement | null>(null)
provide(inspectorHostKey, inspectorHost)
</script>

<template>
  <div
    class="shell"
    :data-alert="store.alert.active ? 'true' : 'false'"
    :data-inspector="ui.inspectorOpen ? 'open' : 'closed'"
    data-testid="app-shell"
  >
    <div aria-hidden="true" class="glows">
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
    </div>

    <GlassPanel as="aside" class="sidebar" aria-label="侧栏">
      <div data-tauri-drag-region class="drag"></div>
      <div class="brand">
        <span class="mark cut-xs">
          <svg aria-hidden="true" width="18" height="10" viewBox="0 0 24 14">
            <path
              d="M12 7C9.6 3.6 7.8 2 5.4 2 2.9 2 1 4.2 1 7s1.9 5 4.4 5c2.4 0 4.2-1.6 6.6-5Zm0 0c2.4 3.4 4.2 5 6.6 5 2.5 0 4.4-2.2 4.4-5s-1.9-5-4.4-5C16.2 2 14.4 3.6 12 7Z"
              fill="none"
              stroke="#c6f432"
              stroke-width="2.4"
            />
          </svg>
        </span>
        <span class="ox wordmark">TOOLBOX</span>
      </div>
      <SidebarNav />
    </GlassPanel>

    <main class="main" aria-label="主区">
      <AlertBanner v-if="store.alert.active" :reason="store.alert.reason ?? null" />
      <RouterView />
    </main>

    <GlassPanel
      v-show="ui.inspectorOpen"
      as="aside"
      class="inspector"
      aria-label="检查器"
      data-testid="inspector"
    >
      <div ref="inspectorHost" class="host"></div>
    </GlassPanel>

    <StatusBar />
  </div>
</template>

<style scoped>
.shell {
  position: relative;
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr) auto;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 14px;
  height: 100vh;
  box-sizing: border-box;
  padding: 14px;
  /* clip 而非 hidden：hidden 仍是可滚动容器，聚焦右下角控件时会把整壳滚走 */
  overflow: clip;
}
.glows {
  position: absolute;
  inset: 0;
  overflow: clip;
  pointer-events: none;
}
.glow {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}
.glow-a {
  width: 560px;
  height: 560px;
  left: -180px;
  top: -240px;
  filter: blur(100px);
  background: var(--acc);
  opacity: 0.28;
}
.glow-b {
  width: 520px;
  height: 520px;
  right: -160px;
  bottom: -220px;
  filter: blur(110px);
  background: #b9d2ff;
  opacity: 0.5;
}
.sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px 12px;
  min-height: 0;
  overflow: auto;
}
.drag {
  height: 28px;
  flex: none;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px 14px;
}
.mark {
  width: 28px;
  height: 28px;
  background: var(--ink);
  display: grid;
  place-items: center;
}
.wordmark {
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0.8px;
}
.main {
  position: relative;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
}
.inspector {
  position: relative;
  width: 340px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.host {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: auto;
}
</style>
