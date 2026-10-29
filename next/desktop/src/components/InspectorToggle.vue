<script setup lang="ts">
import { PanelRight } from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import ToolbarButton from './ToolbarButton.vue'

/** 页面顶栏右侧的检查器开关（aria-pressed）。并排模式的开合状态存 localStorage `toolbox.ui.inspector`（仅布尔）；浮层模式不持久化。 */
const ui = useUiStore()
</script>

<template>
  <ToolbarButton
    :label="ui.inspectorVisible ? '收起检查器' : '展开检查器'"
    :pressed="ui.inspectorVisible"
    data-testid="inspector-toggle"
    @click="ui.toggleInspector()"
  >
    <PanelRight :size="16" aria-hidden="true" />
  </ToolbarButton>
</template>
