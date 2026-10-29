<script setup lang="ts">
import { onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useBackendStore } from '@/stores/backend'
import { useUiStore } from '@/stores/ui'
import { inspectorHostKey } from '@/app/inspector'
import Banner from '@/components/Banner.vue'
import Pane from '@/components/Pane.vue'
import Sidebar from '@/components/Sidebar.vue'

const store = useBackendStore()
const ui = useUiStore()
const route = useRoute()
const sidebarPane = ref<{ $el: HTMLElement } | null>(null)
const inspectorHost = ref<HTMLElement | null>(null)
const inspectorPane = ref<{ $el: HTMLElement } | null>(null)
provide(inspectorHostKey, inspectorHost)

// 浮层模式（<1280）：Esc 或点浮层外关闭。点检查器开关本身交给开关自己切换，避免“先关再开”。
function onDocKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && ui.sidebarMode === 'overlay') ui.closeSidebarFloat()
  if (ui.inspectorOverlay && ui.inspectorFloatOpen && e.key === 'Escape') ui.closeInspectorFloat()
}
function onDocPointer(e: Event) {
  // 窄窗侧栏浮层：点浮层外收起（点侧栏自己的内容、开关都不算“外部”）
  if (ui.sidebarMode === 'overlay') {
    const t = e.target as Element | null
    if (t && !sidebarPane.value?.$el.contains(t)) ui.closeSidebarFloat()
  }
  if (!ui.inspectorOverlay || !ui.inspectorFloatOpen) return
  const t = e.target as Element | null
  if (!t) return
  if (inspectorPane.value?.$el.contains(t)) return
  if (t.closest('[data-testid="inspector-toggle"]')) return
  ui.closeInspectorFloat()
}
// 导航后浮层自动收起
watch(
  () => route.fullPath,
  () => ui.closeSidebarFloat(),
)
onMounted(() => {
  document.addEventListener('keydown', onDocKey)
  document.addEventListener('pointerdown', onDocPointer)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onDocKey)
  document.removeEventListener('pointerdown', onDocPointer)
})
</script>

<template>
  <div
    class="shell"
    :data-alert="store.alert.active ? 'true' : 'false'"
    :data-sidebar="ui.sidebarMode"
    :data-inspector="ui.inspectorVisible ? 'open' : 'closed'"
    :data-inspector-mode="ui.inspectorOverlay ? 'overlay' : 'docked'"
    data-testid="app-shell"
  >
    <Pane ref="sidebarPane" as="aside" surface="sidebar" class="sidebar" aria-label="侧栏">
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
      v-show="ui.inspectorVisible && ui.inspectorUsers > 0"
      ref="inspectorPane"
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
  /* fixed + inset:0：壳钉死在视口，不随文档滚动；配合 html/body overflow:hidden，聚焦长页面控件时整壳不会被顶出窗口 */
  position: fixed;
  inset: 0;
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
/* 1100–1279 与 960–1099：检查器浮在详情区上方，不占布局宽度；由 ui store 的 matchMedia 决定开合，这里只管样式 */
@media (max-width: 1279px) {
  .inspector {
    position: absolute;
    /* 从页面顶栏下沿开始，顶栏里的检查器开关仍可点 */
    top: var(--topbar-h);
    right: 0;
    bottom: 0;
    z-index: 20;
    max-width: calc(100% - var(--sidebar-w-compact));
    box-shadow:
      0 0 0 0.5px var(--line),
      -12px 0 32px rgba(0, 0, 0, 0.14);
  }
}
/* 收起（<1100 默认，或宽窗手动收起）：侧栏 76px 只显示图标 */
.shell:not([data-sidebar='expanded']) .sidebar {
  width: var(--sidebar-w-compact);
  padding: 0 8px 12px;
}
/* 窄窗手动展开：侧栏 212px 浮在内容上方，主区仍按 76px 留位，不被挤压 */
.shell[data-sidebar='overlay'] .main {
  margin-left: var(--sidebar-w-compact);
}
.shell[data-sidebar='overlay'] .sidebar {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: 30;
  width: var(--sidebar-w);
  padding: 0 10px 12px;
  box-shadow:
    0 0 0 0.5px var(--line),
    12px 0 32px rgba(0, 0, 0, 0.14);
}
.host {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: auto;
}
</style>
