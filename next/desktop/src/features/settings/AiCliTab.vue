<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { AIJobData } from '@/api/events'
import type {
  AgyAnalysis,
  AgyDefaults,
  ClaudeAnalysis,
  ClaudeDefaults,
  CodexAnalysis,
  CodexDefaults,
  ModelPresets,
  ProfileView,
} from './api'
import { settingsContextKey } from './useSettings'

const ctx = inject(settingsContextKey)!
const runtime = inject(backendRuntimeKey)

onMounted(() => {
  ctx.aiTabActive.value = true
})
onUnmounted(() => {
  ctx.aiTabActive.value = false
})

const aiData = computed(() => ctx.ai.data.value ?? null)
const rawProfiles = computed(() => (aiData.value?.profiles ?? []) as unknown[])
const profiles = computed(() =>
  rawProfiles.value.filter(
    (p): p is ProfileView =>
      typeof p === 'object' &&
      p !== null &&
      'id' in p &&
      typeof (p as { id: unknown }).id === 'string',
  ),
)
const hasInvalidProfiles = computed(() =>
  rawProfiles.value.some(
    (p) =>
      typeof p !== 'object' ||
      p === null ||
      !('id' in p) ||
      typeof (p as { id: unknown }).id !== 'string',
  ),
)

// --- 检测 (Check) ---
const checkSheetOpen = ref(false)
const checkingProfile = ref<ProfileView | null>(null)
const checkResult = ref<{ ok: boolean; exit_code?: number | null; output: string } | null>(null)
const checkLoading = ref(false)
const checkError = ref<string | null>(null)

async function onCheck(profile: ProfileView) {
  checkingProfile.value = profile
  checkResult.value = null
  checkError.value = null
  checkLoading.value = true
  checkSheetOpen.value = true
  try {
    const res = await ctx.checkAiProfile(String(profile.id))
    checkResult.value = res
  } catch (err: unknown) {
    checkError.value = err instanceof Error ? err.message : String(err)
  } finally {
    checkLoading.value = false
  }
}

// --- 升级 (Upgrade) ---
const upgradeSheetOpen = ref(false)
const upgradingProfile = ref<ProfileView | null>(null)
const activeJobId = ref<string | null>(null)
const activeJobState = ref<'running' | 'succeeded' | 'failed' | 'cancelled' | null>(null)
const activeJobOutput = ref('')
const activeJobExitCode = ref<number | null>(null)
const upgradeSubmitting = ref(false)
const upgradeError = ref<string | null>(null)

// 监听 WS ai.job 与早到事件缓存
const earlyJobEvents = new Map<string, AIJobData>()

function applyJobData(data: AIJobData) {
  if (data.state) {
    activeJobState.value = data.state
  }
  if (data.output !== undefined) {
    // 最多保留 256 KiB
    activeJobOutput.value = data.output.slice(-262144)
  }
  if (data.exit_code !== undefined) {
    activeJobExitCode.value = data.exit_code
  }
}

let unbindJobEvents: (() => void) | null = null
onMounted(() => {
  if (runtime) {
    unbindJobEvents = runtime.onEvent((envelope) => {
      if (envelope.topic === 'ai' && envelope.type === 'ai.job') {
        const data = envelope.data as unknown as AIJobData
        if (data?.job_id) {
          if (activeJobId.value && data.job_id === activeJobId.value) {
            applyJobData(data)
          } else {
            // S5D-T06: 缓存早于 HTTP POST 响应到达的终态/过程事件
            earlyJobEvents.set(data.job_id, data)
            if (earlyJobEvents.size > 20) {
              const firstKey = earlyJobEvents.keys().next().value
              if (firstKey) earlyJobEvents.delete(firstKey)
            }
          }
        }
      }
    })
  }
})

onUnmounted(() => {
  if (unbindJobEvents) {
    unbindJobEvents()
    unbindJobEvents = null
  }
  earlyJobEvents.clear()
})

function onOpenUpgradeSheet(profile: ProfileView) {
  upgradingProfile.value = profile
  upgradeError.value = null
  activeJobId.value = null
  activeJobState.value = null
  activeJobOutput.value = ''
  activeJobExitCode.value = null
  earlyJobEvents.clear()
  upgradeSheetOpen.value = true
}

