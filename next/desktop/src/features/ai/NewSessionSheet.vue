<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import {
  createAiSession,
  fetchAiAgyModels,
  fetchResumeCandidates,
  toApiError,
  type AIDefaults,
  type ModelPresets,
  type ProfileView,
  type RepoView,
  type ResumeCandidate,
  type SessionView,
} from './api'
import { formatAiError } from './terminal-protocol'

const props = defineProps<{
  open: boolean
  profiles: ProfileView[]
  localRepos: RepoView[]
  defaultProfileId?: string
  modelPresets?: ModelPresets
  defaults?: AIDefaults
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  created: [session: SessionView]
  jumpToRepos: []
}>()

const runtime = inject(backendRuntimeKey)

const kind = ref<'terminal' | 'chat'>('terminal')
const profileId = ref('')
const repoId = ref('')
const model = ref('')
const effort = ref('')
const permission = ref('')
const initialPrompt = ref('')
const isResume = ref(false)
const resumeSessionId = ref('')
const resumeCandidates = ref<ResumeCandidate[]>([])
const loadingCandidates = ref(false)
const candidateQuery = ref('')

const agyModels = ref<string[]>([])
const loadingAgyModels = ref(false)

const ackHighRisk = ref(false)
const showHighRiskAck = ref(false)
const requestId = ref('')
const submitting = ref(false)
const errorMessage = ref<string | null>(null)

const selectedProfile = computed(() => props.profiles.find((p) => String(p.id) === profileId.value))
const selectedCli = computed(() =>
  selectedProfile.value?.cli ? String(selectedProfile.value.cli) : '',
)

// 高权限档位判断：Claude bypassPermissions / Codex danger-full-access / agy auto / terminal 模式下的 agy
const isHighRisk = computed(() => {
  const cli = selectedCli.value
  if (kind.value === 'terminal') {
    return cli === 'agy'
  }
  if (cli === 'claude') {
    return permission.value === 'bypassPermissions'
  }
  if (cli === 'codex') {
    return permission.value === 'danger-full-access'
  }
  if (cli === 'agy') {
    return permission.value === 'auto'
  }
  return false
})

const promptBytes = computed(() => {
  if (!initialPrompt.value) return 0
  return new TextEncoder().encode(initialPrompt.value).length
})

const isPromptTooLarge = computed(() => promptBytes.value > 32768)

// 选项列表
const availableModels = computed(() => {
  const cli = selectedCli.value
  if (cli === 'claude') {
    return props.modelPresets?.claude ?? []
  }
  if (cli === 'codex') {
    return props.modelPresets?.codex ?? []
  }
  if (cli === 'agy') {
    return agyModels.value
  }
  return []
})

const permissionOptions = computed(() => {
  const cli = selectedCli.value
  if (cli === 'claude') {
    return [
      { value: 'manual', label: '手动审批 (manual)' },
      { value: 'acceptEdits', label: '自动接受编辑 (acceptEdits)' },
      { value: 'plan', label: '规划模式 (plan)' },
      { value: 'auto', label: '自动执行 (auto)' },
      { value: 'dontAsk', label: '不询问 (dontAsk)' },
      { value: 'bypassPermissions', label: '完全放行 - 高风险 (bypassPermissions)' },
    ]
  }
  if (cli === 'codex') {
    return [
      { value: 'workspace-write', label: '工作区写入 (workspace-write)' },
      { value: 'read-only', label: '只读沙箱 (read-only)' },
      { value: 'danger-full-access', label: '无沙箱完全访问 - 高风险 (danger-full-access)' },
    ]
  }
  if (cli === 'agy') {
    return [
      { value: 'plan', label: '规划模式 (plan)' },
      { value: 'sandbox', label: '沙箱模式 (sandbox)' },
      { value: 'auto', label: '全自动 - 高风险 (auto)' },
    ]
  }
  return []
})

