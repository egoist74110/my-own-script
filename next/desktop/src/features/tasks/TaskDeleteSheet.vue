<script setup lang="ts">
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import { errorText, type TaskView } from './api'

defineProps<{
  open: boolean
  task: TaskView | null
  submitting?: boolean
  error?: unknown
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: []
}>()
</script>

<template>
  <Sheet
    :open="open"
    :title="`确认删除任务「${task?.name}」？`"
    description="删除后不可撤销。被其他配置引用的任务无法直接删除。"
    @update:open="emit('update:open', $event)"
  >
    <div class="delete-body">
      <Banner v-if="error" kind="error" class="mb-2" data-testid="delete-task-error">
        {{ errorText(error) }}
      </Banner>
      <p>将从工具箱配置中移除此任务定义。这不会影响磁盘上的本地代码仓库或远端 ADO 服务。</p>
    </div>
    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="destructive"
        data-testid="confirm-delete-task-btn"
        :disabled="submitting"
        @click="emit('confirm')"
      >
        {{ submitting ? '删除中…' : '确认删除' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.delete-body {
  font-size: var(--text-body);
  color: var(--ink);
}
.delete-body p {
  margin: 4px 0;
}
.mb-2 {
  margin-bottom: 8px;
}
</style>
