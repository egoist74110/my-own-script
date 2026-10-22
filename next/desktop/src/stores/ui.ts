import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 纯界面状态（不涉及连接/安全）。 */
export const useUiStore = defineStore('ui', () => {
  const inspectorOpen = ref(true)
  function toggleInspector() {
    inspectorOpen.value = !inspectorOpen.value
  }
  return { inspectorOpen, toggleInspector }
})
