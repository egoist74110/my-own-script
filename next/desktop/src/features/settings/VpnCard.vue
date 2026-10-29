<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import StatusPill from '@/components/StatusPill.vue'
import StatusDot from '@/components/StatusDot.vue'
import OverflowMenu from '@/components/OverflowMenu.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import type { PillState } from '@/components/pill'
import {
  VPN_EVENT_LABELS,
  VPN_RUNG_LABELS,
  vpnErrorMessage,
  type VpnConfig,
  type VpnSnapshot,
} from './api'
import { useVpnContext } from './useVpn'
import VpnTotpImportSheet from './VpnTotpImportSheet.vue'
import VpnMfaSheet from './VpnMfaSheet.vue'
import VpnLegacyImportSheet from './VpnLegacyImportSheet.vue'

const props = defineProps<{
  snapshot?: VpnSnapshot | null
  busy?: boolean
  writable?: boolean
}>()

const vpn = useVpnContext()

// Sheet 显隐状态
const totpSheetOpen = ref(false)
const legacySheetOpen = ref(false)
const showSettings = ref(false)
const confirmClearBrowser = ref(false)

// 凭据输入缓存（只写，提交后立即清空）
const passwordInput = ref('')
const totpInput = ref('')

// 设置项本地表单
const residencyOptions = [
  'US Data Residency',
  'EU Data Residency',
  'India Data Residency',
  'Australia Data Residency',
  'CA Data Residency',
] as const

function defaultVpnConfig(): VpnConfig {
  return {
    client: {
      bundle_id: 'com.safervpn.osx.smb',
      app_name: null,
      url_scheme: 'CheckPointSASE',
    },
    tunnel_prefix: '10.254.',
    login: {
      workspace: '',
      residency: 'US Data Residency',
      email: '',
      totp_filter: 'Perimeter',
      headless: true,
    },
    window_automation: 'off',
    rung_timeout_s: 30,
    login_timeout_s: 75,
    max_run_s: 480,
    chrome_path: null,
  }
}

const form = ref<VpnConfig>(defaultVpnConfig())

watch(
  () => props.snapshot?.settings,
  (val) => {
    if (val) {
      const merged = { ...defaultVpnConfig(), ...JSON.parse(JSON.stringify(val)) }
      merged.login = { ...defaultVpnConfig().login, ...(merged.login || {}) }
      merged.client = { ...defaultVpnConfig().client, ...(merged.client || {}) }
      form.value = merged
    }
  },
  { immediate: true },
)

const chromePathModel = computed({
  get: () => form.value.chrome_path ?? '',
  set: (val: string) => {
    form.value.chrome_path = val.trim() ? val.trim() : null
  },
})

const snap = computed(() => props.snapshot || vpn.snapshot.value)
const isConnected = computed(() => snap.value?.connected ?? false)
const ip = computed(() => snap.value?.ip ?? null)
const client = computed(() => snap.value?.client)
const currentRun = computed(() => snap.value?.current_run)
const credentials = computed(() => snap.value?.credentials)
const permissions = computed(() => snap.value?.permissions)

const isRunActive = computed(() => {
  const s = currentRun.value?.state
  return s === 'queued' || s === 'running' || s === 'cancelling'
})

const pillState = computed<PillState>(() => {
  if (isRunActive.value) return 'running'
  if (currentRun.value?.state === 'failed') return 'failed'
  if (isConnected.value) return 'running'
  return 'disabled'
})

const pillLabel = computed<string>(() => {
  if (currentRun.value?.state === 'cancelling') return '取消中'
  if (isRunActive.value) {
    const rung = currentRun.value?.rung ?? 0
    return VPN_RUNG_LABELS[rung] ? `连接中（${VPN_RUNG_LABELS[rung]}）` : '连接中'
  }
  if (currentRun.value?.state === 'failed') return '连接失败'
  if (currentRun.value?.state === 'cancelled') return '已取消'
  if (isConnected.value) return '已连接'
  return '未连接'
})

