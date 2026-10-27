<script setup lang="ts">
import { ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import { useVpnContext, type TotpCandidate } from './useVpn'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  imported: []
}>()

const vpn = useVpnContext()

const totpText = ref('')
const selectedFile = ref<File | null>(null)
const candidates = ref<TotpCandidate[]>([])
const selectedIndex = ref<number | null>(null)
const localError = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

watch(
  () => props.open,
  (val) => {
    if (val) {
      resetState()
    }
  },
)

function resetState() {
  totpText.value = ''
  selectedFile.value = null
  candidates.value = []
  selectedIndex.value = null
  localError.value = null
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

function onFileSelect(ev: Event) {
  const target = ev.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  if (file.size > 1024 * 1024) {
    localError.value = '文件大小超过 1 MiB 上限'
    return
  }

  selectedFile.value = file
  localError.value = null

  // 纯前端内存读取，绝不传递路径给后端
  const reader = new FileReader()
  reader.onload = (e) => {
    const text = e.target?.result
    if (typeof text === 'string') {
      totpText.value = text
    }
  }
  reader.onerror = () => {
    localError.value = '读取文件失败'
  }
  reader.readAsText(file)
}

async function onSubmit() {
  const text = totpText.value.trim()
  if (!text) {
    localError.value = '请输入或选择 TOTP 导出文本'
    return
  }

  localError.value = null
  try {
    const res = await vpn.importTotp(
      text,
      selectedIndex.value !== null ? selectedIndex.value : undefined,
    )
    if (res.ambiguous && res.items && res.items.length > 0) {
      candidates.value = res.items
      selectedIndex.value = res.items[0]?.index ?? 0
      return
    }

    resetState()
    emit('imported')
    emit('update:open', false)
  } catch (e: unknown) {
    localError.value = e instanceof Error ? e.message : '导入失败'
  }
}

function onCancel() {
  resetState()
  emit('update:open', false)
}
</script>

<template>
  <Sheet
    :open="open"
    title="导入 TOTP 种子"
    description="支持 Ente Auth / 2FA 导出文本或 otpauth:// 格式种子。纯内存解析，不落盘。"
    @update:open="emit('update:open', $event)"
  >
    <div class="sheet-body" data-testid="vpn-totp-import-sheet">
      <Banner
        v-if="localError || vpn.error.value"
        kind="error"
        class="mb-3"
        data-testid="totp-import-error"
      >
        {{ localError || vpn.error.value }}
      </Banner>

      <Banner kind="info" class="mb-3">
        种子写入 macOS Keychain
        后将从内存中彻底销毁。导入成功后<strong>请自行删除导出文件</strong>。
      </Banner>

      <!-- 多匹配待选列表 -->
      <div
        v-if="candidates.length > 0"
        class="candidate-box"
        data-testid="totp-candidates-container"
      >
        <div class="field-label">检测到多个 TOTP 项目，请选择要导入的一项：</div>
        <div class="candidate-list">
          <label
            v-for="item in candidates"
            :key="item.index"
            class="candidate-item"
            :class="{ active: selectedIndex === item.index }"
          >
            <input
              type="radio"
              name="totp-candidate"
              :value="item.index"
              :checked="selectedIndex === item.index"
              data-testid="totp-candidate-radio"
              @change="selectedIndex = item.index"
            />
            <div class="candidate-info">
              <span class="candidate-label">{{ item.label }}</span>
              <span v-if="item.issuer" class="candidate-issuer">（{{ item.issuer }}）</span>
            </div>
          </label>
        </div>
      </div>

      <!-- 文本输入与文件选择模式 -->
      <template v-else>
        <div class="field-box">
          <label class="field-label" for="totp-text-input">粘贴导出内容或 otpauth:// URI</label>
          <textarea
            id="totp-text-input"
            v-model="totpText"
            rows="5"
            class="totp-textarea"
            placeholder="粘贴 otpauth://totp/... 链接或从认证器导出的纯文本/JSON 内容"
            data-testid="totp-text-input"
          />
        </div>

        <div class="field-box">
          <label class="field-label">或选择本地导出文件（纯前端读入内存）</label>
          <div class="file-picker-row">
            <input
              ref="fileInput"
              type="file"
              class="file-input"
              data-testid="totp-file-input"
              accept=".txt,.json,.uri"
              @change="onFileSelect"
            />
            <span v-if="selectedFile" class="file-chosen-name" data-testid="chosen-file-name">
              已选: {{ selectedFile.name }} ({{ selectedFile.size }} 字节)
            </span>
          </div>
        </div>
      </template>
    </div>

    <template #actions>
      <Button
        variant="primary"
        data-testid="submit-totp-import-btn"
        :disabled="!totpText.trim() || vpn.actionLoading.value === 'import_totp'"
        @click="onSubmit"
      >
        {{
          vpn.actionLoading.value === 'import_totp'
            ? '导入中…'
            : candidates.length > 0
              ? '导入所选条目'
              : '导入种子'
        }}
      </Button>
      <Button
        variant="default"
        data-testid="cancel-totp-import-btn"
        :disabled="vpn.actionLoading.value === 'import_totp'"
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
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--fg);
}
.totp-textarea {
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--r-ctl, 6px);
  border: 1px solid var(--line);
  background: var(--bg-ctl, #fff);
  color: var(--fg);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-sub, 12px);
  resize: vertical;
}
.totp-textarea:focus {
  outline: none;
  border-color: var(--accent);
}
.file-picker-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.file-chosen-name {
  font-size: var(--text-sub, 12px);
  color: var(--mute);
}
.candidate-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.candidate-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl, 6px);
  padding: 8px;
}
.candidate-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
}
.candidate-item:hover {
  background: var(--bg-hover, rgba(0, 0, 0, 0.04));
}
.candidate-item.active {
  background: var(--bg-active, rgba(0, 100, 255, 0.08));
}
.candidate-label {
  font-weight: 500;
  font-size: var(--text-base);
}
.candidate-issuer {
  font-size: var(--text-sub);
  color: var(--mute);
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
