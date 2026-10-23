<script setup lang="ts">
import { computed } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import { errorText, type TaskView } from './api'

const props = defineProps<{
  open: boolean
  task: TaskView | null
  submitting?: boolean
  error?: unknown
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: []
  'confirm-detach': []
}>()

const referencedGroups = computed(() => {
  if (
    props.error &&
    typeof props.error === 'object' &&
    'code' in props.error &&
    (props.error as { code: string }).code === 'task_referenced'
  ) {
    const d = (props.error as { detail?: Record<string, unknown> }).detail
    if (d && Array.isArray(d.groups)) {
      return d.groups.filter((g): g is string => typeof g === 'string')
    }
  }
  return []
})
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
      <div
        v-if="referencedGroups.length > 0"
        class="referenced-box mb-2"
        data-testid="task-referenced-groups"
      >
        <p class="warn-title">该任务已被以下 {{ referencedGroups.length }} 个权限组引用：</p>
        <ul class="group-list">
          <li v-for="g in referencedGroups" :key="g">{{ g }}</li>
        </ul>
        <p class="detach-hint">
          您可以选择同时从这些权限组中移除引用并删除任务，或先手动调整权限组配置。
        </p>
      </div>
      <p>将从工具箱配置中移除此任务定义。这不会影响磁盘上的本地代码仓库或远端 ADO 服务。</p>
    </div>
    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        v-if="referencedGroups.length > 0"
        variant="destructive"
        data-testid="confirm-detach-delete-task-btn"
        :disabled="submitting"
        @click="emit('confirm-detach')"
      >
        {{ submitting ? '删除中…' : `同时从 ${referencedGroups.length} 个权限组移除并删除` }}
      </Button>
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
.referenced-box {
  background: var(--bn-warn-bg);
  border: 1px solid var(--bn-warn-line);
  color: var(--bn-warn-fg);
  border-radius: var(--r-ctl);
  padding: 10px 14px;
}
.warn-title {
  margin: 0 0 6px !important;
  font-weight: 600;
}
.group-list {
  margin: 0 0 6px;
  padding-left: 20px;
}
.detach-hint {
  font-size: var(--text-sub);
  color: var(--mute);
  margin: 0 !important;
}
</style>
