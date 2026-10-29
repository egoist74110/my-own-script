<script setup lang="ts">
import { computed } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import { discoverErrorText, type DiscoveredItem } from './discover'

/**
 * Agent 队列下拉：可选“不指定”。列表来自 ADO 发现；读取中、失败、空列表都有明确状态。
 * 选中的队列不在列表里（例如手填的旧值）时仍保留为一项，不会被悄悄清掉。
 */
const props = defineProps<{
  queues: DiscoveredItem[] | undefined
  loading?: boolean
  error?: unknown
  /** 当前已选（用于列表外的旧值）。 */
  currentName?: string
  label?: string
}>()
const emit = defineEmits<{ retry: [] }>()
const queueId = defineModel<string>('queueId', { default: '' })
const queueName = defineModel<string>('queueName', { default: '' })

const options = computed(() => {
  const list = props.queues ?? []
  if (queueId.value && !list.some((q) => q.id === queueId.value))
    return [
      ...list,
      { id: queueId.value, name: queueName.value || props.currentName || queueId.value },
    ]
  return list
})

function onChange(e: Event) {
  const id = (e.target as HTMLSelectElement).value
  const hit = options.value.find((q) => q.id === id)
  queueId.value = id
  queueName.value = hit?.name ?? ''
}
</script>

<template>
  <div class="qs" data-testid="queue-select">
    <p v-if="loading" class="qs-hint" role="status" data-testid="queue-loading">
      正在读取 Agent 队列…
    </p>
    <Banner v-else-if="error" kind="error" data-testid="queue-error">
      {{ discoverErrorText(error) }}
      <template #actions>
        <Button data-testid="queue-retry" @click="emit('retry')">重试</Button>
      </template>
    </Banner>
    <template v-else>
      <select
        class="qs-sel"
        :aria-label="label ?? 'Agent 队列'"
        data-testid="queue-select-input"
        :value="queueId"
        @change="onChange"
      >
        <option value="">不指定</option>
        <option v-for="q in options" :key="q.id" :value="q.id">{{ q.name }}</option>
      </select>
      <p v-if="(queues ?? []).length === 0" class="qs-hint" data-testid="queue-empty">
        该项目没有可用队列，可留空。
      </p>
    </template>
  </div>
</template>

<style scoped>
.qs {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.qs-sel {
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--ink);
  padding: 0 8px;
  font: inherit;
}
.qs-hint {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
</style>
