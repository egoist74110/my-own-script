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
  imported: []
}>()

const services = useServicesContext()
const legacyPath = ref('')

watch(
  () => props.open,
  (val) => {
    if (val) {
      legacyPath.value = ''
      services.legacyImportError.value = null
    }
  },
)

async function onSubmit() {
  if (!legacyPath.value.trim()) return
  const ok = await services.importLegacyPref(legacyPath.value.trim())
  if (ok) {
    emit('imported')
    emit('update:open', false)
  }
}
</script>

<template>
  <Sheet
    :open="open"
    title="从旧应用导入协议偏好"
    description="读取旧应用的 cloudflared_pref.json 中的协议偏好设置。"
    @update:open="emit('update:open', $event)"
  >
    <div class="sheet-body" data-testid="cloudflared-import-sheet">
      <Banner
        v-if="services.legacyImportError.value"
        kind="error"
        class="mb-3"
        data-testid="import-error-banner"
      >
        {{ services.legacyImportError.value }}
      </Banner>

      <Banner kind="info" class="mb-3">
        此操作只读取旧 JSON 配置文件中的协议枚举值（http2 或
        quic），不会修改或删除原文件，也不会影响旧应用。
      </Banner>

      <div class="field-box">
        <label class="field-label" for="legacy-path-input"> 旧配置文件绝对路径 </label>
        <TextField
          id="legacy-path-input"
          v-model="legacyPath"
          label="旧配置文件绝对路径"
          placeholder="/path/to/cloudflared_pref.json"
          data-testid="legacy-import-path-input"
          :disabled="services.legacyImporting.value"
        />
      </div>
    </div>

    <template #actions>
      <Button
        variant="primary"
        data-testid="submit-import-btn"
        :disabled="!legacyPath.trim() || services.legacyImporting.value"
        @click="onSubmit"
      >
        {{ services.legacyImporting.value ? '导入中…' : '导入配置' }}
      </Button>
      <Button
        variant="default"
        data-testid="cancel-import-btn"
        :disabled="services.legacyImporting.value"
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
.mb-3 {
  margin-bottom: 12px;
}
</style>
