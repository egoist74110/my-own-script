<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import { backendRuntimeKey } from '@/app/backend-runtime'
import {
  createAiSession,
  toApiError,
  type ProfileView,
  type RepoView,
  type SessionView,
} from './api'
import { formatAiError } from './terminal-protocol'

const props = defineProps<{
  open: boolean
  profiles: ProfileView[]
  localRepos: RepoView[]
  defaultProfileId?: string
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  created: [session: SessionView]
  jumpToRepos: []
}>()

const runtime = inject(backendRuntimeKey)

const profileId = ref('')
const repoId = ref('')
const ackHighRisk = ref(false)
const showHighRiskAck = ref(false)
const requestId = ref('')
const submitting = ref(false)
const errorMessage = ref<string | null>(null)

const selectedProfile = computed(() => props.profiles.find((p) => String(p.id) === profileId.value))

// 判断是否为高权限档位
const isHighRiskProfile = computed(() => {
  const p = selectedProfile.value
  if (!p) return false
  const cli = String(p.cli)
  return cli === 'agy' // agy auto / claude bypass / codex danger
})

watch(
  () => props.open,
  (val) => {
    if (val) {
      // 每次打开生成新的 request_id；同一打开会话内的重复点击使用相同 id 保持幂等
      requestId.value = crypto.randomUUID()
      errorMessage.value = null
      submitting.value = false
      ackHighRisk.value = false
      showHighRiskAck.value = false

      if (!profileId.value || !props.profiles.some((p) => String(p.id) === profileId.value)) {
        const available = props.profiles.find((p) => p.resolved?.ok) ?? props.profiles[0]
        profileId.value = available ? String(available.id) : ''
      }
      if (!repoId.value || !props.localRepos.some((r) => r.id === repoId.value)) {
        repoId.value = props.localRepos[0]?.id ?? ''
      }
    }
  },
)

async function submit() {
  if (submitting.value) return
  if (!profileId.value || !repoId.value) {
    errorMessage.value = '请选择 CLI 配置和本地仓库'
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
      kind: 'terminal',
      profile_id: profileId.value,
      repo_id: repoId.value,
      ack_high_risk: ackHighRisk.value,
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
      errorMessage.value = formatAiError(code, '创建终端会话失败，请稍后重试')
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Sheet
    :open="open"
    title="新建 AI 终端会话"
    description="在指定的本地代码仓库中启动 AI 命令行终端。"
    @update:open="emit('update:open', $event)"
  >
    <form class="new-session-form" data-testid="new-session-form" @submit.prevent="submit">
      <Banner v-if="errorMessage" kind="error" class="mb-3" data-testid="session-error-banner">
        {{ errorMessage }}
      </Banner>

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

      <div class="field-row">
        <span class="field-label">会话类型</span>
        <div class="field-control">
          <div class="kind-options">
            <label class="kind-option active">
              <input type="radio" name="session_kind" value="terminal" checked disabled />
              <span>终端（PTY）</span>
            </label>
            <label class="kind-option disabled" title="Chat 会话将在 S5-B 接入">
              <input type="radio" name="session_kind" value="chat" disabled />
              <span>对话（待 S5-B）</span>
            </label>
          </div>
        </div>
      </div>

      <div
        v-if="showHighRiskAck || isHighRiskProfile"
        class="high-risk-box"
        data-testid="high-risk-box"
      >
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
          <span>我已知晓并确认以高权限模式启动此终端会话</span>
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
            (selectedProfile && !selectedProfile.resolved?.ok)
          "
        >
          {{ submitting ? '创建中…' : '创建终端会话' }}
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
  padding: 4px 0;
}
.field-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.field-control {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.b-select {
  height: 32px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--text);
  padding: 0 8px;
  font-size: 13px;
  outline: none;
}
.b-select:focus {
  border-color: var(--accent);
}
.field-hint {
  font-size: 12px;
  color: var(--text-muted);
}
.field-hint.warn {
  color: #e07b00;
}
.no-repos-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-panel);
  border-radius: 6px;
  border: 1px dashed var(--line);
}
.repo-manage-link {
  display: flex;
  justify-content: flex-end;
}
.link-btn {
  background: none;
  border: none;
  color: var(--link);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}
.link-btn:hover {
  text-decoration: underline;
}
.kind-options {
  display: flex;
  gap: 12px;
}
.kind-option {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
}
.kind-option.disabled {
  color: var(--text-muted);
  cursor: not-allowed;
}
.high-risk-box {
  margin-top: 4px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.3);
}
.ack-checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text);
  cursor: pointer;
}
.sheet-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
</style>
