<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import TextField from '@/components/TextField.vue'
import type { ACLGroup, ACLMember } from './api'

const props = defineProps<{
  open: boolean
  member: ACLMember | null
  groups: ACLGroup[]
  submitting?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  save: [
    data: {
      group_id: string
      label: string
      chat_id: string | null
      username: string | null
    },
  ]
}>()

const groupId = ref('')
const label = ref('')
const chatId = ref('')
const username = ref('')
const touched = ref(false)

watch(
  () => props.open,
  (val) => {
    if (val) {
      touched.value = false
      if (props.member) {
        groupId.value = props.member.group_id
        label.value = props.member.label
        chatId.value = props.member.chat_id ?? ''
        username.value = props.member.username ?? ''
      } else {
        groupId.value = props.groups[0]?.id ?? ''
        label.value = ''
        chatId.value = ''
        username.value = ''
      }
    }
  },
  { immediate: true },
)

const validationError = computed(() => {
  if (!groupId.value) return '请选择所属权限组'
  const c = chatId.value.trim()
  const u = username.value.trim()
  if (!c && !u) return 'Chat ID 与用户名需至少填写一项'
  return null
})

function onSave() {
  touched.value = true
  if (validationError.value) return

  let u = username.value.trim()
  if (u && !u.startsWith('@')) {
    u = `@${u}`
  }

  emit('save', {
    group_id: groupId.value,
    label: label.value.trim(),
    chat_id: chatId.value.trim() ? chatId.value.trim() : null,
    username: u ? u : null,
  })
}
</script>

<template>
  <Sheet
    :open="open"
    :title="
      member ? `编辑成员「${member.label || member.username || member.chat_id}」` : '添加组成员'
    "
    description="配置成员的所属权限组、备注及识别标识（Chat ID 或 @用户名）。"
    @update:open="emit('update:open', $event)"
  >
    <div class="member-form" data-testid="member-edit-dialog">
      <Banner v-if="error" kind="error" class="mb-3" data-testid="member-error-banner">
        {{ error }}
      </Banner>

      <div class="form-fld">
        <label class="lbl" for="member-group-select">所属权限组</label>
        <select
          id="member-group-select"
          v-model="groupId"
          class="st-select group-select"
          data-testid="member-group-select"
          :disabled="submitting"
        >
          <option v-for="g in groups" :key="g.id" :value="g.id">
            {{ g.name }}
          </option>
        </select>
      </div>

      <TextField
        v-model="label"
        label="备注名称"
        placeholder="例如：运维专员张三"
        data-testid="member-label-input"
        :disabled="submitting"
      />

      <TextField
        v-model="chatId"
        label="Telegram Chat ID"
        placeholder="例如：123456789（私聊或群聊 ID）"
        data-testid="member-chat-id-input"
        :disabled="submitting"
      />

      <TextField
        v-model="username"
        label="Telegram 用户名 (@username)"
        placeholder="例如：@alice"
        data-testid="member-username-input"
        :disabled="submitting"
      />

      <p class="st-note">
        提示：Chat ID 与用户名至少填写一项。通过用户名匹配的成员在首次私聊互动后会自动绑定其数字
        User ID。
      </p>

      <Banner v-if="touched && validationError" kind="error" data-testid="member-validation-error">
        {{ validationError }}
      </Banner>
    </div>

    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="primary"
        data-testid="save-member-btn"
        :disabled="submitting || (touched && Boolean(validationError))"
        @click="onSave"
      >
        {{ submitting ? '保存中…' : '保存' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.member-form {
  font-size: var(--text-body);
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.form-fld {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.lbl {
  font-weight: 600;
  color: var(--ink);
}
.group-select {
  width: 100%;
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
