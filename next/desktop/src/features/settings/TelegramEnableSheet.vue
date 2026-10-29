<script setup lang="ts">
import { ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'

const props = defineProps<{
  open: boolean
  submitting?: boolean
  webhookSet?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: [opts: { ackOldBotStopped: boolean; deleteWebhook: boolean }]
}>()

const ackOldBotStopped = ref(false)
const confirmDeleteWebhook = ref(false)

watch(
  () => props.open,
  (val) => {
    if (val) {
      ackOldBotStopped.value = false
      confirmDeleteWebhook.value = false
    }
  },
)
</script>

<template>
  <Sheet
    :open="open"
    :title="webhookSet ? '检测到 Webhook，确认接管轮询？' : '启用 Telegram 长轮询接管'"
    description="启用前请仔细阅读并确认所有权切换步骤。"
    @update:open="emit('update:open', $event)"
  >
    <div class="enable-body" data-testid="enable-telegram-dialog">
      <Banner v-if="error" kind="error" class="mb-3" data-testid="enable-error-banner">
        {{ error }}
      </Banner>

      <div class="steps-box">
        <h3 class="steps-title">所有权切换步骤说明：</h3>
        <ol class="steps-list">
          <li>
            <strong>S4 期间使用单独测试 Bot</strong>
            ：建议在开发与真实验收阶段使用独立的测试 Bot，主 Bot 暂留旧版。
          </li>
          <li>
            <strong>切换主 Bot 流程</strong>
            ：先在新版导入 Token，再由用户手动删除旧 Keychain 条目（服务名
            <code>my-own-script</code>，账号 <code>telegram_bot_token</code>）。
            <em class="warn-em">
              请勿在旧版关闭「启用 Telegram 触发任务」开关，以免停掉旧版的三个 AI 机器人。
            </em>
          </li>
          <li>
            <strong>回退方案</strong>
            ：若需回退，只需在新版停用长轮询，并在旧版应用中重新填入 Token 即可恢复。
          </li>
        </ol>
      </div>

      <Banner v-if="webhookSet" kind="warn" class="mb-3" data-testid="webhook-set-banner">
        检测到该 Bot 当前在 Telegram 服务器上已注册 Webhook。Telegram 不允许 Webhook
        与长轮询同时存在。点击确认将调用接口删除已注册的 Webhook 并接管长轮询。
      </Banner>

      <label class="ack-label" data-testid="ack-checkbox-label">
        <input
          v-model="ackOldBotStopped"
          type="checkbox"
          data-testid="ack-old-bot-stopped-checkbox"
          :disabled="submitting"
        />
        <span>我已知晓并确认旧应用主轮询已让出，同意接管此 Bot</span>
      </label>

      <label v-if="webhookSet" class="ack-label mt-2" data-testid="webhook-checkbox-label">
        <input
          v-model="confirmDeleteWebhook"
          type="checkbox"
          data-testid="confirm-delete-webhook-checkbox"
          :disabled="submitting"
        />
        <span>确认删除 Telegram 上已注册的 Webhook</span>
      </label>
    </div>

    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="primary"
        data-testid="confirm-enable-btn"
        :disabled="submitting || !ackOldBotStopped || (webhookSet && !confirmDeleteWebhook)"
        @click="
          emit('confirm', {
            ackOldBotStopped: true,
            deleteWebhook: Boolean(webhookSet && confirmDeleteWebhook),
          })
        "
      >
        {{ submitting ? '启用中…' : webhookSet ? '删除 Webhook 并接管' : '确认启用' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.enable-body {
  font-size: var(--text-body);
  color: var(--ink);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.steps-box {
  background: var(--bg-settings);
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  padding: 12px 14px;
}
.steps-title {
  margin: 0 0 8px;
  font-size: var(--text-body);
  font-weight: 700;
}
.steps-list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.6;
}
.steps-list li {
  margin-bottom: 6px;
}
.warn-em {
  color: var(--st-verify-fg);
  font-style: normal;
  display: block;
  margin-top: 2px;
}
.ack-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}
.mb-3 {
  margin-bottom: 12px;
}
.mt-2 {
  margin-top: 8px;
}
code {
  font-family: var(--font-mono);
  background: var(--field-bg);
  padding: 2px 4px;
  border-radius: 4px;
}
</style>
