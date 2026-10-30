<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Tag from '@/components/Tag.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import { appKind, appPath, useVpnBypass, type AppKind } from './useVpnBypass'

const props = defineProps<{
  /** 外层 VPN 快照的全局配置版本；变化时静默刷新（不覆盖未保存草稿）。 */
  revision?: number | null
  busy?: boolean
  writable?: boolean
}>()

const bp = useVpnBypass()

const canMutate = computed(() => !!props.writable && !props.busy && !bp.operating.value)
const editable = canMutate
const confirmDiscard = ref(false)

watch(
  () => props.revision,
  (next, prev) => {
    if (next != null && prev != null && next !== prev) void bp.refresh()
  },
)

const interfaceModel = computed({
  get: () => bp.draft.value.interface ?? '',
  set: (v: string) => {
    bp.draft.value.interface = v || null
  },
})
const gatewayModel = computed({
  get: () => bp.draft.value.gateway ?? '',
  set: (v: string) => {
    bp.draft.value.gateway = v || null
  },
})

const canSave = computed(() => canMutate.value && bp.dirty.value && bp.problems.value.length === 0)
const canActivate = computed(() => canMutate.value && bp.canActivate.value)
// 已安装即可停用撤销：不看启用开关、草稿是否脏、配置是否合法
const canDeactivate = computed(() => canMutate.value && bp.installed.value)

const STATE_LABELS: Record<string, string> = {
  not_installed: '未安装',
  stopped: '已停止',
  pending: '待同步',
  active: '路由已验证',
  degraded: '部分异常',
  error: '错误',
}
const stateLabel = computed(() => STATE_LABELS[bp.status.value?.state ?? ''] ?? '未知')
const stateKind = computed(() => (bp.status.value?.state === 'active' ? 'ok' : 'warn'))
const activateLabel = computed(() => {
  if (bp.op.value === 'activating') return '等待系统授权/应用中…'
  if (!bp.installed.value) return '授权安装并应用'
  return bp.status.value?.synced && bp.status.value?.running ? '重新应用' : '应用已保存配置'
})
const saveLabel = computed(() => {
  if (bp.saving.value) return bp.installed.value ? '同步中…' : '保存中…'
  return bp.installed.value ? '保存并同步' : '保存配置'
})
const lastSweep = computed(() => {
  const t = bp.status.value?.last_sweep_at
  return t == null ? '尚未扫描' : new Date(t * 1000).toLocaleString()
})
// 应用已安装且运行，但没有发现任何目标：不能当作成功
const noTargets = computed(
  () => bp.installed.value && bp.status.value?.running === true && bp.targets.value.length === 0,
)

async function onSave() {
  if (canSave.value) await bp.save()
}
async function onActivate() {
  if (canActivate.value) await bp.activate()
}
async function onDeactivate() {
  if (canDeactivate.value) await bp.deactivate()
}
async function onDiscard() {
  confirmDiscard.value = false
  await bp.discardAndReload()
}
function onKind(a: Parameters<typeof bp.setAppKind>[0], e: Event) {
  bp.setAppKind(a, (e.target as HTMLSelectElement).value as AppKind)
}
function onPath(a: Parameters<typeof bp.setAppPath>[0], e: Event) {
  bp.setAppPath(a, (e.target as HTMLInputElement).value)
}
</script>