async function onConfirmUpgrade() {
  // S5D-T05: 同步重入保护（快速连点时第二击同步拦截）
  if (upgradeSubmitting.value) return
  if (!upgradingProfile.value) return
  upgradeSubmitting.value = true
  upgradeError.value = null
  try {
    const res = await ctx.upgradeAiProfile(String(upgradingProfile.value.id))
    activeJobId.value = res.job_id
    // S5D-T06: 合并早于响应到达的 ai.job 事件
    const early = earlyJobEvents.get(res.job_id)
    if (early) {
      earlyJobEvents.delete(res.job_id)
      applyJobData(early)
      if (!activeJobState.value) {
        activeJobState.value = 'running'
      }
    } else {
      activeJobState.value = 'running'
    }
  } catch (err: unknown) {
    const code =
      typeof err === 'object' && err !== null && 'code' in err
        ? String((err as { code: unknown }).code)
        : ''
    const status =
      typeof err === 'object' && err !== null && 'status' in err
        ? Number((err as { status: unknown }).status)
        : 0
    const msg = err instanceof Error ? err.message : String(err)
    if (code === 'busy' || status === 409 || msg.includes('409') || msg.includes('busy')) {
      upgradeError.value = '已有 AI 升级任务正在运行，同时只允许一个升级任务'
    } else {
      upgradeError.value = msg
    }
  } finally {
    upgradeSubmitting.value = false
  }
}

async function onCancelJob() {
  if (!activeJobId.value) return
  try {
    await ctx.cancelAiJob(activeJobId.value)
  } catch (err: unknown) {
    upgradeError.value = err instanceof Error ? err.message : String(err)
  }
}

// --- 添加/编辑 Profile ---
const profileSheetOpen = ref(false)
const isEditing = ref(false)
const editingId = ref('')
const formName = ref('')
const formCli = ref<'claude' | 'codex' | 'agy' | 'other'>('other')
const formCommand = ref('')
const formUpgradeCommand = ref('')
const formError = ref<string | null>(null)
const formSubmitting = ref(false)

function onOpenAddProfile() {
  isEditing.value = false
  editingId.value = ''
  formName.value = ''
  formCli.value = 'other'
  formCommand.value = ''
  formUpgradeCommand.value = ''
  formError.value = null
  profileSheetOpen.value = true
}

function onOpenEditProfile(p: ProfileView) {
  isEditing.value = true
  editingId.value = String(p.id)
  formName.value = String(p.name ?? '')
  formCli.value = (p.cli as 'claude' | 'codex' | 'agy' | 'other') ?? 'other'
  formCommand.value = String(p.command ?? '')
  formUpgradeCommand.value = String(p.upgrade_command ?? '')
  formError.value = null
  profileSheetOpen.value = true
}

async function onSaveProfile() {
  formError.value = null
  if (!formName.value.trim()) {
    formError.value = '配置名称不能为空'
    return
  }
  if (!formCommand.value.trim()) {
    formError.value = '启动命令不能为空'
    return
  }
  formSubmitting.value = true

  if (isEditing.value) {
    await ctx.patchAiProfile(
      editingId.value,
      {
        name: formName.value.trim(),
        command: formCommand.value.trim(),
        upgrade_command: formUpgradeCommand.value.trim(),
      },
      (err) => {
        formError.value = err.message
        return true
      },
      {
        onConflict: () => {
          formError.value = '配置已被其他窗口修改，已自动刷新最新内容'
          return true
        },
      },
    )
  } else {
    await ctx.createAiProfile(
      {
        name: formName.value.trim(),
        cli: formCli.value,
        command: formCommand.value.trim(),
        upgrade_command: formUpgradeCommand.value.trim(),
      },
      (err) => {
        formError.value = err.message
        return true
      },
      {
        onConflict: () => {
          formError.value = '配置已被修改，请重试'
          return true
        },
      },
    )
  }

  formSubmitting.value = false
  if (!formError.value) {
    profileSheetOpen.value = false
  }
}

// --- 删除 Profile ---
const deleteSheetOpen = ref(false)
const deletingProfile = ref<ProfileView | null>(null)
const deleteError = ref<string | null>(null)
const deleteSubmitting = ref(false)

function onOpenDeleteProfile(p: ProfileView) {
  deletingProfile.value = p
  deleteError.value = null
  deleteSheetOpen.value = true
}