const effortOptions = computed(() => {
  const cli = selectedCli.value
  if (cli === 'claude') {
    return [
      { value: '', label: '默认 (Default)' },
      { value: 'low', label: '低 (low)' },
      { value: 'medium', label: '中 (medium)' },
      { value: 'high', label: '高 (high)' },
      { value: 'xhigh', label: '超高 (xhigh)' },
      { value: 'max', label: '最高 (max)' },
    ]
  }
  if (cli === 'codex') {
    return [
      { value: '', label: '默认 (Default)' },
      { value: 'none', label: '无 (none)' },
      { value: 'minimal', label: '极低 (minimal)' },
      { value: 'low', label: '低 (low)' },
      { value: 'medium', label: '中 (medium)' },
      { value: 'high', label: '高 (high)' },
      { value: 'xhigh', label: '超高 (xhigh)' },
      { value: 'max', label: '最高 (max)' },
    ]
  }
  if (cli === 'agy') {
    return [
      { value: '', label: '默认 (Default)' },
      { value: 'low', label: '低 (low)' },
      { value: 'medium', label: '中 (medium)' },
      { value: 'high', label: '高 (high)' },
      { value: 'xhigh', label: '超高 (xhigh)' },
      { value: 'max', label: '最高 (max)' },
    ]
  }
  return []
})

async function loadAgyModels() {
  const client = runtime?.api()
  if (!client || agyModels.value.length > 0 || loadingAgyModels.value) return
  loadingAgyModels.value = true
  try {
    const res = await fetchAiAgyModels(client)
    agyModels.value = res.items || []
    if (!model.value && agyModels.value.length > 0) {
      model.value = agyModels.value[0]!
    }
  } catch {
    // 忽略加载错误，使用空列表
  } finally {
    loadingAgyModels.value = false
  }
}

async function loadResumeCandidates() {
  const client = runtime?.api()
  if (!client || !repoId.value || selectedCli.value !== 'claude') return
  loadingCandidates.value = true
  try {
    const res = await fetchResumeCandidates(
      client,
      repoId.value,
      candidateQuery.value.trim() || undefined,
    )
    resumeCandidates.value = res.items || []
    if (!resumeSessionId.value && resumeCandidates.value.length > 0) {
      resumeSessionId.value = resumeCandidates.value[0]!.session_id
    }
  } catch {
    resumeCandidates.value = []
  } finally {
    loadingCandidates.value = false
  }
}

function resetDefaultsForCli() {
  const cli = selectedCli.value
  if (cli === 'claude') {
    const claudeDef = props.defaults?.claude
    model.value = claudeDef?.model || props.modelPresets?.claude?.[0] || ''
    permission.value = claudeDef?.permission || 'auto'
    effort.value = claudeDef?.effort || ''
  } else if (cli === 'codex') {
    const codexDef = props.defaults?.codex
    model.value = codexDef?.model || props.modelPresets?.codex?.[0] || ''
    permission.value = codexDef?.sandbox || 'workspace-write'
    effort.value = codexDef?.effort || ''
  } else if (cli === 'agy') {
    const agyDef = props.defaults?.agy
    model.value = agyDef?.model || agyModels.value[0] || ''
    permission.value = agyDef?.mode || 'sandbox'
    effort.value = agyDef?.effort || ''
    void loadAgyModels()
  }
}

watch(selectedCli, () => {
  resetDefaultsForCli()
  if (isResume.value && selectedCli.value === 'claude') {
    void loadResumeCandidates()
  }
})

watch([isResume, repoId], ([resume, rid]) => {
  if (resume && rid && selectedCli.value === 'claude') {
    void loadResumeCandidates()
  }
})

watch(
  () => props.open,
  (val) => {
    if (val) {
      requestId.value = crypto.randomUUID()
      errorMessage.value = null
      submitting.value = false
      ackHighRisk.value = false
      showHighRiskAck.value = false
      initialPrompt.value = ''
      isResume.value = false
      resumeSessionId.value = ''

      if (!profileId.value || !props.profiles.some((p) => String(p.id) === profileId.value)) {
        const available = props.profiles.find((p) => p.resolved?.ok) ?? props.profiles[0]
        profileId.value = available ? String(available.id) : ''
      }
      if (!repoId.value || !props.localRepos.some((r) => r.id === repoId.value)) {
        repoId.value = props.localRepos[0]?.id ?? ''
      }
      resetDefaultsForCli()
    }
  },
  { immediate: true },
)

