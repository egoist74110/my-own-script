import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref } from 'vue'

/** 检查器开合状态在 localStorage 里的键；只存布尔值。 */
export const INSPECTOR_KEY = 'toolbox.ui.inspector'

/** 窗口宽度小于 1280 时检查器改为浮层（规范 §3）；≥1280 并排一栏。 */
export const INSPECTOR_OVERLAY_QUERY = '(max-width: 1279px)'

/** 侧栏手动选择（宽窗下的展开/收起）；只存 'expanded' | 'collapsed'，没有这个键表示从未手动选过。 */
export const SIDEBAR_KEY = 'toolbox.ui.sidebar'

/** 窗口宽度 ≥1100 时侧栏默认展开（212px，带文字）；更窄时收成 76px 只显示图标（给红黄绿按钮留位）。 */
export const SIDEBAR_WIDE_QUERY = '(min-width: 1100px)'

export type SidebarPref = 'expanded' | 'collapsed'
/** expanded：并排 212px；compact：并排 76px 仅图标；overlay：窄窗下手动展开，浮在内容上方（主区仍按 76px 留位）。 */
export type SidebarMode = 'expanded' | 'compact' | 'overlay'

function readSidebarPref(): SidebarPref | null {
  try {
    const v = localStorage.getItem(SIDEBAR_KEY)
    return v === 'expanded' || v === 'collapsed' ? v : null
  } catch {
    return null
  }
}
function writeSidebarPref(v: SidebarPref) {
  try {
    localStorage.setItem(SIDEBAR_KEY, v)
  } catch {
    // 存储不可用时只保留内存状态
  }
}

function readOpen(): boolean {
  try {
    return localStorage.getItem(INSPECTOR_KEY) !== 'false'
  } catch {
    return true
  }
}
function writeOpen(open: boolean) {
  try {
    localStorage.setItem(INSPECTOR_KEY, open ? 'true' : 'false')
  } catch {
    // 存储不可用时只保留内存状态
  }
}

/** 纯界面状态（不涉及连接/安全）。 */
export const useUiStore = defineStore('ui', () => {
  /** 并排模式（≥1280）下检查器是否打开；持久化。 */
  const inspectorOpen = ref(readOpen())
  /** 当前挂载着检查器内容的页面数；为 0 时壳里不显示检查器栏。 */
  const inspectorUsers = ref(0)

  /** 窄窗（<1280）：检查器是浮在详情区上方的浮层，不占布局宽度。matchMedia 不可用时按并排处理。 */
  const inspectorOverlay = ref(false)
  /** 浮层模式下是否打开；不持久化，每次进入窄窗默认收起，避免盖住详情。 */
  const inspectorFloatOpen = ref(false)
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    const mq = window.matchMedia(INSPECTOR_OVERLAY_QUERY)
    inspectorOverlay.value = mq.matches
    const onChange = (e: MediaQueryListEvent) => {
      inspectorOverlay.value = e.matches
      inspectorFloatOpen.value = false
    }
    mq.addEventListener('change', onChange)
    onScopeDispose(() => mq.removeEventListener('change', onChange))
  }

  /**
   * 侧栏优先级：
   * - 宽窗（≥1100）：手动选择（持久化）优先；从未选过则默认展开。
   * - 窄窗（<1100）：默认收成图标；按钮只开关一个不持久化的浮层，Esc / 点外部 / 切换页面都会收起，
   *   不会覆盖宽窗下保存的手动选择。
   */
  const sidebarPref = ref<SidebarPref | null>(readSidebarPref())
  /** matchMedia 不可用时按宽窗处理。 */
  const sidebarWide = ref(true)
  const sidebarFloatOpen = ref(false)
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    const mq = window.matchMedia(SIDEBAR_WIDE_QUERY)
    sidebarWide.value = mq.matches
    const onChange = (e: MediaQueryListEvent) => {
      sidebarWide.value = e.matches
      sidebarFloatOpen.value = false
    }
    mq.addEventListener('change', onChange)
    onScopeDispose(() => mq.removeEventListener('change', onChange))
  }
  const sidebarMode = computed<SidebarMode>(() => {
    if (sidebarWide.value) return sidebarPref.value === 'collapsed' ? 'compact' : 'expanded'
    return sidebarFloatOpen.value ? 'overlay' : 'compact'
  })
  function toggleSidebar() {
    if (sidebarWide.value) {
      sidebarPref.value = sidebarMode.value === 'expanded' ? 'collapsed' : 'expanded'
      writeSidebarPref(sidebarPref.value)
      return
    }
    sidebarFloatOpen.value = !sidebarFloatOpen.value
  }
  /** 关闭窄窗浮层（Esc / 点外部 / 导航）；宽窗下不动。 */
  function closeSidebarFloat() {
    sidebarFloatOpen.value = false
  }

  /** 当前模式下检查器是否应显示（尚未考虑是否有页面提供内容）。 */
  const inspectorVisible = computed(() =>
    inspectorOverlay.value ? inspectorFloatOpen.value : inspectorOpen.value,
  )

  function toggleInspector() {
    if (inspectorOverlay.value) {
      inspectorFloatOpen.value = !inspectorFloatOpen.value
      return
    }
    inspectorOpen.value = !inspectorOpen.value
    writeOpen(inspectorOpen.value)
  }
  /** 关闭浮层（Esc / 点浮层外）；并排模式下不动。 */
  function closeInspectorFloat() {
    inspectorFloatOpen.value = false
  }
  return {
    inspectorOpen,
    inspectorUsers,
    inspectorOverlay,
    inspectorFloatOpen,
    inspectorVisible,
    toggleInspector,
    closeInspectorFloat,
    sidebarPref,
    sidebarWide,
    sidebarMode,
    toggleSidebar,
    closeSidebarFloat,
  }
})
