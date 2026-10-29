<script setup lang="ts">
import { ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import TextField from '@/components/TextField.vue'
import { useServicesContext } from './useServices'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  created: []
}>()

const services = useServicesContext()

const targetUrl = ref('http://127.0.0.1:3000')
const ackPublic = ref(false)

watch(
  () => props.open,
  (val) => {
    if (val) {
      ackPublic.value = false
      targetUrl.value = 'http://127.0.0.1:3000'
      services.tunnelCreateError.value = null
    }
  },
)

async function onSubmit() {
  if (!ackPublic.value || !targetUrl.value.trim()) return
  const ok = await services.createCustomTunnel(targetUrl.value.trim(), true)
  if (ok) {
    emit('created')
    emit('update:open', false)
  }
}
</script>

<template>
  <Sheet
    :open="open"
    title="添加自定义 Quick 隧道"
    description="将本机回环端口通过 Cloudflare 临时隧道暴露为公网访问地址。"
    @update:open="emit('update:open', $event)"
  >
    <div class="sheet-body" data-testid="cloudflared-tunnel-sheet">
      <Banner
        v-if="services.tunnelCreateError.value"
        kind="error"
        class="mb-3"
        data-testid="tunnel-error-banner"
      >
        {{ services.tunnelCreateError.value }}
      </Banner>

      <div class="field-box">
        <label class="field-label" for="tunnel-target-input">
          目标 URL
          <span class="hint-text">（需携带显式端口，仅支持 localhost / 127.0.0.1 / [::1]）</span>
        </label>
        <TextField
          id="tunnel-target-input"
          v-model="targetUrl"
          label="目标 URL"
          placeholder="http://127.0.0.1:3000"
          data-testid="tunnel-target-url-input"
          :disabled="services.tunnelCreating.value"
        />
      </div>

      <Banner kind="warn" class="mb-3">
        安全提醒：Cloudflare Quick
        隧道将直接为公网生成可访问域名。若目标服务自身无认证保护，互联网上的任何人均可直接访问。
      </Banner>

      <div class="check-box">
        <label class="check-label">
          <input
            v-model="ackPublic"
            type="checkbox"
            data-testid="ack-public-checkbox"
            :disabled="services.tunnelCreating.value"
          />
          <span>该地址将可被公网任何人访问，隧道本身无认证</span>
        </label>
      </div>
    </div>

    <template #actions>
      <Button
        variant="primary"
        data-testid="submit-tunnel-btn"
        :disabled="!ackPublic || !targetUrl.trim() || services.tunnelCreating.value"
        @click="onSubmit"
      >
        {{ services.tunnelCreating.value ? '创建中…' : '创建隧道' }}
      </Button>
      <Button
        variant="default"
        data-testid="cancel-tunnel-btn"
        :disabled="services.tunnelCreating.value"
        @click="emit('update:open', false)"
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
.hint-text {
  font-size: var(--text-sub);
  color: var(--mute);
  font-weight: normal;
}
.check-box {
  padding: 10px 12px;
  background: var(--bg-sub);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.check-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-body);
  cursor: pointer;
  color: var(--ink);
  font-weight: 500;
}
.check-label input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