async function submit() {
  if (submitting.value) return
  if (!profileId.value || !repoId.value) {
    errorMessage.value = '请选择 CLI 配置和本地仓库'
    return
  }
  if (isPromptTooLarge.value) {
    errorMessage.value = '初始提示词不能超过 32 KiB'
    return
  }
  if (isHighRisk.value && !ackHighRisk.value) {
    showHighRiskAck.value = true
    errorMessage.value = formatAiError('high_risk_ack_required')
    return
  }

  const client = runtime?.api()
  if (!client) {
    errorMessage.value = '无法连接后端'
    return
  }

  submitting.value = true
  errorMessage.value = null

  try {
    const session = await createAiSession(client, {
      request_id: requestId.value,
      kind: kind.value,
      profile_id: profileId.value,
      repo_id: repoId.value,
      ack_high_risk: ackHighRisk.value,
      ...(kind.value === 'chat'
        ? {
            model: model.value || null,
            effort: effort.value || null,
            permission: permission.value || null,
            initial_prompt: initialPrompt.value || null,
            ...(isResume.value && resumeSessionId.value
              ? { resume: { session_id: resumeSessionId.value } }
              : {}),
          }
        : {}),
    })
    emit('created', session)
    emit('update:open', false)
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    const code = (apiErr as { code?: string }).code
    if (code === 'high_risk_ack_required') {
      showHighRiskAck.value = true
      errorMessage.value = formatAiError('high_risk_ack_required')
    } else {
      errorMessage.value = formatAiError(code, '创建会话失败，请稍后重试')
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Sheet
    :open="open"
    :title="kind === 'chat' ? '新建 AI 对话会话' : '新建 AI 终端会话'"
    :description="
      kind === 'chat'
        ? '在指定的本地代码仓库中启动 AI 结构化对话会话。'
        : '在指定的本地代码仓库中启动 AI 命令行终端。'
    "
    @update:open="emit('update:open', $event)"
  >
    <form class="new-session-form" data-testid="new-session-form" @submit.prevent="submit">
      <Banner v-if="errorMessage" kind="error" class="mb-3" data-testid="session-error-banner">
        {{ errorMessage }}
      </Banner>

      <!-- 会话类型 -->
      <div class="field-row">
        <span class="field-label">会话类型</span>
        <div class="field-control">
          <div class="kind-options">
            <label class="kind-option" :class="{ active: kind === 'terminal' }">
              <input
                v-model="kind"
                type="radio"
                name="session_kind"
                value="terminal"
                data-testid="kind-terminal-radio"
                :disabled="submitting"
              />
              <span>终端（PTY）</span>
            </label>
            <label class="kind-option" :class="{ active: kind === 'chat' }">
              <input
                v-model="kind"
                type="radio"
                name="session_kind"
                value="chat"
                data-testid="kind-chat-radio"
                :disabled="submitting"
              />
              <span>对话（结构化）</span>
            </label>
          </div>
        </div>
      </div>

      <!-- AI CLI 配置 -->
      <div class="field-row">
        <label for="ai-profile-select" class="field-label">AI CLI 配置</label>
        <div class="field-control">
          <select
            id="ai-profile-select"
            v-model="profileId"
            class="b-select"
            data-testid="profile-select"
            :disabled="submitting || profiles.length === 0"
          >
            <option
              v-for="p in profiles"
              :key="String(p.id)"
              :value="String(p.id)"
              :disabled="!p.resolved?.ok"
            >
              {{ String(p.name) }} ({{ String(p.cli) }})
              {{ !p.resolved?.ok ? ' · 不可运行: ' + (p.resolved?.path_hint || '未就绪') : '' }}
            </option>
          </select>
          <span v-if="selectedProfile && !selectedProfile.resolved?.ok" class="field-hint warn">
            此 CLI 尚未就绪：{{ selectedProfile.resolved?.path_hint || '未检测到可执行文件' }}
          </span>
        </div>
      </div>

      <!-- 本地仓库 -->
      <div class="field-row">
        <label for="ai-repo-select" class="field-label">工作目录（本地仓库）</label>
        <div class="field-control">
          <div v-if="localRepos.length === 0" class="no-repos-box">
            <span class="text-sm text-neutral-500">暂无已配置的本地仓库</span>
            <Button
              type="button"
              variant="default"
              data-testid="jump-to-repos-btn"
              @click="emit('jumpToRepos')"
            >
              前往设置添加本地仓库
            </Button>
          </div>
          <select
            v-else
            id="ai-repo-select"
            v-model="repoId"
            class="b-select"
            data-testid="repo-select"
            :disabled="submitting"
          >
            <option v-for="r in localRepos" :key="r.id" :value="r.id">
              {{ r.name }}
            </option>
          </select>
          <div class="repo-manage-link">
            <button
              type="button"
              class="link-btn"
              data-testid="manage-repos-link"
              @click="emit('jumpToRepos')"
            >
              管理本地仓库…
            </button>
          </div>
        </div>
      </div>

      <!-- Chat 模式专属字段 -->
      <template v-if="kind === 'chat'">
        <!-- Claude 续聊选项 -->
        <div v-if="selectedCli === 'claude'" class="field-row">
          <span class="field-label">会话模式</span>
          <div class="field-control">
            <label class="resume-toggle-label">
              <input
                v-model="isResume"
                type="checkbox"
                data-testid="resume-checkbox"
                :disabled="submitting"
              />
              <span>从已有 Claude 历史会话续聊 (Resume)</span>
            </label>

            <div
              v-if="isResume"
              class="resume-candidate-box mt-2"
              data-testid="resume-candidates-box"
            >
              <div class="flex gap-2 mb-2">
                <input
                  v-model="candidateQuery"
                  type="text"
                  placeholder="搜索历史会话…"
                  class="b-input flex-1"
                  data-testid="candidate-query-input"
                  @keydown.enter.prevent="loadResumeCandidates"
                />
                <Button
                  type="button"
                  variant="default"
                  size="sm"
                  :disabled="loadingCandidates"
                  @click="loadResumeCandidates"
                >
                  {{ loadingCandidates ? '加载中…' : '刷新' }}
                </Button>
              </div>
              <div v-if="resumeCandidates.length === 0" class="text-xs text-neutral-500 py-2">
                {{ loadingCandidates ? '正在获取历史会话…' : '未找到此仓库下的历史会话' }}
              </div>
              <select
                v-else
                v-model="resumeSessionId"
                class="b-select"
                data-testid="resume-candidate-select"
                :disabled="submitting"
              >
                <option v-for="c in resumeCandidates" :key="c.session_id" :value="c.session_id">
                  {{ c.title }} ({{ c.updated_at }})
                </option>
              </select>
            </div>
          </div>
        </div>

        <!-- 模型选择 -->
        <div class="field-row">
          <label for="ai-model-select" class="field-label">模型 (Model)</label>
          <div class="field-control">
            <div v-if="availableModels.length > 0">
              <select
                id="ai-model-select"
                v-model="model"
                class="b-select"
                data-testid="model-select"
                :disabled="submitting"
              >
                <option v-for="m in availableModels" :key="m" :value="m">
                  {{ m }}
                </option>
              </select>
            </div>
            <div v-else>
              <input
                id="ai-model-select"
                v-model="model"
                type="text"
                class="b-input"
                placeholder="输入模型名称（可选）"
                data-testid="model-input"
                :disabled="submitting || loadingAgyModels"
              />
              <span v-if="loadingAgyModels" class="field-hint">正在加载模型列表…</span>
            </div>
          </div>
        </div>

        <!-- 权限 / 沙箱 / 模式 -->
        <div v-if="permissionOptions.length > 0" class="field-row">
          <label for="ai-permission-select" class="field-label">
            {{
              selectedCli === 'codex' ? '沙箱模式' : selectedCli === 'agy' ? '运行模式' : '权限模式'
            }}
          </label>
          <div class="field-control">
            <select
              id="ai-permission-select"
              v-model="permission"
              class="b-select"
              data-testid="permission-select"
              :disabled="submitting"
            >
              <option v-for="opt in permissionOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
        </div>

        <!-- 思考深度 (Effort) -->
        <div v-if="effortOptions.length > 0" class="field-row">
          <label for="ai-effort-select" class="field-label">思考深度 (Effort)</label>
          <div class="field-control">
            <select
              id="ai-effort-select"
              v-model="effort"
              class="b-select"
              data-testid="effort-select"
              :disabled="submitting"
            >
              <option v-for="opt in effortOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
        </div>

        <!-- 初始提示词 (<= 32 KiB) -->
        <div class="field-row">
          <label for="ai-initial-prompt" class="field-label">初始提示词 (可选)</label>
          <div class="field-control">
            <textarea
              id="ai-initial-prompt"
              v-model="initialPrompt"
              rows="3"
              class="b-textarea"
              placeholder="输入发送给 AI 的首条提示词（可选，最多 32 KiB）…"
              data-testid="initial-prompt-input"
              :disabled="submitting"
            ></textarea>
            <div class="prompt-len-hint" :class="{ error: isPromptTooLarge }">
              <span>{{ promptBytes }} / 32,768 字节</span>
              <span v-if="isPromptTooLarge" class="text-red-500 font-semibold ml-2">
                超出 32 KiB 限制！
              </span>
            </div>
          </div>
        </div>
      </template>

      <!-- 高风险确认复选框 -->
      <div v-if="showHighRiskAck || isHighRisk" class="high-risk-box" data-testid="high-risk-box">
        <Banner kind="warn" class="mb-2">
          高权限确认：该会话将以高权限或无沙箱模式运行命令，请确认已知晓风险。
        </Banner>
        <label class="ack-checkbox-label">
          <input
            v-model="ackHighRisk"
            type="checkbox"
            data-testid="high-risk-ack-checkbox"
            :disabled="submitting"
          />
          <span>我已知晓并确认以高权限模式启动此会话</span>
        </label>
      </div>

      <div class="sheet-footer">
        <Button
          type="button"
          variant="default"
          data-testid="cancel-create-btn"
          @click="emit('update:open', false)"
        >
          取消
        </Button>
        <Button
          type="submit"
          variant="primary"
          data-testid="confirm-create-btn"
          :disabled="
            submitting ||
            !profileId ||
            !repoId ||
            (selectedProfile && !selectedProfile.resolved?.ok) ||
            isPromptTooLarge
          "
        >
          {{ submitting ? '创建中…' : kind === 'chat' ? '创建对话会话' : '创建终端会话' }}
        </Button>
      </div>
    </form>
  </Sheet>
</template>

<style scoped>
.new-session-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 4px;
}
.field-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}
.field-control {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.b-select,
.b-input,
.b-textarea {
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--r-ctl, 6px);
  border: 1px solid var(--line);
  background: var(--card-bg, #fff);
  color: var(--ink);
  font: inherit;
  font-size: 13px;
}
.b-textarea {
  resize: vertical;
  min-height: 72px;
}
.b-select:focus,
.b-input:focus,
.b-textarea:focus {
  outline: 2px solid var(--focus);
  outline-offset: -1px;
}
.field-hint {
  font-size: 12px;
  color: var(--mute);
}
.field-hint.warn {
  color: #b45309;
}
.no-repos-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 6px;
  background: var(--bg-sub, #f5f5f7);
}
.repo-manage-link {
  margin-top: 4px;
}
.link-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 12px;
  color: var(--link);
  cursor: pointer;
  text-decoration: underline;
}
.kind-options {
  display: flex;
  gap: 12px;
}
.kind-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px solid var(--line);
  font-size: 13px;
  cursor: pointer;
  background: var(--card-bg, #fff);
}
.kind-option.active {
  border-color: var(--accent);
  background: var(--accent-sub, rgba(10, 99, 214, 0.08));
  font-weight: 600;
}
.kind-option input[type='radio'] {
  accent-color: var(--accent);
}
.high-risk-box {
  padding: 10px;
  border-radius: 6px;
  background: #fffbeb;
  border: 1px solid #fde68a;
}
.ack-checkbox-label,
.resume-toggle-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
}
.prompt-len-hint {
  display: flex;
  justify-content: flex-end;
  font-size: 11px;
  color: var(--mute);
  margin-top: 2px;
}
.prompt-len-hint.error {
  color: #dc2626;
}
.resume-candidate-box {
  padding: 8px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--bg-sub, #f9fafb);
}
.sheet-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
</style>
