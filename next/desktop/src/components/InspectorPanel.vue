<script setup lang="ts">
import { inject } from 'vue'
import { inspectorHostKey } from '@/app/inspector'

/** 页面向右侧检查器提供内容：内容经 Teleport 进入 App 壳的检查器容器。 */
defineProps<{ label: string; alert?: boolean }>()
const host = inject(inspectorHostKey, null)
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