async function onConfirmDeleteProfile() {
  if (!deletingProfile.value) return
  deleteSubmitting.value = true
  deleteError.value = null
  await ctx.deleteAiProfile(
    String(deletingProfile.value.id),
    (err) => {
      deleteError.value = err.message
      return true
    },
    {
      onConflict: () => {
        deleteError.value = '配置已被修改，请刷新后重试'
        return true
      },
    },
  )
  deleteSubmitting.value = false
  if (!deleteError.value) {
    deleteSheetOpen.value = false
  }
}

// --- 默认档位、工单分析档位与模型预设编辑 ---
const MODEL_REGEX = /^[A-Za-z0-9][A-Za-z0-9._:/() +-]{0,79}$/

const claudePermission = ref<ClaudeDefaults['permission']>('auto')
const claudeEffort = ref<ClaudeDefaults['effort']>(null)
const claudeModel = ref('')
const claudeAnalysis = ref<ClaudeAnalysis['permission']>('plan')

const codexSandbox = ref<CodexDefaults['sandbox']>('workspace-write')
const codexEffort = ref<CodexDefaults['effort']>('medium')
const codexModel = ref('')
const codexAnalysis = ref<CodexAnalysis['sandbox']>('read-only')

const agyMode = ref<AgyDefaults['mode']>('sandbox')
const agyModel = ref('')
const agyAnalysis = ref<AgyAnalysis['mode']>('sandbox')

const claudePresetsText = ref('')
const codexPresetsText = ref('')
const selectedProfileId = ref('')

const settingsError = ref<string | null>(null)
const settingsSubmitting = ref(false)

// 高权限档位风险提示（已决4）
const hasHighRiskSetting = computed(() => {
  return (
    claudePermission.value === 'bypassPermissions' ||
    codexSandbox.value === 'danger-full-access' ||
    agyMode.value === 'auto'
  )
})

watch(
  aiData,
  (d) => {
    if (!d) return
    const defaults = d.defaults ?? {}
    const analysis = d.analysis ?? {}

    claudePermission.value = defaults.claude?.permission ?? 'auto'
    claudeEffort.value = defaults.claude?.effort ?? null
    claudeModel.value = defaults.claude?.model ?? ''
    claudeAnalysis.value = analysis.claude?.permission ?? 'plan'

    codexSandbox.value = defaults.codex?.sandbox ?? 'workspace-write'
    codexEffort.value = defaults.codex?.effort ?? 'medium'
    codexModel.value = defaults.codex?.model ?? ''
    codexAnalysis.value = analysis.codex?.sandbox ?? 'read-only'

    agyMode.value = defaults.agy?.mode ?? 'sandbox'
    agyModel.value = defaults.agy?.model ?? ''
    agyAnalysis.value = analysis.agy?.mode ?? 'sandbox'

    const presets = d.model_presets ?? {}
    claudePresetsText.value = (presets.claude ?? []).join('\n')
    codexPresetsText.value = (presets.codex ?? []).join('\n')
    selectedProfileId.value = d.selected_profile_id ?? ''
  },
  { immediate: true },
)

function parsePresets(text: string): { valid: boolean; list: string[] } {
  const lines = text
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean)
  for (const item of lines) {
    if (!MODEL_REGEX.test(item)) {
      return { valid: false, list: [] }
    }
  }
  return { valid: true, list: lines }
}

