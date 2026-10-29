<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import TextField from '@/components/TextField.vue'
import { useVpnContext } from './useVpn'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  submitted: []
}>()

const vpn = useVpnContext()
const code = ref('')
const localError = ref<string | null>(null)

watch(
  () => props.open,
  (val) => {
    if (val) {
      code.value = ''
      localError.value = null
    }
  },
)

const isCodeValid = computed(() => /^[0-9]{6}$/.test(code.value.trim()))
const isExpired = computed(() => vpn.mfaSecondsLeft.value <= 0)

async function onSubmit() {
  if (!isCodeValid.value || isExpired.value) return

  localError.value = null
  const codeVal = code.value.trim()
  code.value = '' // 提交时立即清空内存

  const ok = await vpn.submitMfa(codeVal)
  if (ok) {
    emit('submitted')
    emit('update:open', false)
  } else {
    localError.value = vpn.mfaError.value || '提交验证码失败'
  }
}

function onCancel() {
  code.value = ''
  vpn.closeMfa()
  emit('update:open', false)
}
</script>

<template>
  <Sheet
    :open="open"
    title="输入 MFA 动态验证码"
    description="VPN 登录流程需要多因素认证（MFA），请输入身份验证器上的 6 位数字。"
    @update:open="emit('update:open', $event)"
  >
    <div class="sheet-body" data-testid="vpn-mfa-sheet">
      <Banner
        v-if="localError || vpn.mfaError.value"
        kind="error"
        class="mb-3"
        data-testid="mfa-error-banner"
      >
        {{ localError || vpn.mfaError.value }}
      </Banner>

      <div class="countdown-bar" :class="{ warning: vpn.mfaSecondsLeft.value < 30 }">
        <span class="countdown-text">
          验证码有效倒计时：<strong data-testid="mfa-countdown">{{
            vpn.mfaSecondsLeft.value
          }}</strong>
          秒
        </span>
      </div>

      <div class="field-box">
        <label class="field-label" for="mfa-code-input">6 位数字验证码</label>
        <TextField
          id="mfa-code-input"
          v-model="code"
          label="6 位数字验证码"
          placeholder="例如 123456"
          data-testid="mfa-code-input"
          :maxlength="6"
          :disabled="isExpired || vpn.actionLoading.value === 'mfa'"
          @keydown.enter="onSubmit"
        />
      </div>

      <Banner kind="info"> 动态口令仅在内存中处理并提交至 SSO 流程，不落盘、不进日志。 </Banner>
    </div>

    <template #actions>
      <Button
        variant="primary"
        data-testid="submit-mfa-btn"
        :disabled="!isCodeValid || isExpired || vpn.actionLoading.value === 'mfa'"
        @click="onSubmit"
      >
        {{ vpn.actionLoading.value === 'mfa' ? '提交中…' : '确认提交' }}
      </Button>
      <Button
        variant="default"
        data-testid="cancel-mfa-btn"
        :disabled="vpn.actionLoading.value === 'mfa'"
        @click="onCancel"
      >
        取消
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.sheet-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.field-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: var(--text-body);
  font-weight: 500;
  color: var(--ink);
}
.countdown-bar {
  padding: 8px 12px;
  background: var(--ctl);
  border-radius: var(--r-ctl);
  font-size: var(--text-body);
  color: var(--ink);
}
.countdown-bar.warning {
  background: rgba(255, 150, 0, 0.1);
  color: #d97706;
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
