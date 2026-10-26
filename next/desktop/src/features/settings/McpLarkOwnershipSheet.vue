<script setup lang="ts">
import { ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'

const props = defineProps<{
  open: boolean
  submitting?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: []
}>()

const ackStopped = ref(false)

watch(
  () => props.open,
  (val) => {
    if (val) {
      ackStopped.value = false
    }
  },
)
</script>

<template>
  <Sheet
    :open="open"
    title="确认接管飞书 / Lark MCP 服务所有权"
    description="请仔细阅读切换步骤并在停止旧应用后勾选确认。"
    @update:open="emit('update:open', $event)"
  >
    <div class="ownership-body" data-testid="mcp-lark-ownership-sheet">
      <Banner v-if="error" kind="error" class="mb-3" data-testid="ownership-error-banner">
        {{ error }}
      </Banner>

      <div class="steps-box">
        <h3 class="steps-title">四步交接步骤说明：</h3>
        <ol class="steps-list">
          <li>
            <strong>前置检查</strong>
            ：确保新端运行组件已安装就绪，并在当前卡片中已导入或录入 App Secret。
          </li>
          <li>
            <strong>停止旧端服务</strong>
            ：在旧应用「MCP配置」页签点击停止 Lark MCP，并确认没有登录流程在进行。
            <em class="warn-em">
              此后切勿在旧应用中点击登录、登出或一键注入，以避免改写共享凭据存储。
            </em>
          </li>
          <li>
            <strong>新端接管确认</strong>
            ：勾选下方承诺并在本确认单点击“确认接管”。随后在新端点击“启动”服务（若遇 409
            端口被占说明旧应用尚未退出，请回到第 2 步）。
          </li>
          <li>
            <strong>客户端验证</strong>
            ：启动后确认补丁全部生效（applied）、令牌状态正常；使用任一已授权的 CLI 调用验证（URL
            未变，客户端无需修改）。
          </li>
        </ol>
      </div>

      <Banner kind="info" class="mb-2">
        注意：首次访问钥匙串时 macOS 可能弹出授权提示，属于正常权限确认。
      </Banner>

      <div class="check-box">
        <label class="check-label">
          <input
            v-model="ackStopped"
            type="checkbox"
            data-testid="ack-old-app-stopped-checkbox"
            :disabled="submitting"
          />
          <span>旧应用已停止且不再在旧应用登录/登出</span>
        </label>
      </div>
    </div>

    <template #actions>
      <Button
        variant="primary"
        data-testid="confirm-ownership-btn"
        :disabled="!ackStopped || submitting"
        @click="emit('confirm')"
      >
        {{ submitting ? '确认中…' : '确认接管所有权' }}
      </Button>
      <Button
        variant="default"
        data-testid="cancel-ownership-btn"
        :disabled="submitting"
        @click="emit('update:open', false)"
      >
        取消
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.ownership-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.steps-box {
  background: var(--bg-settings);
  padding: 10px 14px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
}
.steps-title {
  margin: 0 0 6px 0;
  font-size: var(--text-body);
  font-weight: 600;
}
.steps-list {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--text-sub);
  line-height: 1.5;
  color: var(--mute);
}
.steps-list strong {
  color: var(--text);
}
.warn-em {
  color: var(--st-verify-fg);
  font-style: normal;
  display: block;
  margin-top: 2px;
}
.check-box {
  padding: 4px 2px;
}
.check-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-body);
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}
.mb-2 {
  margin-bottom: 4px;
}
.mb-3 {
  margin-bottom: 8px;
}
</style>
