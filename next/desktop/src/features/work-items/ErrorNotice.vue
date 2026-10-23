<script setup lang="ts">
import { computed } from 'vue'
import { AlertTriangle } from 'lucide-vue-next'
import { ApiError, errorText } from './api'
import Button from '@/components/Button.vue'
import EmptyState from '@/components/EmptyState.vue'

/** 固定文案的错误提示；列表区居中 EmptyState，no_credential 给出跳设置的入口，可选“重试”。 */
const props = defineProps<{ error: unknown; retry?: boolean }>()
defineEmits<{ retry: [] }>()
const text = computed(() => errorText(props.error))
const noCredential = computed(
  () => props.error instanceof ApiError && props.error.code === 'no_credential',
)
</script>

<template>
  <EmptyState
    tone="error"
    :icon="AlertTriangle"
    title="无法读取工单"
    :description="text"
    role="alert"
    data-testid="wi-error"
    class="wi-error"
  >
    <template #actions>
      <RouterLink v-if="noCredential" to="/settings" class="wi-link">前往设置</RouterLink>
      <Button v-if="retry" @click="$emit('retry')">重试</Button>
      <slot />
    </template>
  </EmptyState>
</template>

<style scoped>
.wi-error {
  flex: 1;
}
.wi-link {
  display: inline-flex;
  align-items: center;
  min-height: var(--ctl-h);
  padding: 0 12px;
  border-radius: var(--r-ctl);
  font-size: var(--text-body);
  color: var(--accent-ink);
  text-decoration: none;
}
.wi-link:hover {
  text-decoration: underline;
}
</style>
