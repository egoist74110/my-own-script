<script setup lang="ts">
import { ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'

const props = defineProps<{
  open: boolean
  aiTitle: string
  submitting: boolean
  error?: string | null
  webhookSet?: boolean
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: [opts: { ackOldBotCleared: boolean; deleteWebhook: boolean }]
}>()

const ackOldBotCleared = ref(false)
const deleteWebhook = ref(false)

watch(
  () => props.open,
  (val) => {
    if (val) {
      ackOldBotCleared.value = false
      deleteWebhook.value = false
    }
  },
)

function onConfirm() {
  if (!ackOldBotCleared.value || props.submitting) return
  emit('confirm', {
    ackOldBotCleared: ackOldBotCleared.value,
    deleteWebhook: Boolean(props.webhookSet && deleteWebhook.value),
  })
}
</script>

<template>
  <Sheet
    :open="open"
    :title="`启用 ${aiTitle}`"
    description="接管前请仔细核对切换步骤，避免多个端同时长轮询导致 Telegram 409 conflict 冲突。切换后，旧应用主机器人对该 AI 的‘MCP 分析’将不再可用（会话输出会丢失），请改用新应用。"
    @update:open="emit('update:open', $event)"
  >
    <div class="enable-flow p-1" data-testid="ai-bot-enable-sheet">
      <Banner v-if="error" kind="error" class="mb-3" data-testid="enable-error-banner">
        {{ error }}
      </Banner>

      <!-- 4 步说明 -->
      <ol class="step-list">
        <li>
          <strong>步骤 1：录入 Token</strong>
          <p class="step-desc">确认已在当前界面中录入并保存该机器人的 Bot Token。</p>
        </li>
        <li>
          <strong>步骤 2：清除旧版绑定</strong>
          <p class="step-desc">
            打开旧版应用，在 AI 配置界面清空对应 AI 机器人的 Token
            并保存（不要关闭主任务机器人）。切换后，旧应用主机器人对该 AI 的‘MCP
            分析’将不再可用（会话输出会丢失），请改用新应用。
          </p>
        </li>
        <li>
          <strong>步骤 3：确认并启用</strong>
          <p class="step-desc">在下方勾选“我已在旧版应用中清空对应 Token”并点击确认。</p>
        </li>
        <li>
          <strong>步骤 4：冲突与回滚</strong>
          <p class="step-desc">
            如遇到 409 conflict 冲突，请检查是否有残留的旧进程或未保存的清空操作，重复步骤 2
            后重试。<br />
            <strong>回滚说明：</strong>如需退回旧版，请先在此处停用该机器人，再将 Token
            粘贴回旧版应用。
          </p>
        </li>
      </ol>

      <div class="ack-section mt-4 pt-3 border-t border-neutral-200 dark:border-neutral-800">
        <label class="ack-label">
          <input
            v-model="ackOldBotCleared"
            type="checkbox"
            data-testid="ack-old-cleared-checkbox"
            :disabled="submitting"
          />
          <span class="font-medium text-sm">我已在旧版应用中清空对应 Bot Token</span>
        </label>
      </div>

      <div v-if="webhookSet" class="mt-3" data-testid="ai-webhook-section">
        <Banner kind="warn" class="mb-2">
          检测到该 Bot 在 Telegram 上设置了 webhook。webhook
          与长轮询不能同时存在，需确认删除后才能启用。
        </Banner>
        <label class="ack-label">
          <input
            v-model="deleteWebhook"
            type="checkbox"
            data-testid="ai-delete-webhook-checkbox"
            :disabled="submitting"
          />
          <span class="font-medium text-sm">确认删除 Telegram 上已注册的 webhook</span>
        </label>
      </div>

      <div class="sheet-actions mt-4 flex justify-end gap-2">
        <Button
          type="button"
          variant="default"
          :disabled="submitting"
          @click="emit('update:open', false)"
        >
          取消
        </Button>
        <Button
          type="button"
          variant="primary"
          data-testid="confirm-enable-ai-bot-btn"
          :disabled="!ackOldBotCleared || submitting || (webhookSet && !deleteWebhook)"
          @click="onConfirm"
        >
          {{ submitting ? '正在启用…' : '确认启用' }}
        </Button>
      </div>
    </div>
  </Sheet>
</template>

<style scoped>
.step-list {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
  color: var(--ink);
}
.step-desc {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--mute);
  line-height: 1.5;
}
.ack-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--ink);
}
</style>