async function onSaveSettings() {
  settingsError.value = null

  const claudeP = parsePresets(claudePresetsText.value)
  if (!claudeP.valid) {
    settingsError.value = 'Claude 模型预设格式不合规（只允许包含字母、数字及 ._:/() +- 且长度≤80）'
    return
  }
  const codexP = parsePresets(codexPresetsText.value)
  if (!codexP.valid) {
    settingsError.value = 'Codex 模型预设格式不合规（只允许包含字母、数字及 ._:/() +- 且长度≤80）'
    return
  }

  if (claudeModel.value.trim() && !MODEL_REGEX.test(claudeModel.value.trim())) {
    settingsError.value = 'Claude 默认模型名不合规'
    return
  }
  if (codexModel.value.trim() && !MODEL_REGEX.test(codexModel.value.trim())) {
    settingsError.value = 'Codex 默认模型名不合规'
    return
  }
  if (agyModel.value.trim() && !MODEL_REGEX.test(agyModel.value.trim())) {
    settingsError.value = 'Antigravity 默认模型名不合规'
    return
  }

  settingsSubmitting.value = true

  const patchBody = {
    selected_profile_id: selectedProfileId.value || null,
    defaults: {
      claude: {
        ...(aiData.value?.defaults?.claude ?? {}),
        permission: claudePermission.value,
        effort: claudeEffort.value,
        model: claudeModel.value.trim() || null,
      },
      codex: {
        ...(aiData.value?.defaults?.codex ?? {}),
        sandbox: codexSandbox.value,
        effort: codexEffort.value,
        model: codexModel.value.trim() || null,
      },
      agy: {
        ...(aiData.value?.defaults?.agy ?? {}),
        mode: agyMode.value,
        model: agyModel.value.trim() || null,
      },
    },
    analysis: {
      claude: {
        ...(aiData.value?.analysis?.claude ?? {}),
        permission: claudeAnalysis.value,
      },
      codex: {
        ...(aiData.value?.analysis?.codex ?? {}),
        sandbox: codexAnalysis.value,
      },
      agy: {
        ...(aiData.value?.analysis?.agy ?? {}),
        mode: agyAnalysis.value,
      },
    },
    model_presets: {
      ...(aiData.value?.model_presets ?? {}),
      claude: claudeP.list,
      codex: codexP.list,
      agy: aiData.value?.model_presets?.agy ?? [],
    } as ModelPresets,
    ...(aiData.value?.mcp_tool_prefix !== undefined
      ? { mcp_tool_prefix: aiData.value.mcp_tool_prefix }
      : {}),
  }

  await ctx.patchAiSettings(
    patchBody,
    (err) => {
      settingsError.value = err.message
      return true
    },
    {
      onConflict: () => {
        settingsError.value = '配置已被其他操作修改，已自动刷新最新内容'
        return true
      },
    },
  )

  settingsSubmitting.value = false
}
</script>

