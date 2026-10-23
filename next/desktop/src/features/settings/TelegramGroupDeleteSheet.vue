<script setup lang="ts">
import { computed } from 'vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import type { ACLGroup, ACLMember } from './api'

const props = defineProps<{
  open: boolean
  group: ACLGroup | null
  members: ACLMember[]
  submitting?: boolean
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: []
}>()

const groupMembers = computed(() => {
  if (!props.group) return []
  return props.members.filter((m) => m.group_id === props.group?.id)
})
</script>

<template>
  <Sheet
    :open="open"
    :title="`确认删除权限组「${group?.name}」？`"
    description="删除权限组不可撤销。其包含的组成员将被一并级联删除。"
    @update:open="emit('update:open', $event)"
  >
    <div class="delete-body" data-testid="group-delete-dialog">
      <div v-if="groupMembers.length > 0" class="members-warning">
        <p class="warn-head">
          该权限组包含以下 <strong>{{ groupMembers.length }}</strong> 个成员，将被一并删除：
        </p>
        <ul class="member-list" data-testid="delete-group-members-list">
          <li v-for="m in groupMembers" :key="m.id">
            <span class="m-label">{{ m.label || '（无备注）' }}</span>
            <span class="m-id st-mono">
              {{ m.username ? `@${m.username.replace(/^@/, '')}` : m.chat_id || '—' }}
            </span>
          </li>
        </ul>
      </div>
      <p v-else class="st-note">该权限组下暂无成员。</p>
    </div>

    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="destructive"
        data-testid="confirm-delete-group-btn"
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
.members-warning {
  background: var(--bn-warn-bg);
  border: 1px solid var(--bn-warn-line);
  color: var(--bn-warn-fg);
  border-radius: var(--r-ctl);
  padding: 10px 14px;
  margin-bottom: 8px;
}
.warn-head {
  margin: 0 0 6px;
  font-weight: 600;
}
.member-list {
  margin: 0;
  padding-left: 18px;
  max-height: 160px;
  overflow-y: auto;
}
.member-list li {
  margin-bottom: 4px;
}
.m-label {
  font-weight: 600;
  margin-right: 8px;
}
.m-id {
  font-size: var(--text-sub);
}
</style>