const clientInstalled = computed(() => client.value?.installed ?? false)
const clientRunning = computed(() => client.value?.running ?? false)
const clientVersionText = computed(() => {
  const name = client.value?.app_name || 'Check Point SASE'
  const ver = client.value?.version ? ` ${client.value.version}` : ''
  return `${name}${ver}`
})

const isScreenRecordingAuthorized = computed(
  () => permissions.value?.screen_recording === 'authorized',
)
const isAccessibilityAuthorized = computed(() => permissions.value?.accessibility === 'authorized')
const permissionsMissing = computed(
  () =>
    form.value.window_automation !== 'off' &&
    (!isScreenRecordingAuthorized.value || !isAccessibilityAuthorized.value),
)

const activeError = computed(() => {
  if (currentRun.value?.error_code) {
    return vpnErrorMessage(currentRun.value.error_code)
  }
  return vpn.error.value
})

const copied = ref(false)
async function copyIp() {
  if (!ip.value) return
  try {
    await navigator.clipboard.writeText(ip.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    // 忽略剪贴板写入异常
  }
}

// 凭据保存与删除
async function onSavePassword() {
  const val = passwordInput.value.trim()
  if (!val) return
  passwordInput.value = '' // 提交后立即清空内存输入
  await vpn.saveCredential('vpn_password', val)
}

async function onDeletePassword() {
  await vpn.deleteCredential('vpn_password')
}

async function onSaveTotp() {
  const val = totpInput.value.trim()
  if (!val) return
  totpInput.value = '' // 提交后立即清空内存输入
  await vpn.saveCredential('vpn_totp_secret', val)
}

async function onDeleteTotp() {
  await vpn.deleteCredential('vpn_totp_secret')
}

async function onSaveSettings() {
  await vpn.saveSettings(form.value)
}

async function onClearBrowser() {
  confirmClearBrowser.value = false
  await vpn.clearBrowserProfile()
}
</script>

<template>
  <div class="st-section" data-testid="vpn-card">
    <!-- 头部：标题、状态胶囊、主动作 -->
    <div class="st-head">
      <h2>VPN（Check Point SASE）</h2>
      <StatusPill :state="pillState" :label="pillLabel" data-testid="vpn-status-pill" />
      <div class="st-grow" />

      <!-- 主控制按钮 -->
      <div class="actions-row">
        <Button
          v-if="!isRunActive"
          variant="primary"
          data-testid="vpn-connect-btn"
          :disabled="
            props.busy || isConnected || !clientInstalled || vpn.actionLoading.value === 'connect'
          "
          @click="vpn.connect()"
        >
          {{ vpn.actionLoading.value === 'connect' ? '连接中…' : '连接' }}
        </Button>

        <Button
          v-if="!isRunActive"
          variant="default"
          data-testid="vpn-relogin-btn"
          :disabled="props.busy || !clientInstalled || vpn.actionLoading.value === 'relogin'"
          @click="vpn.relogin()"
        >
          {{ vpn.actionLoading.value === 'relogin' ? '重登中…' : '强制重登' }}
        </Button>

        <Button
          v-if="isRunActive"
          variant="destructive"
          data-testid="vpn-cancel-btn"
          :disabled="vpn.actionLoading.value === 'cancel'"
          @click="vpn.cancelRun()"
        >
          {{ vpn.actionLoading.value === 'cancel' ? '取消中…' : '取消连接' }}
        </Button>

        <OverflowMenu v-if="!confirmClearBrowser" label="更多 VPN 操作">
          <button
            type="button"
            role="menuitem"
            class="menu-item"
            data-testid="open-legacy-import-btn"
            :disabled="props.busy || isRunActive"
            @click="legacySheetOpen = true"
          >
            从旧应用导入
          </button>
          <button
            type="button"
            role="menuitem"
            class="menu-item"
            data-danger="true"
            data-testid="clear-browser-btn"
            :disabled="props.busy || isRunActive"
            @click="confirmClearBrowser = true"
          >
            忘记此浏览器
          </button>
        </OverflowMenu>

        <div v-else class="confirm-box st-free" data-testid="clear-browser-confirm-box">
          <span class="confirm-tip">确认清空 Chrome Profile？</span>
          <Button
            variant="destructive"
            data-testid="confirm-clear-browser-btn"
            :disabled="vpn.actionLoading.value === 'clear_browser'"
            @click="onClearBrowser"
          >
            确认
          </Button>
          <Button
            variant="default"
            data-testid="cancel-clear-browser-btn"
            @click="confirmClearBrowser = false"
          >
            取消
          </Button>
        </div>
      </div>
    </div>

    <!-- 全局提示与错误 -->
    <Banner
      v-if="vpn.notice.value"
      kind="info"
      data-testid="vpn-notice-banner"
      class="banner-block"
    >
      {{ vpn.notice.value }}
    </Banner>

    <Banner v-if="activeError" kind="error" data-testid="vpn-error-banner" class="banner-block">
      {{ activeError }}
    </Banner>

    <!-- 状态详情条：客户端、IP、版本 -->
    <div class="info-bar" data-testid="vpn-info-bar">
      <div class="info-group">
        <span class="info-label">客户端</span>
        <Tag v-if="!clientInstalled" state="verify" data-testid="client-not-installed-tag"
          >未安装客户端</Tag
        >
        <template v-else>
          <Tag v-if="clientRunning" state="running" data-testid="client-running-tag">运行中</Tag>
          <Tag v-else state="disabled" data-testid="client-stopped-tag">未运行</Tag>
          <span class="client-name" data-testid="client-version-text">{{ clientVersionText }}</span>
        </template>
      </div>

      <div class="info-group">
        <span class="info-label">VPN IP</span>
        <span class="ip-value" data-testid="vpn-ip-text">{{ ip || '未分配' }}</span>
        <Button
          v-if="ip"
          variant="default"
          class="copy-btn"
          data-testid="copy-ip-btn"
          @click="copyIp"
        >
          {{ copied ? '已复制' : '复制' }}
        </Button>
      </div>
    </div>

    <!-- 运行步骤时间线（当有运行或历史记录时展现） -->
    <div
      v-if="vpn.timelineEvents.value.length > 0 || (currentRun && isRunActive)"
      class="timeline-card"
      data-testid="vpn-timeline-card"
    >
      <div class="timeline-head">运行步骤进度</div>
      <div class="timeline-list">
        <div
          v-for="ev in vpn.timelineEvents.value"
          :key="`${ev.run_id}-${ev.run_seq}`"
          class="timeline-row"
          :class="{ error: ev.state === 'failed' }"
          data-testid="timeline-step-row"
        >
          <div class="step-indicator">
            <StatusDot
              :state="ev.state === 'failed' ? 'warn' : ev.event === 'done' ? 'ok' : 'run'"
            />
          </div>
          <div class="step-content">
            <span class="step-name">
              {{ ev.event ? VPN_EVENT_LABELS[ev.event] || ev.event : `档位 ${ev.rung}` }}
            </span>
            <span v-if="ev.error_code" class="step-error" data-testid="step-error-code">
              {{ vpnErrorMessage(ev.error_code) }}
            </span>
            <span v-if="ev.ip" class="step-ip">，分配 IP {{ ev.ip }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 凭据设置：密码与 TOTP 种子（纯只写，绝不回填明文） -->
    <div class="credentials-card" data-testid="vpn-credentials-section">
      <div class="sub-head">登录凭据</div>
      <p class="st-note">
        密码和 TOTP 种子直接写入 macOS 钥匙串。界面任何位置都不会回填或显示明文。
      </p>

      <div class="cred-grid">
        <!-- 密码行 -->
        <div class="cred-row" data-testid="password-cred-row">
          <div class="cred-meta">
            <span class="cred-title">登录密码</span>
            <Tag
              :state="credentials?.password ? 'running' : 'disabled'"
              data-testid="password-status-tag"
            >
              {{ credentials?.password ? '已配置' : '未配置' }}
            </Tag>
          </div>
          <div class="cred-form">
            <input
              v-model="passwordInput"
              type="password"
              class="cred-input"
              placeholder="输入新密码以更新"
              autocomplete="new-password"
              data-testid="vpn-password-input"
              :disabled="props.busy || isRunActive"
            />
            <Button
              variant="default"
              data-testid="save-password-btn"
              :disabled="
                !passwordInput.trim() ||
                props.busy ||
                isRunActive ||
                vpn.actionLoading.value === 'vpn_password'
              "
              @click="onSavePassword"
            >
              {{ vpn.actionLoading.value === 'vpn_password' ? '保存中…' : '保存密码' }}
            </Button>
            <Button
              v-if="credentials?.password"
              variant="destructive"
              data-testid="delete-password-btn"
              :disabled="
                props.busy || isRunActive || vpn.actionLoading.value === 'delete_vpn_password'
              "
              @click="onDeletePassword"
            >
              清除
            </Button>
          </div>
        </div>

        <!-- TOTP 种子行 -->
        <div class="cred-row" data-testid="totp-cred-row">
          <div class="cred-meta">
            <span class="cred-title">TOTP 种子</span>
            <Tag
              :state="credentials?.totp_secret ? 'running' : 'disabled'"
              data-testid="totp-status-tag"
            >
              {{ credentials?.totp_secret ? '已配置' : '未配置' }}
            </Tag>
          </div>
          <div class="cred-form">
            <input
              v-model="totpInput"
              type="password"
              class="cred-input"
              placeholder="输入 Base32 种子密钥"
              autocomplete="off"
              data-testid="vpn-totp-input"
              :disabled="props.busy || isRunActive"
            />
            <Button
              variant="default"
              data-testid="save-totp-btn"
              :disabled="
                !totpInput.trim() ||
                props.busy ||
                isRunActive ||
                vpn.actionLoading.value === 'vpn_totp_secret'
              "
              @click="onSaveTotp"
            >
              {{ vpn.actionLoading.value === 'vpn_totp_secret' ? '保存中…' : '保存种子' }}
            </Button>
            <Button
              variant="default"
              data-testid="open-totp-import-btn"
              :disabled="props.busy || isRunActive"
              @click="totpSheetOpen = true"
            >
              导入种子文件
            </Button>
            <Button
              v-if="credentials?.totp_secret"
              variant="destructive"
              data-testid="delete-totp-btn"
              :disabled="
                props.busy || isRunActive || vpn.actionLoading.value === 'delete_vpn_totp_secret'
              "
              @click="onDeleteTotp"
            >
              清除
            </Button>
          </div>
        </div>
      </div>
    </div>

    <!-- 折叠设置区 -->
    <div class="settings-toggle-row">
      <Button
        variant="default"
        data-testid="toggle-vpn-settings-btn"
        @click="showSettings = !showSettings"
      >
        {{ showSettings ? '收起 VPN 设置' : '展开 VPN 设置' }}
      </Button>
    </div>

    <div v-if="showSettings" class="settings-form" data-testid="vpn-settings-container">
      <Banner
        v-if="permissionsMissing"
        kind="warn"
        class="mb-3"
        data-testid="permissions-warning-banner"
      >
        窗口自动化已启用，但缺少所需权限（屏幕录制或辅助功能）。会移动真实鼠标；授权对象是启动后端的那个应用（终端/IDE/打包应用），授权后需重启后端。
      </Banner>

      <div class="form-grid">
        <div class="form-item">
          <label class="form-label" for="vpn-workspace">Workspace 域名/标识</label>
          <TextField
            v-if="form.login"
            id="vpn-workspace"
            v-model="form.login.workspace"
            label="Workspace"
            placeholder="例如 company.perimeter81.com"
            data-testid="vpn-workspace-input"
            :maxlength="200"
          />
        </div>

        <div class="form-item">
          <label class="form-label" for="vpn-residency">数据驻留区域</label>
          <select
            v-if="form.login"
            id="vpn-residency"
            v-model="form.login.residency"
            class="form-select"
            data-testid="vpn-residency-select"
          >
            <option v-for="opt in residencyOptions" :key="opt" :value="opt">
              {{ opt }}
            </option>
          </select>
        </div>

        <div class="form-item">
          <label class="form-label" for="vpn-email">SSO 登录邮箱</label>
          <TextField
            v-if="form.login"
            id="vpn-email"
            v-model="form.login.email"
            label="登录邮箱"
            placeholder="user@example.com"
            data-testid="vpn-email-input"
            :maxlength="200"
          />
        </div>

        <div class="form-item">
          <label class="form-label" for="vpn-tunnel-prefix">隧道网段前缀</label>
          <TextField
            id="vpn-tunnel-prefix"
            v-model="form.tunnel_prefix"
            label="隧道 IP 前缀"
            placeholder="10.254."
            data-testid="vpn-tunnel-prefix-input"
          />
        </div>

        <div class="form-item">
          <label class="form-label" for="vpn-totp-filter">TOTP 匹配过滤器</label>
          <TextField
            v-if="form.login"
            id="vpn-totp-filter"
            v-model="form.login.totp_filter"
            label="TOTP 过滤器"
            placeholder="Perimeter"
            data-testid="vpn-totp-filter-input"
          />
        </div>

        <div class="form-item">
          <label class="form-label" for="vpn-chrome-path">自定义 Chrome 绝对路径</label>
          <TextField
            id="vpn-chrome-path"
            v-model="chromePathModel"
            label="Chrome 路径"
            placeholder="留空使用系统默认 Chrome"
            data-testid="vpn-chrome-path-input"
          />
        </div>

        <div class="form-item">
          <label class="form-label">窗口自动化</label>
          <select
            v-model="form.window_automation"
            class="form-select"
            data-testid="vpn-window-automation-select"
          >
            <option value="off">关闭</option>
            <option value="connect">只点「Connect」</option>
            <option value="connect_update">点「Connect」并处理客户端更新</option>
          </select>
          <span class="form-desc"> 会移动真实鼠标，需要系统的屏幕录制和辅助功能权限。 </span>
        </div>

        <div class="form-item">
          <label class="form-label">系统权限状态（只读）</label>
          <div class="perm-row">
            <span class="perm-item" data-testid="perm-screen-recording">
              屏幕录制：
              <Tag :state="isScreenRecordingAuthorized ? 'running' : 'verify'">
                {{ isScreenRecordingAuthorized ? '已授权' : '未授权' }}
              </Tag>
            </span>
            <span class="perm-item" data-testid="perm-accessibility">
              辅助功能：
              <Tag :state="isAccessibilityAuthorized ? 'running' : 'verify'">
                {{ isAccessibilityAuthorized ? '已授权' : '未授权' }}
              </Tag>
            </span>
          </div>
        </div>

        <div class="form-item-full">
          <div class="timeout-grid">
            <div>
              <label class="form-label">每一步等待上限（秒）</label>
              <input
                v-model.number="form.rung_timeout_s"
                type="number"
                class="num-input"
                min="5"
                max="120"
                data-testid="vpn-rung-timeout-input"
              />
            </div>
            <div>
              <label class="form-label">登录流程上限（秒）</label>
              <input
                v-model.number="form.login_timeout_s"
                type="number"
                class="num-input"
                min="30"
                max="300"
                data-testid="vpn-login-timeout-input"
              />
            </div>
            <div>
              <label class="form-label">单次连接总时限（秒）</label>
              <input
                v-model.number="form.max_run_s"
                type="number"
                class="num-input"
                min="120"
                max="1200"
                data-testid="vpn-max-run-input"
              />
            </div>
            <div v-if="form.login" class="switch-row">
              <label class="form-label">后台登录（不显示浏览器窗口）</label>
              <Switch
                :checked="form.login.headless"
                data-testid="vpn-headless-switch"
                @update:checked="form.login.headless = $event"
              />
            </div>
          </div>
        </div>
      </div>

      <div class="settings-actions">
        <Button
          variant="primary"
          data-testid="save-vpn-settings-btn"
          :disabled="props.busy || isRunActive || vpn.actionLoading.value === 'save_settings'"
          @click="onSaveSettings"
        >
          {{ vpn.actionLoading.value === 'save_settings' ? '保存中…' : '保存设置' }}
        </Button>
      </div>
    </div>

    <!-- 子 Sheets -->
    <VpnTotpImportSheet :open="totpSheetOpen" @update:open="totpSheetOpen = $event" />

    <VpnMfaSheet :open="vpn.mfaModalOpen.value" @update:open="vpn.mfaModalOpen.value = $event" />

    <VpnLegacyImportSheet :open="legacySheetOpen" @update:open="legacySheetOpen = $event" />
  </div>
</template>

<style scoped>
.actions-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.confirm-box {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--st-failed-bg);
  border: 1px solid var(--bn-error-line);
  border-radius: var(--r-ctl);
  padding: 2px 6px;
}
.confirm-tip {
  font-size: var(--text-sub);
  color: var(--ink);
}
.banner-block {
  margin-top: 4px;
}
.info-bar {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
}
.info-group {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-body);
}
.info-label {
  color: var(--mute);
  font-size: var(--text-sub);
}
.client-name {
  color: var(--ink);
  font-weight: 500;
}
.ip-value {
  font-family: var(--font-mono, monospace);
  font-weight: 600;
  color: var(--ink);
}
.copy-btn {
  font-size: 11px;
  padding: 2px 6px;
  height: 22px;
}
.timeline-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.timeline-head {
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--mute);
}
.timeline-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.timeline-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-body);
}
.timeline-row.error {
  color: #dc2626;
}
.step-name {
  font-weight: 500;
}
.step-error {
  font-size: var(--text-sub);
  color: #dc2626;
  margin-left: 6px;
}
.step-ip {
  font-size: var(--text-sub);
  color: var(--mute);
  margin-left: 6px;
}
.credentials-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 4px;
}
.sub-head {
  font-size: var(--text-body);
  font-weight: 600;
  color: var(--ink);
}
.cred-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cred-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
  border-top: 1px solid var(--line);
  flex-wrap: wrap;
}
.cred-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cred-title {
  font-weight: 500;
  font-size: var(--text-body);
}
.cred-form {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cred-input {
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  font-size: var(--text-body);
  min-width: 180px;
  background: var(--ctl);
  color: var(--ink);
}
.cred-input:focus {
  outline: none;
  border-color: var(--accent);
}
.settings-toggle-row {
  display: flex;
  justify-content: flex-start;
  margin-top: 4px;
}
.settings-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 4px;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}
.form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-item-full {
  grid-column: 1 / -1;
}
.form-label {
  font-size: var(--text-sub);
  font-weight: 500;
  color: var(--mute);
}
.form-desc {
  font-size: 11px;
  color: var(--mute);
}
.form-select {
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  background: var(--ctl);
  color: var(--ink);
  font-size: var(--text-body);
}
.perm-row {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 36px;
}
.perm-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-body);
}
.timeout-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  align-items: end;
}
.num-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  font-size: var(--text-body);
  background: var(--ctl);
  color: var(--ink);
}
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
}
.settings-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
