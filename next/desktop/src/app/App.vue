<script setup lang="ts">
import { provide, ref } from 'vue'
import { useBackendStore } from '@/stores/backend'
import { useUiStore } from '@/stores/ui'
import { inspectorHostKey } from '@/app/inspector'
import Banner from '@/components/Banner.vue'
import Pane from '@/components/Pane.vue'
import Sidebar from '@/components/Sidebar.vue'

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
    <Pane as="aside" surface="sidebar" class="sidebar" aria-label="侧栏">
      <div data-tauri-drag-region class="drag"></div>
      <Sidebar />
    </Pane>

    <main class="main" aria-label="主区">
      <Banner
        v-if="store.alert.active"
        kind="warn"
        role="alert"
        data-testid="alert-banner"
        class="alert"
      >
        <span data-testid="alert-reason">{{
          store.alert.reason?.trim() || '后端报告告警（未提供原因）'
        }}</span>
      </Banner>
      <div class="page"><RouterView /></div>
    </main>

    <Pane
      v-show="ui.inspectorOpen && ui.inspectorUsers > 0"
      as="aside"
      surface="inspector"
      class="inspector"
      aria-label="检查器"
      data-testid="inspector"
    >
      <div ref="inspectorHost" class="host"></div>
    </Pane>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  /* 100% 而非 100vh：Tauri/WKWebView（Overlay 标题栏、窗口缩放后）的 vh 可能与实际窗口不一致，导致壳只占一截 */
  height: 100%;
  background: var(--bg-window);
  /* clip 而非 hidden：hidden 仍是可滚动容器，聚焦边缘控件时会把整壳滚走 */
  overflow: clip;
}
.sidebar {
  flex: none;
  width: var(--sidebar-w);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  padding: 0 10px 12px;
  border-right: 1px solid var(--line-sidebar);
  min-height: 0;
}
.drag {
  flex: none;
  height: var(--topbar-h);
}
.main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.alert {
  margin: 8px 12px 0;
  flex: none;
}
.page {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
}
.inspector {
  flex: none;
  width: var(--inspector-w);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--line);
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
