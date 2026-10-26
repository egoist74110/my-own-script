<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import Tag from '@/components/Tag.vue'
import type { AdoMcp, ClientConfig, SelfTestResult } from './api'
import { MCP_ERROR_MESSAGES } from './api'
import McpAdoSourceSheet from './McpAdoSourceSheet.vue'
import McpAdoWriteConfirmSheet from './McpAdoWriteConfirmSheet.vue'
import { useMcpContext } from './useMcp'

const props = defineProps<{
  ado: AdoMcp
  aiMcpSource?: 'legacy' | 'toolbox'
  busy?: boolean
  writable?: boolean
}>()

const mcp = useMcpContext()

// --- 自检 ---
const selfTestResult = computed<SelfTestResult | null>(() => mcp.adoTestResult.value)
const isTesting = computed(() => mcp.adoTesting.value)
const testError = computed(() => mcp.adoError.value)

async function onSelfTest() {
  await mcp.runAdoSelfTest(15)
}

// --- 写工具开关二次确认 ---
const writeConfirmOpen = ref(false)
const writeSubmitting = ref(false)

async function onToggleWriteTool(checked: boolean) {
  if (checked) {
    writeConfirmOpen.value = true
  } else {
    await mcp.updateAdoSettings({
      ...props.ado,
      allow_create_work_item: false,
    })
  }
}

async function onConfirmEnableWrite() {
  writeSubmitting.value = true
  try {
    const ok = await mcp.updateAdoSettings({
      ...props.ado,
      allow_create_work_item: true,
    })
    if (ok) {
      writeConfirmOpen.value = false
    }
  } finally {
    writeSubmitting.value = false
  }
}

function onCancelEnableWrite() {
  writeConfirmOpen.value = false
}

// --- 接入片段复制 ---
const cliOptions = [
  { value: 'claude', label: 'Claude Code' },
  { value: 'codex', label: 'Codex' },
  { value: 'agy', label: 'Antigravity (agy)' },
]
const selectedCli = ref<'claude' | 'codex' | 'agy'>('claude')
const clientConfig = ref<ClientConfig | null>(null)
const snippetCopied = ref(false)

async function loadClientConfig(cli: 'claude' | 'codex' | 'agy') {
  clientConfig.value = await mcp.fetchClientConfig('ado', cli)
}

watch(
  selectedCli,
  (cli) => {
    void loadClientConfig(cli)
  },
  { immediate: true },
)

async function onCopySnippet() {
  if (!clientConfig.value?.snippet) return
  try {
    await navigator.clipboard.writeText(clientConfig.value.snippet)
    snippetCopied.value = true
    setTimeout(() => {
      snippetCopied.value = false
    }, 2000)
  } catch {
    // 忽略剪贴板写入异常
  }
}

// --- 分析来源切换 Sheet ---
const sourceSheetOpen = ref(false)
const sourceSubmitting = ref(false)
const sourceError = ref<string | null>(null)

function onOpenSourceSheet() {
  sourceError.value = null
  sourceSheetOpen.value = true
}

async function onConfirmSourceSwitch(opts: {
  source: 'legacy' | 'toolbox'
  ackCliRegistered: boolean
}) {
  sourceSubmitting.value = true
  sourceError.value = null
  try {
    const ok = await mcp.switchAnalysisSource(opts.source, opts.ackCliRegistered)
    if (ok) {
      sourceSheetOpen.value = false
    } else {
      sourceError.value = '切换分析来源失败，请重试'
    }
  } catch (e: unknown) {
    sourceError.value = e instanceof Error ? e.message : String(e)
  } finally {
    sourceSubmitting.value = false
  }
}
</script>

