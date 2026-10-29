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
    title="允许 AI 创建工单？"
    description="打开后，AI 可以在会话或工单分析中直接在 ADO 里建单。"
    @update:open="emit('update:open', $event)"
  >
    <div class="confirm-body" data-testid="mcp-ado-write-confirm-dialog">
      <div class="confirm-desc">
        <p>AI 会通过工具 <code>ado_create_work_item</code> 创建工单，不再逐次询问你。</p>
        <p class="st-warn">
          这个工具会向 ADO 写入数据，创建出的工单需要你自己去 ADO 里修改或删除。确认可以接受再打开。
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
