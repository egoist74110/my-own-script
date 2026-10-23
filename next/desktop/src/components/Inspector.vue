<script setup lang="ts">
import { inject, onBeforeUnmount, onMounted } from 'vue'
import { inspectorHostKey } from '@/app/inspector'
import { useUiStore } from '@/stores/ui'

/** 页面向右侧检查器提供内容：内容经 Teleport 进入 App 壳的检查器容器。 */
defineProps<{ label: string; alert?: boolean }>()
const host = inject(inspectorHostKey, null)
const ui = useUiStore()
onMounted(() => (ui.inspectorUsers += 1))
onBeforeUnmount(() => (ui.inspectorUsers -= 1))
</script>

<template>
  <Teleport v-if="host" :to="host">
    <div
      class="inspector-body"
      :data-alert="alert ? 'true' : undefined"
      :aria-label="label"
      role="region"
    >
      <slot />
    </div>
  </Teleport>
</template>

<style scoped>
.inspector-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}
</style>
