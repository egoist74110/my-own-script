<script setup lang="ts">
import { computed } from 'vue'
import { ApiError, errorText } from './api'
import AppButton from '@/components/AppButton.vue'

/** 固定文案的错误提示；no_credential 给出跳设置的入口，可选“重试”。 */
const props = defineProps<{ error: unknown; retry?: boolean }>()
defineEmits<{ retry: [] }>()
const text = computed(() => errorText(props.error))
const noCredential = computed(
  () => props.error instanceof ApiError && props.error.code === 'no_credential',
)
</script>

<template>
  <div class="wi-error" role="alert" data-testid="wi-error">
    <span>{{ text }}</span>
    <RouterLink v-if="noCredential" to="/settings" class="wi-link">前往设置</RouterLink>
    <AppButton v-if="retry" variant="ghost" @click="$emit('retry')">重试</AppButton>
    <slot />
  </div>
</template>

<style scoped>
.wi-error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  font-size: 12.5px;
  background: rgba(255, 140, 40, 0.14);
  box-shadow: inset 3px 0 0 var(--warn);
}
.wi-link {
  color: var(--ink);
  font-weight: 600;
  text-decoration: underline;
  min-height: var(--target-min);
  display: inline-flex;
  align-items: center;
}
</style>
