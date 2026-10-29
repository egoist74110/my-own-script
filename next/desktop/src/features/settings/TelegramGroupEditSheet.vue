<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import TextField from '@/components/TextField.vue'
import type { ACLGroup, TaskView } from './api'

const props = defineProps<{
  open: boolean
  group: ACLGroup | null
  allTasks: TaskView[]
  submitting?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  save: [
    data: {
      name: string
      can_run: boolean
      can_stop: boolean
      can_status: boolean
      can_rollback: boolean
      task_ids: string[]
    },
  ]
}>()

const name = ref('')
const canRun = ref(false)
const canStop = ref(false)
const canStatus = ref(true)
const canRollback = ref(false)
const taskIds = ref<string[]>([])
const touched = ref(false)

watch(
  () => props.open,
  (val) => {
    if (val) {
      touched.value = false
      if (props.group) {
        name.value = props.group.name
        canRun.value = props.group.can_run
        canStop.value = props.group.can_stop
        canStatus.value = props.group.can_status
        canRollback.value = props.group.can_rollback
        taskIds.value = [...(props.group.task_ids ?? [])]
      } else {
        name.value = ''
        canRun.value = false
        canStop.value = false
        canStatus.value = true
        canRollback.value = false
        taskIds.value = []
      }
    }
  },
  { immediate: true },
)

const validationError = computed(() => {
  if (!name.value.trim()) return '组名称不能为空'
  if (name.value.trim().length > 64) return '组名称不能超过 64 个字符'
  if ((canRun.value || canRollback.value) && taskIds.value.length === 0) {
    return '勾选运行或回滚权限时，需至少选择一个任务'
  }
  return null
})

function toggleTask(id: string) {
  touched.value = true
  if (taskIds.value.includes(id)) {
    taskIds.value = taskIds.value.filter((t) => t !== id)
  } else {
    taskIds.value.push(id)
  }
}

function onSave() {
  touched.value = true
  if (validationError.value) return
  emit('save', {
    name: name.value.trim(),
    can_run: canRun.value,
    can_stop: canStop.value,
    can_status: canStatus.value,
    can_rollback: canRollback.value,
    task_ids: taskIds.value,
  })
}
</script>

<template>
  <Sheet
    :open="open"
    :title="group ? `编辑权限组「${group.name}」` : '新建权限组'"
    description="配置权限组名称、操作权限位与可访问的任务列表。"
    @update:open="emit('update:open', $event)"
  >
    <div class="group-form" data-testid="group-edit-dialog">
      <Banner v-if="error" kind="error" class="mb-3" data-testid="group-error-banner">
        {{ error }}
      </Banner>

      <TextField
        v-model="name"
        label="组名称"
        placeholder="输入唯一的权限组名称"
        data-testid="group-name-input"
        :error="touched && !name.trim() ? '组名称不能为空' : undefined"
      />

      <div class="perm-section">
        <label class="section-label">权限位：</label>
        <div class="perm-grid">
          <label class="chk-label" data-testid="perm-can-run">
            <input v-model="canRun" type="checkbox" :disabled="submitting" />
            <span>执行任务（构建/发布）</span>
          </label>
          <label class="chk-label" data-testid="perm-can-stop">
            <input v-model="canStop" type="checkbox" :disabled="submitting" />
            <span>停止运行</span>
          </label>
          <label class="chk-label" data-testid="perm-can-status">
            <input v-model="canStatus" type="checkbox" :disabled="submitting" />
            <span>查询状态 (/status)</span>
          </label>
          <label class="chk-label" data-testid="perm-can-rollback">
            <input v-model="canRollback" type="checkbox" :disabled="submitting" />
            <span>执行回滚</span>
          </label>
        </div>
      </div>

      <div class="tasks-section">
        <div class="tasks-head">
          <label class="section-label">关联任务：</label>
          <span v-if="canRun || canRollback" class="req-hint">
            （拥有运行或回滚权限时必须至少选择一个任务）
          </span>
        </div>

        <div v-if="allTasks.length === 0" class="st-note">还没有可选的任务，请先到任务页创建。</div>
        <div v-else class="task-checkbox-list" data-testid="group-task-list">
          <label
            v-for="t in allTasks"
            :key="t.id"
            class="task-chk-item"
            :data-testid="`group-task-item-${t.id}`"
          >
            <input
              type="checkbox"
              :checked="taskIds.includes(t.id)"
              :disabled="submitting"
              @change="toggleTask(t.id)"
            />
            <span class="task-title">{{ t.name }}</span>
            <span v-if="t.tg_command" class="st-mono task-cmd">(/{{ t.tg_command }})</span>
          </label>
        </div>
      </div>

      <Banner v-if="touched && validationError" kind="error" data-testid="group-validation-error">
        {{ validationError }}
      </Banner>
    </div>

    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="primary"
        data-testid="save-group-btn"
        :disabled="submitting || (touched && Boolean(validationError))"
        @click="onSave"
      >
        {{ submitting ? '保存中…' : '保存' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.group-form {
  font-size: var(--text-body);
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.section-label {
  font-weight: 600;
  color: var(--ink);
  display: block;
  margin-bottom: 6px;
}
.perm-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  background: var(--bg-settings);
  padding: 10px 12px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
}
.chk-label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}
.tasks-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 6px;
}
.req-hint {
  font-size: var(--text-sub);
  color: var(--st-verify-fg);
}
.task-checkbox-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 180px;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  padding: 8px 12px;
  background: var(--bg-settings);
}
.task-chk-item {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 2px 0;
}
.task-title {
  font-weight: 500;
}
.task-cmd {
  color: var(--mute);
  font-size: var(--text-sub);
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