<template>
  <section class="st-section" aria-label="ADO 工单 MCP" data-testid="mcp-ado-card">
    <div class="st-head">
      <h2>ADO 工单 MCP</h2>
      <Tag>stdio 模式</Tag>
      <div class="st-grow"></div>
      <Button
        variant="default"
        data-testid="mcp-ado-selftest-btn"
        :disabled="isTesting || busy || !writable"
        @click="onSelfTest"
      >
        {{ isTesting ? '自检中…' : '运行自检' }}
      </Button>
    </div>
    <p class="st-note">
      通过 stdio 协议由各 AI CLI 会话按需拉起，无常驻进程。凭据每次调用从钥匙串读取。
    </p>

    <!-- 自检错误或失败展示 -->
    <Banner v-if="testError" kind="error" data-testid="ado-test-error-banner">
      {{ testError }}
    </Banner>

    <div v-if="selfTestResult" class="test-result-box" data-testid="ado-selftest-result">
      <div class="test-result-header">
        <span class="lbl">自检状态：</span>
        <span
          class="test-status-badge"
          :class="selfTestResult.ok ? 'st-ok' : 'st-warn'"
          data-testid="ado-selftest-status"
        >
          {{ selfTestResult.ok ? '握手成功' : '自检失败' }}
        </span>
        <span v-if="selfTestResult.duration_ms" class="st-mono mute">
          ({{ selfTestResult.duration_ms }} ms)
        </span>
        <span v-if="selfTestResult.protocol_version" class="st-mono mute">
          协议: {{ selfTestResult.protocol_version }}
        </span>
      </div>

      <div v-if="selfTestResult.tools?.length" class="test-tools-row">
        <span class="lbl">暴露工具：</span>
        <div class="st-tags" data-testid="ado-selftest-tools">
          <Tag v-for="t in selfTestResult.tools" :key="t">{{ t }}</Tag>
        </div>
      </div>

      <div v-if="selfTestResult.error_code" class="test-error-row">
        <span class="lbl">错误码：</span>
        <span class="st-warn" data-testid="ado-selftest-error-code">
          {{ MCP_ERROR_MESSAGES[selfTestResult.error_code] ?? selfTestResult.error_code }}
        </span>
      </div>

      <div v-if="selfTestResult.stderr_tail" class="test-stderr-row">
        <span class="lbl">错误输出：</span>
        <pre class="st-mono stderr-box" data-testid="ado-selftest-stderr">{{
          selfTestResult.stderr_tail
        }}</pre>
      </div>
    </div>

    <hr class="st-sep" />

    <!-- 写工具开关 -->
    <div class="setting-row">
      <div class="setting-info">
        <strong class="setting-title">写工具 (ado_create_work_item)</strong>
        <p class="st-note">
          允许 AI 在工单分析或会话中直接创建新工单。默认关闭，开启时 AI 可调用建单工具。
        </p>
      </div>
      <Switch
        :model-value="Boolean(ado.allow_create_work_item)"
        data-testid="ado-allow-create-work-item-switch"
        :disabled="busy || !writable"
        @update:model-value="onToggleWriteTool"
      />
    </div>

    <hr class="st-sep" />

    <!-- 附件缓存说明 -->
    <div class="setting-row">
      <div class="setting-info">
        <strong class="setting-title">附件缓存与用量</strong>
        <p class="st-note">
          总量上限 {{ ado.attachment_cache_mb }} MB · 单文件上限
          {{ ado.attachment_max_mb }} MB。遵循 LRU 及 14 天自动过期规则。
        </p>
      </div>
      <div class="setting-action">
        <span class="mute st-note" data-testid="ado-attachment-cache-hint">暂无清空接口</span>
      </div>
    </div>

    <hr class="st-sep" />

    <!-- 分析来源切换 -->
    <div class="setting-row">
      <div class="setting-info">
        <strong class="setting-title">工单 AI 分析 MCP 来源</strong>
        <p class="st-note">
          当前来源：
          <strong data-testid="ado-current-mcp-source">
            {{ aiMcpSource === 'toolbox' ? '新端 ADO MCP (toolbox_ado)' : '旧版工单 MCP (默认)' }}
          </strong>
        </p>
      </div>
      <div class="setting-action">
        <Button
          variant="default"
          data-testid="open-source-sheet-btn"
          :disabled="busy || !writable"
          @click="onOpenSourceSheet"
        >
          切换分析来源
        </Button>
      </div>
    </div>

    <hr class="st-sep" />

    <!-- 接入片段复制 -->
    <div class="snippet-section">
      <div class="snippet-header">
        <strong class="setting-title">CLI 接入片段（无凭据）</strong>
        <div class="st-grow"></div>
        <Button
          variant="plain"
          size="sm"
          data-testid="copy-ado-snippet-btn"
          :disabled="!clientConfig?.snippet"
          @click="onCopySnippet"
        >
          {{ snippetCopied ? '已复制！' : '复制片段' }}
        </Button>
      </div>
      <SegmentedControl
        v-model="selectedCli"
        :items="cliOptions"
        label="选择 CLI"
        data-testid="ado-cli-segmented"
        class="cli-seg"
      />
      <pre class="st-mono snippet-box" data-testid="ado-snippet-box">{{
        clientConfig?.snippet || '加载片段中…'
      }}</pre>
    </div>

    <!-- 写工具二次确认 Sheet -->
    <McpAdoWriteConfirmSheet
      :open="writeConfirmOpen"
      :submitting="writeSubmitting"
      @confirm="onConfirmEnableWrite"
      @cancel="onCancelEnableWrite"
      @update:open="writeConfirmOpen = $event"
    />

    <!-- 分析来源切换 Sheet -->
    <McpAdoSourceSheet
      :open="sourceSheetOpen"
      :current-source="aiMcpSource ?? 'legacy'"
      :submitting="sourceSubmitting"
      :error="sourceError"
      @confirm="onConfirmSourceSwitch"
      @update:open="sourceSheetOpen = $event"
    />
  </section>
</template>

<style scoped>
.test-result-box {
  background: var(--bg-settings);
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.test-result-header,
.test-tools-row,
.test-error-row,
.test-stderr-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-body);
}
.test-stderr-row {
  align-items: flex-start;
  flex-direction: column;
}
.lbl {
  color: var(--mute);
  font-size: var(--text-sub);
}
.mute {
  color: var(--mute);
}
.stderr-box {
  width: 100%;
  margin: 4px 0 0;
  padding: 8px 10px;
  background: var(--bg-window);
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
}
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.setting-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.setting-title {
  font-size: var(--text-body);
}
.snippet-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.snippet-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cli-seg {
  align-self: flex-start;
}
.snippet-box {
  margin: 0;
  padding: 10px 12px;
  background: var(--bg-settings);
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  max-height: 160px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