<template>
  <div class="st-body" data-testid="ai-cli-tab">
    <!-- 存储错误提示 -->
    <Banner
      v-if="aiData?.store_state === 'unavailable'"
      kind="error"
      class="mb-4"
      data-testid="ai-store-unavailable-banner"
    >
      AI 存储库不可用（只读错误态），无法启动会话或修改配置。
    </Banner>

    <!-- Profiles 列表 -->
    <section class="st-section" aria-label="AI CLI Profiles">
      <div class="st-head">
        <h2>AI CLI 配置 (Profiles)</h2>
        <Tag>{{ profiles.length }}</Tag>
        <span class="st-grow"></span>
        <Button
          variant="primary"
          data-testid="add-profile-btn"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="onOpenAddProfile"
        >
          ＋ 添加配置
        </Button>
      </div>

      <Banner
        v-if="hasInvalidProfiles"
        kind="warn"
        class="mb-3"
        data-testid="invalid-profiles-banner"
      >
        检测到无效配置项，已自动安全跳过
      </Banner>

      <table class="st-tbl" data-testid="profiles-table">
        <thead>
          <tr>
            <th scope="col">名称</th>
            <th scope="col">CLI</th>
            <th scope="col">启动命令</th>
            <th scope="col">检测状态</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in profiles" :key="String(p.id)" :data-testid="`profile-row-${p.id}`">
            <td>
              <div class="profile-name-cell">
                <span class="font-medium">{{ String(p.name) }}</span>
                <Tag v-if="p.builtin" class="ml-2 text-xs">内置</Tag>
              </div>
            </td>
            <td>
              <span class="st-mono text-xs uppercase">{{ String(p.cli) }}</span>
            </td>
            <td class="st-mono text-xs">{{ String(p.command) }}</td>
            <td>
              <div class="status-cell" :data-testid="`profile-status-${p.id}`">
                <span
                  class="status-indicator"
                  :class="p.resolved?.ok ? 'status-ok' : 'status-err'"
                ></span>
                <span :class="p.resolved?.ok ? 'text-green-700' : 'text-amber-700'">
                  {{ p.resolved?.ok ? '可执行' : '不可执行' }}
                </span>
                <span v-if="p.resolved?.version" class="text-xs text-neutral-500 ml-1">
                  ({{ p.resolved.version }})
                </span>
                <span v-else-if="p.resolved?.path_hint" class="text-xs text-neutral-500 ml-1">
                  ({{ p.resolved.path_hint }})
                </span>
              </div>
            </td>
            <td>
              <div class="actions-cell">
                <Button
                  size="sm"
                  variant="default"
                  :data-testid="`check-profile-btn-${p.id}`"
                  :disabled="ctx.busy.value"
                  @click="onCheck(p)"
                >
                  检测
                </Button>
                <Button
                  v-if="p.upgrade_command"
                  size="sm"
                  variant="default"
                  :data-testid="`upgrade-profile-btn-${p.id}`"
                  :disabled="ctx.busy.value || activeJobState === 'running'"
                  @click="onOpenUpgradeSheet(p)"
                >
                  升级
                </Button>
                <Button
                  size="sm"
                  variant="default"
                  :data-testid="`edit-profile-btn-${p.id}`"
                  :disabled="ctx.busy.value || !ctx.writable.value"
                  @click="onOpenEditProfile(p)"
                >
                  编辑
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  :data-testid="`delete-profile-btn-${p.id}`"
                  :disabled="p.builtin || ctx.busy.value || !ctx.writable.value"
                  :title="p.builtin ? '内置配置不可删除' : '删除配置'"
                  @click="onOpenDeleteProfile(p)"
                >
                  删除
                </Button>
              </div>
            </td>
          </tr>
          <tr v-if="profiles.length === 0">
            <td colspan="5" class="st-note">暂无 AI CLI 配置</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 默认档位与工单分析档位设置 -->
    <section class="st-section mt-6" aria-label="默认档位与工单分析">
      <div class="st-head">
        <h2>档位与模型预设</h2>
      </div>

      <Banner v-if="settingsError" kind="error" class="mb-4" data-testid="settings-error-banner">
        {{ settingsError }}
      </Banner>

      <!-- 高权限档位风险提示 (已决4) -->
      <Banner
        v-if="hasHighRiskSetting"
        kind="warn"
        class="mb-4"
        data-testid="high-risk-tier-banner"
      >
        高权限档位风险提示：已选高权限档位（Claude bypassPermissions / Codex danger-full-access /
        agy auto）。该档位下 AI 将完全跳过沙箱或审批，可在本机运行任意命令，请确保环境可信！
      </Banner>

      <div class="settings-grid">
        <!-- Claude 档位 -->
        <div class="settings-card" data-testid="claude-settings-card">
          <h3 class="card-title">Claude Code</h3>
          <div class="form-row">
            <label for="claude-perm-select">默认权限档位</label>
            <select
              id="claude-perm-select"
              v-model="claudePermission"
              class="b-select"
              data-testid="claude-perm-select"
            >
              <option value="default">default (默认)</option>
              <option value="acceptEdits">acceptEdits (自动接受编辑)</option>
              <option value="auto">auto (自动允许常用只读工具)</option>
              <option value="dontAsk">dontAsk (静默拒绝需审批命令)</option>
              <option value="bypassPermissions">bypassPermissions (跳过所有审批 · 高危)</option>
              <option value="plan">plan (只读计划模式)</option>
            </select>
          </div>
          <div class="form-row">
            <label for="claude-effort-select">思考努力程度 (Effort)</label>
            <select id="claude-effort-select" v-model="claudeEffort" class="b-select">
              <option :value="null">默认</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="xhigh">xhigh</option>
              <option value="max">max</option>
            </select>
          </div>
          <div class="form-row">
            <label for="claude-analysis-select">工单分析档位</label>
            <select id="claude-analysis-select" v-model="claudeAnalysis" class="b-select">
              <option value="plan">plan (只读计划 · 推荐)</option>
              <option value="auto">auto</option>
              <option value="acceptEdits">acceptEdits</option>
            </select>
          </div>
          <div class="form-row">
            <label for="claude-model-input">默认模型 (选填)</label>
            <TextField
              id="claude-model-input"
              v-model="claudeModel"
              label="Claude 默认模型"
              placeholder="如 claude-3-5-sonnet"
            />
          </div>
        </div>

        <!-- Codex 档位 -->
        <div class="settings-card" data-testid="codex-settings-card">
          <h3 class="card-title">Codex CLI</h3>
          <div class="form-row">
            <label for="codex-sandbox-select">默认沙箱档位</label>
            <select
              id="codex-sandbox-select"
              v-model="codexSandbox"
              class="b-select"
              data-testid="codex-sandbox-select"
            >
              <option value="read-only">read-only (只读)</option>
              <option value="workspace-write">workspace-write (工作区可写)</option>
              <option value="danger-full-access">danger-full-access (完全访问 · 高危)</option>
            </select>
          </div>
          <div class="form-row">
            <label for="codex-effort-select">思考努力程度 (Effort)</label>
            <select id="codex-effort-select" v-model="codexEffort" class="b-select">
              <option value="minimal">minimal</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </div>
          <div class="form-row">
            <label for="codex-analysis-select">工单分析档位</label>
            <select id="codex-analysis-select" v-model="codexAnalysis" class="b-select">
              <option value="read-only">read-only (只读 · 推荐)</option>
              <option value="workspace-write">workspace-write</option>
            </select>
          </div>
          <div class="form-row">
            <label for="codex-model-input">默认模型 (选填)</label>
            <TextField
              id="codex-model-input"
              v-model="codexModel"
              label="Codex 默认模型"
              placeholder="如 gpt-5.3-codex"
            />
          </div>
        </div>

        <!-- Antigravity (agy) 档位 -->
        <div class="settings-card" data-testid="agy-settings-card">
          <h3 class="card-title">Antigravity (agy)</h3>
          <div class="form-row">
            <label for="agy-mode-select">默认运行模式</label>
            <select
              id="agy-mode-select"
              v-model="agyMode"
              class="b-select"
              data-testid="agy-mode-select"
            >
              <option value="sandbox">sandbox (沙箱安全隔离)</option>
              <option value="auto">auto (自动批准所有命令 · 高危)</option>
            </select>
          </div>
          <div class="form-row">
            <label for="agy-analysis-select">工单分析档位</label>
            <select id="agy-analysis-select" v-model="agyAnalysis" class="b-select">
              <option value="sandbox">sandbox (沙箱 · 推荐)</option>
              <option value="auto">auto</option>
            </select>
          </div>
          <div class="form-row">
            <label for="agy-model-input">默认模型 (选填)</label>
            <TextField
              id="agy-model-input"
              v-model="agyModel"
              label="Antigravity 默认模型"
              placeholder="如 gemini-3.8-flash"
            />
          </div>
        </div>
      </div>

      <!-- 模型预设 -->
      <div class="presets-section mt-4">
        <h3 class="card-title">模型预设列表 (每行或以逗号分隔一个模型名)</h3>
        <div class="presets-grid mt-2">
          <div class="preset-col">
            <label for="claude-presets-textarea">Claude 模型预设</label>
            <textarea
              id="claude-presets-textarea"
              v-model="claudePresetsText"
              class="presets-textarea"
              rows="3"
              data-testid="claude-presets-textarea"
            ></textarea>
          </div>
          <div class="preset-col">
            <label for="codex-presets-textarea">Codex 模型预设</label>
            <textarea
              id="codex-presets-textarea"
              v-model="codexPresetsText"
              class="presets-textarea"
              rows="3"
              data-testid="codex-presets-textarea"
            ></textarea>
          </div>
        </div>
      </div>

      <div class="mt-4 flex justify-end">
        <Button
          variant="primary"
          data-testid="save-ai-settings-btn"
          :disabled="ctx.busy.value || !ctx.writable.value || settingsSubmitting"
          @click="onSaveSettings"
        >
          {{ settingsSubmitting ? '正在保存…' : '保存 AI 档位与预设' }}
        </Button>
      </div>
    </section>

    <!-- 检测结果 Sheet -->
    <Sheet
      :open="checkSheetOpen"
      :title="`检测 ${checkingProfile?.name ?? ''} 可执行文件`"
      description="后端解析可执行文件路径并执行 --version 进行连通性校验。"
      @update:open="checkSheetOpen = $event"
    >
      <div class="check-body p-2" data-testid="check-dialog">
        <Banner v-if="checkError" kind="error" class="mb-3">
          {{ checkError }}
        </Banner>
        <div v-if="checkLoading" class="p-4 text-center text-sm text-neutral-500">
          正在检测 CLI 可执行文件，请稍候…
        </div>
        <div v-else-if="checkResult" class="check-result-box" data-testid="check-result-box">
          <div class="result-header mb-2">
            <span class="font-semibold">检测状态：</span>
            <span :class="checkResult.ok ? 'text-green-600 font-bold' : 'text-red-600 font-bold'">
              {{ checkResult.ok ? '成功 (OK)' : '失败' }}
            </span>
            <span
              v-if="checkResult.exit_code !== null && checkResult.exit_code !== undefined"
              class="ml-2 text-sm text-neutral-500"
            >
              退出码: {{ checkResult.exit_code }}
            </span>
          </div>
          <div class="output-title text-xs font-semibold text-neutral-600 mb-1">命令输出：</div>
          <pre class="check-output st-mono" data-testid="check-output">{{
            checkResult.output || '(无输出)'
          }}</pre>
        </div>
        <div class="mt-4 flex justify-end">
          <Button variant="default" @click="checkSheetOpen = false">关闭</Button>
        </div>
      </div>
    </Sheet>

    <!-- 升级确认与输出 Sheet -->
    <Sheet
      :open="upgradeSheetOpen"
      :title="`升级 ${upgradingProfile?.name ?? ''}`"
      description="通过监督器执行预设的升级命令，并在下方实时查看输出。"
      @update:open="upgradeSheetOpen = $event"
    >
      <div class="upgrade-body p-2" data-testid="upgrade-dialog">
        <Banner v-if="upgradeError" kind="error" class="mb-3">
          {{ upgradeError }}
        </Banner>

        <div v-if="!activeJobId" class="upgrade-prompt">
          <p class="text-sm mb-2 text-neutral-700 dark:text-neutral-300">将运行以下升级命令：</p>
          <pre class="command-box st-mono mb-4">{{ upgradingProfile?.upgrade_command }}</pre>
          <div class="flex justify-end gap-2">
            <Button
              variant="default"
              :disabled="upgradeSubmitting"
              @click="upgradeSheetOpen = false"
              >取消</Button
            >
            <Button
              variant="primary"
              data-testid="confirm-upgrade-btn"
              :disabled="upgradeSubmitting"
              @click="onConfirmUpgrade"
            >
              {{ upgradeSubmitting ? '启动中…' : '确认升级' }}
            </Button>
          </div>
        </div>

        <div v-else class="job-running-box" data-testid="upgrade-job-box">
          <div class="job-status-line mb-2 flex items-center justify-between">
            <div>
              <span class="font-semibold text-sm">状态：</span>
              <span class="job-state font-bold text-sm" :data-state="activeJobState">
                {{
                  activeJobState === 'running'
                    ? '正在执行升级…'
                    : activeJobState === 'succeeded'
                      ? '升级成功'
                      : activeJobState === 'failed'
                        ? '升级失败'
                        : '已取消'
                }}
              </span>
              <span v-if="activeJobExitCode !== null" class="ml-2 text-xs text-neutral-500">
                (退出码: {{ activeJobExitCode }})
              </span>
            </div>
            <Button
              v-if="activeJobState === 'running'"
              size="sm"
              variant="destructive"
              data-testid="cancel-job-btn"
              @click="onCancelJob"
            >
              取消升级
            </Button>
          </div>

          <div class="output-label text-xs font-semibold text-neutral-600 mb-1">
            升级实时日志 (≤256 KiB)：
          </div>
          <pre class="job-output st-mono" data-testid="upgrade-output">{{
            activeJobOutput || '(等待输出...)'
          }}</pre>

          <div class="mt-4 flex justify-end">
            <Button
              variant="default"
              :disabled="activeJobState === 'running'"
              @click="upgradeSheetOpen = false"
            >
              完成
            </Button>
          </div>
        </div>
      </div>
    </Sheet>

    <!-- 添加/编辑 Profile Sheet -->
    <Sheet
      :open="profileSheetOpen"
      :title="isEditing ? `编辑 AI CLI 配置` : `添加自定义 AI CLI 配置`"
      description="配置命令名必须经 shlex 解析非空，第 0 项为可执行程序绝对路径或可从 PATH 解析的程序名。"
      @update:open="profileSheetOpen = $event"
    >
      <form class="p-2 space-y-4" data-testid="profile-form" @submit.prevent="onSaveProfile">
        <Banner v-if="formError" kind="error" class="mb-2">
          {{ formError }}
        </Banner>

        <div class="field-row">
          <label for="form-profile-name">配置名称</label>
          <TextField
            id="form-profile-name"
            v-model="formName"
            label="配置名称"
            data-testid="profile-name-input"
            placeholder="如 Claude 生产版"
          />
        </div>

        <div class="field-row">
          <label for="form-profile-cli">CLI 类型</label>
          <select
            id="form-profile-cli"
            v-model="formCli"
            class="b-select"
            data-testid="profile-cli-select"
            :disabled="isEditing"
          >
            <option value="claude">claude</option>
            <option value="codex">codex</option>
            <option value="agy">agy (Antigravity)</option>
            <option value="other">other (其他)</option>
          </select>
        </div>

        <div class="field-row">
          <label for="form-profile-cmd">启动命令 (非空，最多 512 字符)</label>
          <TextField
            id="form-profile-cmd"
            v-model="formCommand"
            label="启动命令"
            data-testid="profile-cmd-input"
            placeholder="如 claude --verbose"
          />
        </div>

        <div class="field-row">
          <label for="form-profile-upcmd">升级命令 (选填，最多 512 字符)</label>
          <TextField
            id="form-profile-upcmd"
            v-model="formUpgradeCommand"
            label="升级命令"
            data-testid="profile-upcmd-input"
            placeholder="如 npm install -g @anthropic-ai/claude-code"
          />
        </div>

        <div class="flex justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="default"
            :disabled="formSubmitting"
            @click="profileSheetOpen = false"
            >取消</Button
          >
          <Button
            type="submit"
            variant="primary"
            data-testid="save-profile-btn"
            :disabled="formSubmitting"
          >
            {{ formSubmitting ? '保存中…' : '保存配置' }}
          </Button>
        </div>
      </form>
    </Sheet>

    <!-- 删除 Profile 确认 Sheet -->
    <Sheet
      :open="deleteSheetOpen"
      title="删除 AI CLI 配置"
      description="确认要删除该自定义 CLI 配置吗？"
      @update:open="deleteSheetOpen = $event"
    >
      <div class="p-2">
        <Banner v-if="deleteError" kind="error" class="mb-3">
          {{ deleteError }}
        </Banner>
        <p class="text-sm mb-4">
          确定要删除配置 <strong>{{ deletingProfile?.name }}</strong> 吗？内置配置不可删除。
        </p>
        <div class="flex justify-end gap-2">
          <Button variant="default" :disabled="deleteSubmitting" @click="deleteSheetOpen = false"
            >取消</Button
          >
          <Button
            variant="destructive"
            data-testid="confirm-delete-profile-btn"
            :disabled="deleteSubmitting"
            @click="onConfirmDeleteProfile"
          >
            {{ deleteSubmitting ? '删除中…' : '确认删除' }}
          </Button>
        </div>
      </div>
    </Sheet>
  </div>
