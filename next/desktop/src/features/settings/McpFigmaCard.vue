<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import type { ClientConfig, FigmaMcpView, SelfTestResult } from './api'
import { MCP_ERROR_MESSAGES } from './api'
import { useMcp } from './useMcp'

const props = defineProps<{
  figma?: FigmaMcpView
  busy?: boolean
  writable?: boolean
}>()

const mcp = useMcp()

const fg = computed(() => props.figma)

// --- 自检 ---
const selfTestResult = computed<SelfTestResult | null>(() => mcp.figmaTestResult.value)
const isTesting = computed(() => mcp.figmaTesting.value)
const testError = computed(() => mcp.figmaError.value)

async function onSelfTest() {
  await mcp.runFigmaSelfTest(15)
}

// --- Token 管理（只写不读回，提交后立即清空局部变量） ---
const inputToken = ref('')
const selectedExpiryDays = ref<1 | 7 | 30 | 90>(fg.value?.expiry_days ?? 90)
const tokenSubmitting = ref(false)

const expiryOptions = [
  { value: 1, label: '1 天' },
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
]

async function onSaveToken() {
  if (!inputToken.value) return
  tokenSubmitting.value = true
  const tokenVal = inputToken.value
  try {
    await mcp.saveFigmaToken(tokenVal, selectedExpiryDays.value)
  } finally {
    // 立即清空，不留凭据
    inputToken.value = ''
    tokenSubmitting.value = false
  }
}

async function onDeleteToken() {
  await mcp.deleteFigmaToken()
}

async function onImportLegacyToken() {
  await mcp.importLegacyFigmaToken()
}

// --- 到期天数与到期提醒计算 ---
const daysRemaining = computed<number | null>(() => {
  if (!fg.value?.token_set_at || !fg.value.token_configured) return null
  const setAt = Date.parse(fg.value.token_set_at)
  if (Number.isNaN(setAt)) return null
  const expiryDays = fg.value.expiry_days || 90
  const elapsedDays = Math.floor((Date.now() - setAt) / (1000 * 60 * 60 * 24))
  return Math.max(0, expiryDays - elapsedDays)
})

const isExpired = computed(() => daysRemaining.value !== null && daysRemaining.value <= 0)
const isExpiringSoon = computed(
  () => daysRemaining.value !== null && daysRemaining.value > 0 && daysRemaining.value <= 7,
)

// --- 限流参数编辑 ---
const editConcurrency = ref(String(fg.value?.max_concurrency ?? 1))
const editInterval = ref(String(fg.value?.min_interval_ms ?? 350))
const editRetry = ref(String(fg.value?.max_retry ?? 4))
const rateLimitSubmitting = ref(false)
const rateLimitMessage = ref<string | null>(null)

watch(
  () => fg.value,
  (newVal) => {
    if (!newVal || rateLimitSubmitting.value) return
    editConcurrency.value = String(newVal.max_concurrency)
    editInterval.value = String(newVal.min_interval_ms)
    editRetry.value = String(newVal.max_retry)
    selectedExpiryDays.value = newVal.expiry_days
  },
  { immediate: true },
)

