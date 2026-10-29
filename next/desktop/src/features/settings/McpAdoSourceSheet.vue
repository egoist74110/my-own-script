<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'

const props = defineProps<{
  open: boolean
  currentSource: 'legacy' | 'toolbox'
  submitting?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: [opts: { source: 'legacy' | 'toolbox'; ackCliRegistered: boolean }]
}>()

const ackRegistered = ref(false)

const isSwitchingToToolbox = computed(() => props.currentSource === 'legacy')
const targetSource = computed<'legacy' | 'toolbox'>(() =>
  isSwitchingToToolbox.value ? 'toolbox' : 'legacy',
)

watch(
  () => props.open,
  (val) => {
    if (val) {
      ackRegistered.value = false
    }
  },
)

const canSubmit = computed(() => {
  if (isSwitchingToToolbox.value) {
    return ackRegistered.value && !props.submitting
  }
  return !props.submitting
})

function onConfirm() {
  if (!canSubmit.value) return
  emit('confirm', {
    source: targetSource.value,
    ackCliRegistered: isSwitchingToToolbox.value ? ackRegistered.value : false,
  })
}
</script>

<template>
  <Sheet
    :open="open"
    :title="isSwitchingToToolbox ? '工单分析改用新版 ADO 工单 MCP' : '切回旧版工单 MCP 来源'"
    description="先在各 CLI 里完成注册并自检，再切换；有问题可以随时切回旧版。"
    @update:open="emit('update:open', $event)"
  >
    <div class="source-body" data-testid="mcp-source-sheet">
      <Banner v-if="error" kind="error" class="mb-3" data-testid="source-error-banner">
        {{ error }}
      </Banner>

      <div class="steps-box">
        <h3 class="steps-title">切换步骤说明：</h3>
        <ol class="steps-list">
          <li>
            <strong>在各 CLI 中完成注册</strong>
            ：复制 ADO 工单分组里的接入配置，在 Claude Code、Codex 或 Antigravity CLI 中完成
            <code>toolbox_ado</code> 注册。
          </li>
          <li>
            <strong>自检验证</strong>
            ：在桌面端点击“运行自检”，确认能够正常握手并列出工单工具。
          </li>
          <li>
            <strong>确认勾选注册</strong>
            ：确认正在使用的各个 CLI 都已注册新版 MCP 后，才能切换。
          </li>
          <li>
            <strong>自动前缀适配</strong>
            ：切换后，分析提示词里的工具前缀会改用
            <code>mcp__toolbox_ado__</code> ，并去掉新版专有的项目提示。
          </li>
          <li>
            <strong>验证与回退</strong>
            ：在工单详情中发起一次工单 AI 分析验证。如遇问题，可随时一键切回旧版。
          </li>
        </ol>
      </div>

      <div v-if="isSwitchingToToolbox" class="check-box">
        <label class="check-label">
          <input
            v-model="ackRegistered"
            type="checkbox"
            data-testid="ack-cli-registered-checkbox"
            :disabled="submitting"
          />
          <span>我已在 Claude / Codex / agy 中完成 <code>toolbox_ado</code> 注册并自检通过</span>
        </label>
      </div>
      <div v-else class="check-box">
        <p class="st-note">
          切回旧版后，AI 分析将恢复使用旧版 MCP 注册名（如 <code>mcp__ado-work-items__</code>）。
        </p>
      </div>
    </div>

    <template #actions>
      <Button
        variant="primary"
        data-testid="confirm-switch-source-btn"
        :disabled="!canSubmit"
        @click="onConfirm"
      >
        {{ submitting ? '切换中…' : isSwitchingToToolbox ? '确认改用新版' : '切回旧版' }}
      </Button>
      <Button
        variant="default"
        data-testid="cancel-switch-source-btn"
        :disabled="submitting"
        @click="emit('update:open', false)"
      >
        取消
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.source-body {
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
  color: var(--ink);
}
.check-box {
  padding: 4px 2px;
}
.check-label {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: var(--text-body);
  cursor: pointer;
  user-select: none;
}
.check-label input {
  margin-top: 3px;
}
.mb-3 {
  margin-bottom: 8px;
}
</style>