</template>

<style scoped>
.profile-name-cell {
  display: flex;
  align-items: center;
}
.status-cell {
  display: flex;
  align-items: center;
  font-size: 12.5px;
}
.status-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 6px;
}
.status-ok {
  background: #16a34a;
}
.status-err {
  background: #e07b00;
}
.actions-cell {
  display: flex;
  gap: 6px;
}
.settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}
.settings-card {
  padding: 14px 16px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--bg-window);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-title {
  margin: 0 0 4px;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-row label {
  font-size: 12px;
  color: var(--text-muted);
}
.b-select {
  height: 30px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--text);
  padding: 0 8px;
  font-size: 12.5px;
  outline: none;
}
.presets-section {
  padding: 14px 16px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--bg-window);
}
.presets-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.preset-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.preset-col label {
  font-size: 12px;
  color: var(--text-muted);
}
.presets-textarea {
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--text);
  padding: 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  resize: vertical;
  outline: none;
}
.check-output,
.job-output,
.command-box {
  padding: 8px 12px;
  border-radius: 6px;
  background: #141416;
  color: #f4f4f5;
  font-size: 12px;
  max-height: 240px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.field-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field-row label {
  font-size: 12.5px;
  font-weight: 500;
}
.job-state[data-state='running'] {
  color: var(--accent-ink);
}
.job-state[data-state='succeeded'] {
  color: #16a34a;
}
.job-state[data-state='failed'] {
  color: #dc2626;
}
.job-state[data-state='cancelled'] {
  color: #a1a1aa;
}
</style>
