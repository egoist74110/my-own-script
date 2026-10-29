<script setup lang="ts">
import { ref } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import { useVpnContext } from './useVpn'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  imported: []
}>()

const vpn = useVpnContext()
const importPassword = ref(true)
const importTotp = ref(true)
const importFields = ref(true)
const localError = ref<string | null>(null)

async function onSubmit() {
  const kinds: ('vpn_password' | 'vpn_totp_secret')[] = []
  if (importPassword.value) kinds.push('vpn_password')
  if (importTotp.value) kinds.push('vpn_totp_secret')

  if (kinds.length === 0 && !importFields.value) {
    localError.value = '请至少选择一项要导入的内容'
    return
  }

  localError.value = null
  const ok = await vpn.importLegacy(kinds, importFields.value)
  if (ok) {
    emit('imported')
    emit('update:open', false)
  } else {
    localError.value = vpn.error.value || '旧应用导入失败'
  }
}
</script>

<template>
  <Sheet
    :open="open"
    title="从旧应用导入 VPN 配置与凭据"
    description="只读读取旧应用 Keychain 与配置项（workspace, residency, email, totp_filter），不修改或删除旧应用数据。"
    @update:open="emit('update:open', $event)"
  >
    <div class="sheet-body" data-testid="vpn-legacy-import-sheet">
      <Banner
        v-if="localError || vpn.error.value"
        kind="error"
        class="mb-3"
        data-testid="legacy-import-error"
      >
        {{ localError || vpn.error.value }}
      </Banner>

      <div class="options-box">
        <label class="option-label">
          <input
            v-model="importPassword"
            type="checkbox"
            data-testid="import-password-checkbox"
            :disabled="vpn.actionLoading.value === 'import_legacy'"
          />
          <span>导入 VPN 密码（写入 toolbox-next Keychain）</span>
        </label>

        <label class="option-label">
          <input
            v-model="importTotp"
            type="checkbox"
            data-testid="import-totp-checkbox"
            :disabled="vpn.actionLoading.value === 'import_legacy'"
          />
          <span>导入 TOTP 种子密钥（写入 toolbox-next Keychain）</span>
        </label>

        <label class="option-label">
          <input
            v-model="importFields"
            type="checkbox"
            data-testid="import-fields-checkbox"
            :disabled="vpn.actionLoading.value === 'import_legacy'"
          />
          <span>导入 Workspace、Residency、Email 与 TOTP Filter 配置</span>
        </label>
      </div>

      <Banner kind="info"> 此操作为单向只读导入。旧应用的任何条目均不受影响。 </Banner>
    </div>

    <template #actions>
      <Button
        variant="primary"
        data-testid="submit-legacy-import-btn"
        :disabled="
          (!importPassword && !importTotp && !importFields) ||
          vpn.actionLoading.value === 'import_legacy'
        "
        @click="onSubmit"
      >
        {{ vpn.actionLoading.value === 'import_legacy' ? '导入中…' : '开始导入' }}
      </Button>
      <Button
        variant="default"
        data-testid="cancel-legacy-import-btn"
        :disabled="vpn.actionLoading.value === 'import_legacy'"
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
.options-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 12px;
  background: var(--ctl);
  border-radius: var(--r-ctl);
}
.option-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-body);
  color: var(--ink);
  cursor: pointer;
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
