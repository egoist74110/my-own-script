<script setup lang="ts">
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'

defineProps<{
  open: boolean
  submitting?: boolean
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: []
  cancel: []
}>()
</script>

<template>
  <Sheet
    :open="open"
    title="开启 ADO 写工具权限确认"
    description="开启写工具后，AI 将具有在 ADO 创建工单的权限。"
    @update:open="emit('update:open', $event)"
  >
    <div class="confirm-body" data-testid="mcp-ado-write-confirm-dialog">
      <div class="confirm-desc">
        <p>写工具 <code>ado_create_work_item</code> 允许 AI 在会话或工单分析过程中直接创建工单。</p>
        <p class="st-warn">
          开启后该工具将暴露在 MCP 工具列表中，请确保已了解可能带来的数据写入风险。
        </p>
      </div>
    </div>
    <template #actions>
      <Button
        variant="primary"
        data-testid="confirm-enable-write-btn"
        :disabled="submitting"
        @click="emit('confirm')"
      >
        {{ submitting ? '保存中…' : '确认开启' }}
      </Button>
      <Button
        variant="default"
        data-testid="cancel-enable-write-btn"
        :disabled="submitting"
        @click="emit('cancel')"
      >
        取消
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.confirm-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: var(--text-body);
  line-height: 1.6;
}
.confirm-desc p {
  margin: 0 0 8px 0;
}
.confirm-desc p:last-child {
  margin-bottom: 0;
}
</style>
