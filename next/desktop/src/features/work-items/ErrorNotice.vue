<script setup lang="ts">
import { computed } from 'vue'
import { ApiError, errorText } from './api'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'

/** 固定文案的错误提示；no_credential 给出跳设置的入口，可选“重试”。 */
const props = defineProps<{ error: unknown; retry?: boolean }>()
defineEmits<{ retry: [] }>()
const text = computed(() => errorText(props.error))
const noCredential = computed(
  () => props.error instanceof ApiError && props.error.code === 'no_credential',
)
</script>

<template>
  <Banner kind="error" role="alert" data-testid="wi-error" class="wi-error">
    <span>{{ text }}</span>
    <template #actions>
      <RouterLink v-if="noCredential" to="/settings" class="wi-link">前往设置</RouterLink>
      <Button v-if="retry" @click="$emit('retry')">重试</Button>
      <slot />
    </template>
  </Banner>
</template>

<style scoped>
.wi-error {
  margin: 8px 12px;
}
.wi-link {
  display: inline-flex;
  align-items: center;
  min-height: var(--target-min);
  color: var(--bn-error-title);
  font-weight: 600;
  text-decoration: underline;
}
</style>
