import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 检查器开合状态在 localStorage 里的键；只存布尔值。 */
export const INSPECTOR_KEY = 'toolbox.ui.inspector'

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
  const inspectorOpen = ref(readOpen())
  /** 当前挂载着检查器内容的页面数；为 0 时壳里不显示检查器栏。 */
  const inspectorUsers = ref(0)
  function toggleInspector() {
    inspectorOpen.value = !inspectorOpen.value
    writeOpen(inspectorOpen.value)
  }
  return { inspectorOpen, inspectorUsers, toggleInspector }
})