async function onSaveRateLimits() {
  if (!fg.value) return
  rateLimitSubmitting.value = true
  rateLimitMessage.value = null
  try {
    const ok = await mcp.updateFigmaSettings({
      max_concurrency: Number(editConcurrency.value) || 1,
      min_interval_ms: Number(editInterval.value) || 350,
      max_retry: Number(editRetry.value) || 4,
      expiry_days: fg.value.expiry_days,
      token_set_at: fg.value.token_set_at,
    })
    if (ok) {
      rateLimitMessage.value = '已保存限流参数'
      setTimeout(() => {
        rateLimitMessage.value = null
      }, 2000)
    }
  } finally {
    rateLimitSubmitting.value = false
  }
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
  clientConfig.value = await mcp.fetchClientConfig('figma', cli)
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
</script>

<template>
  <section class="st-section" aria-label="Figma MCP" data-testid="mcp-figma-card">
    <div class="st-head">
      <h2>Figma MCP</h2>
      <Tag>stdio Wrapper</Tag>
      <div class="st-grow"></div>
      <Button
        variant="default"
        data-testid="mcp-figma-selftest-btn"
        :disabled="isTesting || !fg?.token_configured || busy || !writable"
        @click="onSelfTest"
      >
        {{ isTesting ? '自检中…' : '运行自检' }}
      </Button>
    </div>
    <p class="st-note">
      通过 Python wrapper 注入限流与脱敏监督，拉起 figma-developer-mcp stdio 协议。已默认禁用
      PostHog 遥测。
    </p>

    <!-- 自检错误展示 -->
    <Banner v-if="testError" kind="error" data-testid="figma-test-error-banner">
      {{ testError }}
    </Banner>

    <!-- 自检结果展示 -->
    <div v-if="selfTestResult" class="test-result-box" data-testid="figma-selftest-result">
      <div class="test-result-header">
        <span class="lbl">自检状态：</span>
        <span
          class="test-status-badge"
          :class="selfTestResult.ok ? 'st-ok' : 'st-warn'"
          data-testid="figma-selftest-status"
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
        <div class="st-tags" data-testid="figma-selftest-tools">
          <Tag v-for="t in selfTestResult.tools" :key="t">{{ t }}</Tag>
        </div>
      </div>

      <div v-if="selfTestResult.error_code" class="test-error-row">
        <span class="lbl">错误码：</span>
        <span class="st-warn" data-testid="figma-selftest-error-code">
          {{ MCP_ERROR_MESSAGES[selfTestResult.error_code] ?? selfTestResult.error_code }}
        </span>
      </div>

      <div v-if="selfTestResult.stderr_tail" class="test-stderr-row">
        <span class="lbl">错误输出：</span>
        <pre class="st-mono stderr-box" data-testid="figma-selftest-stderr">{{
          selfTestResult.stderr_tail
        }}</pre>
      </div>
    </div>

    <!-- 到期提醒 Banner -->
    <Banner v-if="isExpired" kind="error" data-testid="figma-token-expired-banner">
      Figma Personal Access Token 已过期，请生成新 Token 并在此替换保存。
    </Banner>
    <Banner v-else-if="isExpiringSoon" kind="warn" data-testid="figma-token-expiring-banner">
      Figma Token 即将在 {{ daysRemaining }} 天后到期，请提前更新。
    </Banner>

    <hr class="st-sep" />

    <!-- Token 管理（只写不读回） -->
    <div class="cred-section">
      <strong class="setting-title">Token 管理 (Personal Access Token)</strong>
      <p class="st-note">
        钥匙串中只写不读回。当前状态：
        <strong data-testid="figma-token-configured-status">
          {{ fg?.token_configured ? '已配置' : '未配置' }}
        </strong>
        <template v-if="fg?.token_set_at">
          · 设置于 {{ fg.token_set_at.slice(0, 10) }} · 有效期 {{ fg.expiry_days }} 天
          <template v-if="daysRemaining !== null">
            (剩余 <strong :class="isExpiringSoon ? 'st-warn' : ''">{{ daysRemaining }}</strong> 天)
          </template>
        </template>
      </p>

      <div class="cred-input-row">
        <TextField
          v-model="inputToken"
          type="password"
          autocomplete="off"
          label="Figma Token"
          placeholder="粘贴新的 Figma Token (figd_...)；提交后立即清空"
          data-testid="figma-token-input"
          class="cred-input"
          :disabled="busy || !writable || tokenSubmitting"
        />

        <div class="expiry-picker">
          <span class="lbl">有效期</span>
          <select
            v-model="selectedExpiryDays"
            class="st-select"
            data-testid="figma-expiry-select"
            :disabled="busy || !writable || tokenSubmitting"
          >
            <option v-for="opt in expiryOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <Button
          variant="primary"
          data-testid="save-figma-token-btn"
          :disabled="!inputToken || busy || !writable || tokenSubmitting"
          @click="onSaveToken"
        >
          {{ tokenSubmitting ? '保存中…' : '保存 Token' }}
        </Button>
        <Button
          v-if="fg?.token_configured"
          variant="destructive"
          data-testid="delete-figma-token-btn"
          :disabled="busy || !writable"
          @click="onDeleteToken"
        >
          删除 Token
        </Button>
        <Button
          variant="default"
          data-testid="import-figma-token-btn"
          :disabled="busy || !writable"
          @click="onImportLegacyToken"
        >
          从旧应用导入
        </Button>
      </div>
    </div>

    <hr class="st-sep" />

    <!-- 限流参数配置 -->
    <div class="ratelimit-section">
      <strong class="setting-title">限流与退避参数</strong>
      <p class="st-note">防止因多轮会话或大文件抓取触发 Figma API 429 限流保护。</p>

      <div class="ratelimit-grid">
        <div class="st-fld">
          <span class="lbl">最大并发数 (max_concurrency)</span>
          <TextField
            v-model="editConcurrency"
            label="最大并发数"
            placeholder="1"
            data-testid="figma-concurrency-input"
            :disabled="busy || !writable"
          />
        </div>

        <div class="st-fld">
          <span class="lbl">最小调用间隔 (min_interval_ms)</span>
          <TextField
            v-model="editInterval"
            label="最小调用间隔 (毫秒)"
            placeholder="350"
            data-testid="figma-interval-input"
            :disabled="busy || !writable"
          />
        </div>

        <div class="st-fld">
          <span class="lbl">最大重试次数 (max_retry)</span>
          <TextField
            v-model="editRetry"
            label="最大重试次数"
            placeholder="4"
            data-testid="figma-retry-input"
            :disabled="busy || !writable"
          />
        </div>
      </div>

      <div class="ratelimit-actions">
        <Button
          variant="primary"
          data-testid="save-figma-ratelimit-btn"
          :disabled="busy || !writable || rateLimitSubmitting"
          @click="onSaveRateLimits"
        >
          {{ rateLimitSubmitting ? '保存中…' : '保存限流参数' }}
        </Button>
        <span v-if="rateLimitMessage" class="st-ok" data-testid="figma-ratelimit-msg">
          {{ rateLimitMessage }}
        </span>
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
          data-testid="copy-figma-snippet-btn"
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
        data-testid="figma-cli-segmented"
        class="cli-seg"
      />
      <pre class="st-mono snippet-box" data-testid="figma-snippet-box">{{
        clientConfig?.snippet || '加载片段中…'
      }}</pre>
    </div>
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
.cred-section,
.ratelimit-section,
.snippet-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.setting-title {
  font-size: var(--text-body);
}
.cred-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cred-input {
  flex: 1;
  min-width: 240px;
}
.expiry-picker {
  display: flex;
  align-items: center;
  gap: 6px;
}
.st-select {
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-ctl);
  color: var(--text);
  padding: 0 8px;
  font-size: var(--text-body);
}
.ratelimit-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.ratelimit-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
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
