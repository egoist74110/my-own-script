<script setup lang="ts">
import { ref, watch } from 'vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import type { TaskView } from './api'

const props = defineProps<{
  open: boolean
  task: TaskView | null
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  submit: [offset: number]
}>()

const offset = ref(1)

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) offset.value = 1
  },
)

function onConfirm() {
  emit('submit', offset.value)
  emit('update:open', false)
}
</script>

<template>
  <Sheet
    :open="open"
    :title="`选择回滚版本 · ${task?.name}`"
    description="选择要回滚到的历史版本（偏移量 1-5，1 表示上一个版本）。"
    @update:open="emit('update:open', $event)"
  >
    <div class="rollback-options" data-testid="rollback-sheet">
      <label class="rollback-label">
        <span>回滚至前</span>
        <select v-model.number="offset" class="offset-select" data-testid="rollback-offset-select">
          <option :value="1">前 1 个版本（上一个 Release）</option>
          <option :value="2">前 2 个版本</option>
          <option :value="3">前 3 个版本</option>
          <option :value="4">前 4 个版本</option>
          <option :value="5">前 5 个版本</option>
        </select>
      </label>
      <p class="rollback-hint">提交后将执行只读预检，并在下一步确认计划前冻结所选历史 Release。</p>
    </div>
    <template #actions>
      <Button @click="emit('update:open', false)">取消</Button>
      <Button variant="primary" data-testid="start-rollback-preflight-btn" @click="onConfirm">
        生成回滚计划…
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.rollback-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: var(--text-body);
}
.rollback-label {
  display: flex;
  align-items: center;
  gap: 10px;
}
.offset-select {
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--ink);
  padding: 0 8px;
  font: inherit;
}
.rollback-hint {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
</style>