<template>
  <div class="bp-panel" data-testid="vpn-bypass-panel">
    <div class="bp-head">
      <div class="sub-head">分流（让指定应用的流量绕过 VPN）</div>
      <Tag v-if="bp.dirty.value" tone="warn" data-testid="bp-dirty-tag">有未保存修改</Tag>
      <div class="st-grow" />
      <Button
        variant="default"
        data-testid="bp-refresh-btn"
        :disabled="bp.loading.value || props.busy || bp.operating.value"
        @click="bp.refresh()"
      >
        {{ bp.loading.value ? '读取中…' : '刷新' }}
      </Button>
    </div>

    <!-- 能力边界：只保留两条必须让用户知道的限制 -->
    <Banner kind="info" data-testid="bp-limits">
      <ul class="bp-limits">
        <li>
          分流是按目标
          <b>IPv4 地址</b>添加的系统路由：<b>同一目标下所有应用共用</b>，不是按进程隔离。
        </li>
        <li>仅支持 <b>IPv4</b>，不覆盖 IPv6。</li>
      </ul>
      <details
        v-if="bp.status.value?.limitations?.length"
        class="bp-more"
        data-testid="bp-more-limits"
      >
        <summary>更多限制</summary>
        <ul class="bp-limits">
          <li v-for="l in bp.status.value.limitations" :key="l">{{ l }}</li>
        </ul>
      </details>
    </Banner>

    <div v-if="bp.status.value" class="bp-status" data-testid="bp-status">
      <div class="bp-row">
        <Tag :tone="stateKind" data-testid="bp-state-tag">{{ stateLabel }}</Tag>
        <Tag :tone="bp.status.value.installed ? 'ok' : 'warn'" data-testid="bp-installed-tag">{{
          bp.status.value.installed ? '助手已安装' : '助手未安装'
        }}</Tag>
        <Tag :tone="bp.status.value.running ? 'ok' : 'warn'" data-testid="bp-running-tag">{{
          bp.status.value.running ? '运行中' : '未运行'
        }}</Tag>
        <Tag :tone="bp.status.value.synced ? 'ok' : 'warn'" data-testid="bp-synced-tag">{{
          bp.status.value.synced ? '配置已同步' : '配置未同步'
        }}</Tag>
        <span class="form-desc" data-testid="bp-last-sweep">最近扫描：{{ lastSweep }}</span>
      </div>
      <div data-testid="bp-status-message">{{ bp.status.value.message }}</div>
      <div v-if="noTargets" class="form-desc" data-testid="bp-no-targets">
        尚未发现任何目标，当前没有生效的分流路由。
      </div>
      <table v-if="bp.targets.value.length" class="bp-targets-table" data-testid="bp-target-list">
        <thead>
          <tr>
            <th>目标</th>
            <th>网关 / 网卡</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in bp.targets.value" :key="t.target" data-testid="bp-target-row">
            <td>
              <code>{{ t.target }}</code>
            </td>
            <td>{{ t.gateway ?? '—' }} / {{ t.interface ?? '—' }}</td>
            <td>
              <Tag :tone="t.verified ? 'ok' : 'warn'">{{ t.verified ? '已验证' : '未验证' }}</Tag>
              <Tag :tone="t.owned ? 'ok' : 'warn'">{{
                t.owned ? '本工具持有' : '非本工具持有'
              }}</Tag>
            </td>
          </tr>
        </tbody>
      </table>
      <ul v-if="bp.status.value.errors?.length" class="bp-problems" data-testid="bp-status-errors">
        <li v-for="e in bp.status.value.errors" :key="e">{{ e }}</li>
      </ul>
    </div>

    <Banner v-if="bp.loadError.value" kind="error" data-testid="bp-load-error">
      读取分流配置失败：{{ bp.loadError.value }}
    </Banner>
    <Banner v-if="bp.saveError.value" kind="error" data-testid="bp-save-error">
      保存失败：{{ bp.saveError.value }}
    </Banner>
    <Banner v-if="bp.syncError.value" kind="warn" data-testid="bp-sync-error">
      {{ bp.syncError.value }}。你的草稿已保留，版本已刷新，可直接重试「保存并同步」或「重新应用」。
    </Banner>
    <Banner v-if="bp.cancelled.value" kind="info" data-testid="bp-cancelled">
      已取消系统授权；助手未获准继续更新，配置与路由请以实际状态为准。
    </Banner>
    <Banner v-if="bp.remote.value" kind="warn" data-testid="bp-conflict-banner">
      后端配置已更新到版本 {{ bp.remote.value.revision }}（你的草稿基于版本
      {{
        bp.baseRevision.value
      }}）。你的未保存修改已保留，不会被覆盖；需要时请显式刷新采用最新版本。
      <div class="bp-row">
        <Button
          v-if="!confirmDiscard"
          variant="default"
          data-testid="bp-reload-remote-btn"
          @click="confirmDiscard = true"
        >
          丢弃草稿并刷新
        </Button>
        <template v-else>
          <span>确认丢弃未保存修改？</span>
          <Button variant="destructive" data-testid="bp-confirm-reload-btn" @click="onDiscard"
            >确认丢弃</Button
          >
          <Button variant="default" @click="confirmDiscard = false">取消</Button>
        </template>
      </div>
    </Banner>
    <Banner v-if="bp.notice.value" kind="info" data-testid="bp-notice">{{
      bp.notice.value
    }}</Banner>

    <div v-if="bp.server.value" class="bp-body">
      <!-- 基础配置 -->
      <div class="bp-grid">
        <div class="bp-field bp-inline">
          <label class="form-label">配置启用分流</label>
          <Switch
            :model-value="bp.draft.value.enabled"
            :disabled="!editable"
            data-testid="bp-enabled-switch"
            @update:model-value="bp.draft.value.enabled = $event"
          />
        </div>
        <div class="bp-field">
          <label class="form-label" for="bp-gateway">物理网关（IPv4）</label>
          <input
            id="bp-gateway"
            v-model="gatewayModel"
            class="num-input"
            placeholder="例如 192.168.1.1"
            :disabled="!editable"
            data-testid="bp-gateway-input"
          />
        </div>
        <div class="bp-field">
          <label class="form-label" for="bp-interface">物理网卡</label>
          <input
            id="bp-interface"
            v-model="interfaceModel"
            class="num-input"
            placeholder="例如 en0"
            :disabled="!editable"
            data-testid="bp-interface-input"
          />
        </div>
        <div class="bp-field">
          <label class="form-label" for="bp-interval">扫描间隔（秒，5–300）</label>
          <input
            id="bp-interval"
            v-model.number="bp.draft.value.interval_s"
            type="number"
            class="num-input"
            min="5"
            max="300"
            :disabled="!editable"
            data-testid="bp-interval-input"
          />
        </div>
        <div class="bp-field">
          <label class="form-label" for="bp-retention">路由保留（秒，0–3600）</label>
          <input
            id="bp-retention"
            v-model.number="bp.draft.value.retention_s"
            type="number"
            class="num-input"
            min="0"
            max="3600"
            :disabled="!editable"
            data-testid="bp-retention-input"
          />
        </div>
      </div>
      <p class="form-desc">
        网关和网卡都需填写；只打开开关不会补全配置，也不会立即修改路由。预览时会校验物理网卡与直连网关，校验失败则停止操作。
      </p>

      <!-- 应用规则 -->
      <div class="bp-section-head">
        <span class="cred-title">应用规则（{{ bp.draft.value.apps.length }}/32）</span>
        <div class="st-grow" />
        <Button
          variant="default"
          :disabled="!editable || bp.draft.value.apps.length >= 32"
          data-testid="bp-add-app-btn"
          @click="bp.addApp()"
        >
          添加应用规则
        </Button>
      </div>
      <p class="form-desc">
        优先填写<b>可执行文件的精确绝对路径</b>（辅助子进程以此匹配）。选择「.app 包」时只匹配其
        Contents/MacOS 里的真实可执行文件，不匹配命令行文本或其他子进程。
      </p>
      <div v-if="bp.draft.value.apps.length === 0" class="form-desc" data-testid="bp-apps-empty">
        暂无应用规则。
      </div>
      <div v-for="a in bp.draft.value.apps" :key="a.id" class="bp-app" data-testid="bp-app-row">
        <Switch
          :model-value="a.enabled"
          :disabled="!editable"
          data-testid="bp-app-enabled"
          @update:model-value="a.enabled = $event"
        />
        <input
          v-model="a.name"
          class="num-input bp-name"
          placeholder="规则名称"
          maxlength="80"
          :disabled="!editable"
          data-testid="bp-app-name"
        />
        <select
          class="form-select"
          :value="appKind(a)"
          :disabled="!editable"
          data-testid="bp-app-kind"
          @change="onKind(a, $event)"
        >
          <option value="executable">可执行文件</option>
          <option value="application">.app 包</option>
        </select>
        <input
          :value="appPath(a)"
          class="num-input bp-path"
          :placeholder="
            appKind(a) === 'application'
              ? '/Applications/Xxx.app（填入真实安装路径）'
              : '/path/to/executable（填入真实路径）'
          "
          :disabled="!editable"
          data-testid="bp-app-path"
          @input="onPath(a, $event)"
        />
        <Button
          variant="destructive"
          :disabled="!editable"
          data-testid="bp-app-remove"
          @click="bp.removeApp(a.id)"
        >
          删除
        </Button>
      </div>

      <!-- 手动目标 -->
      <div class="bp-section-head">
        <span class="cred-title">手动目标（IPv4 / CIDR，每行一个）</span>
      </div>
      <textarea
        v-model="bp.targetsText.value"
        class="bp-targets"
        rows="4"
        placeholder="203.0.113.7&#10;198.51.100.0/24"
        :disabled="!editable"
        data-testid="bp-targets-input"
      />
      <p class="form-desc">不接受 /0 与非单播地址；这些目标会始终走物理网关（所有应用共用）。</p>

      <ul v-if="bp.problems.value.length" class="bp-problems" data-testid="bp-problems">
        <li v-for="p in bp.problems.value" :key="p">{{ p }}</li>
      </ul>

      <div class="settings-actions">
        <span v-if="!props.writable" class="form-desc" data-testid="bp-readonly-hint"
          >当前只读，无法修改分流配置。</span
        >
        <Button variant="primary" :disabled="!canSave" data-testid="bp-save-btn" @click="onSave">
          {{ saveLabel }}
        </Button>
      </div>
      <p v-if="bp.installed.value" class="form-desc" data-testid="bp-save-sync-hint">
        助手已安装：保存会自动同步到系统，macOS 可能弹出授权窗口（可能需要数分钟，请勿重复点击）。
      </p>
      <p v-else class="form-desc" data-testid="bp-save-install-hint">
        保存不会安装或修改系统路由；保存后点击「授权安装并应用」才会安装助手并生效。
      </p>

      <!-- 安装 / 应用 / 停用 -->
      <div class="bp-section-head">
        <span class="cred-title">应用到系统</span>
        <div class="st-grow" />
        <Button
          variant="primary"
          :disabled="!canActivate"
          data-testid="bp-activate-btn"
          @click="onActivate"
        >
          {{ activateLabel }}
        </Button>
        <Button
          variant="destructive"
          :disabled="!canDeactivate"
          data-testid="bp-deactivate-btn"
          @click="onDeactivate"
        >
          {{ bp.op.value === 'deactivating' ? '撤销中…' : '停用并撤销' }}
        </Button>
      </div>
      <p v-if="bp.dirty.value" class="form-desc" data-testid="bp-activate-dirty-hint">
        有未保存修改：请先保存再应用；停用并撤销不受影响。
      </p>
      <p
        v-else-if="!bp.savedEnabled.value"
        class="form-desc"
        data-testid="bp-activate-disabled-hint"
      >
        已保存的配置未启用分流，无法应用；请打开「配置启用分流」并保存。
      </p>
      <p v-if="bp.operating.value" class="form-desc" data-testid="bp-op-hint">
        系统授权可能需要数分钟，请在弹出的系统窗口中完成；期间其他操作已锁定。
      </p>
      <Banner v-if="bp.actionError.value" kind="error" data-testid="bp-action-error">
        {{ bp.actionError.value }}
      </Banner>

      <!-- 状态预览（只读，不会应用） -->
      <div class="bp-section-head">
        <span class="cred-title">预览（只读检查）</span>
        <div class="st-grow" />
        <Button
          variant="default"
          :disabled="
            props.busy ||
            bp.previewing.value ||
            bp.dirty.value ||
            bp.loading.value ||
            bp.operating.value
          "
          data-testid="bp-preview-btn"
          @click="bp.runPreview()"
        >
          {{ bp.previewing.value ? '检查中…' : '预览当前发现的目标' }}
        </Button>
      </div>
      <p class="form-desc">只检查已保存的配置，不修改路由。</p>
      <p v-if="bp.dirty.value" class="form-desc" data-testid="bp-preview-dirty-hint">
        当前修改尚未保存，请先补全配置并保存，再预览，避免读取旧配置。
      </p>
      <div
        v-if="bp.preview.value && !bp.dirty.value"
        class="bp-preview"
        data-testid="bp-preview-result"
      >
        <div>{{ bp.preview.value.message }}</div>
        <div class="form-desc">
          网关 {{ bp.preview.value.gateway ?? '未配置' }} · 网卡
          {{ bp.preview.value.interface ?? '未配置' }}
        </div>
        <div v-if="bp.preview.value.targets.length" data-testid="bp-preview-targets">
          发现 {{ bp.preview.value.targets.length }} 个目标：
          <code>{{ bp.preview.value.targets.join('、') }}</code>
        </div>
        <ul v-if="bp.preview.value.errors.length" class="bp-problems">
          <li v-for="e in bp.preview.value.errors" :key="e">{{ e }}</li>
        </ul>
      </div>
    </div>
    <div v-else-if="!bp.loadError.value" class="form-desc" data-testid="bp-loading">
      {{ bp.loading.value ? '读取分流配置…' : '尚未读取分流配置。' }}
    </div>
  </div>
</template>

<style scoped>
.bp-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}
.bp-head,
.bp-section-head,
.bp-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.bp-section-head {
  margin-top: 8px;
}
.bp-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  align-items: end;
}
.bp-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.bp-inline {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}
.bp-limits {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.bp-app {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 0;
  border-top: 1px solid var(--line);
}
.bp-name {
  width: 150px;
}
.bp-path {
  flex: 1;
  min-width: 220px;
  font-family: var(--font-mono, monospace);
}
.bp-targets {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  background: var(--ctl);
  color: var(--ink);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-body);
}
.bp-problems {
  margin: 0;
  padding-left: 18px;
  color: #dc2626;
  font-size: var(--text-sub);
}
.bp-preview {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--text-body);
}
.bp-status {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bp-targets-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sub);
}
.bp-targets-table th,
.bp-targets-table td {
  text-align: left;
  padding: 4px 8px;
  border-top: 1px solid var(--line);
}
</style>
