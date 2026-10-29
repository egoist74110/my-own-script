<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import { ApiError, errorText, type PlanResponse, type PlanTarget, type TaskOperation } from './api'

/** 确认单只用到配置名与路径；Git 规则来自命令所选的分支。 */
interface ConfirmSubject {
  name: string
  local_repo_path?: string
}

/** 命令所选分支的 Git 规则。 */
interface ConfirmBranch {
  build_branch?: string
  update_branches?: string[]
  merges?: Array<{ source: string; target: string }>
  push_branches?: string[]
}

const props = defineProps<{
  open: boolean
  task: ConfirmSubject | null
  /** 选中的运行命令名称；有则标题写成“配置名”的命令“命令名”。 */
  commandName?: string
  /** 命令所选分支；确认单的 Git 步骤按它的规则写。 */
  branch?: ConfirmBranch | null
  /** 命令的一句话概述（分支与目标），显示在计划上方。 */
  routeText?: string
  operation: TaskOperation
  plan: PlanResponse | null
  submitting?: boolean
  /** 预检请求进行中（plan 尚未返回）。 */
  loading?: boolean
  error?: unknown
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: [{ planId: string; requestId: string; ack: true }]
  /** 预检失败后重新预检。 */
  retry: []
  /** 去编辑当前发布配置（检查本地仓库路径等）。 */
  'open-config': []
}>()

const localRequestId = ref<string>('')

function getTarget(idx?: number | null): PlanTarget | undefined {
  if (idx === null || idx === undefined || !props.plan?.targets) return undefined
  return props.plan.targets[idx]
}

// 每次打开确认单，生成唯一且固定的 request_id；双击或重试保持同一个 request_id（幂等）
watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      localRequestId.value = crypto.randomUUID()
    }
  },
  { immediate: true },
)

const isDeployOnly = computed(() => props.operation === 'deploy_only')
const isRollback = computed(() => props.operation === 'rollback')

const missingCommit = computed(() => {
  if (isDeployOnly.value || isRollback.value) {
    if (!props.plan?.targets || props.plan.targets.length === 0) return true
    return props.plan.targets.some((t) => !t.commit)
  }
  return false
})

const subjectText = computed(() =>
  props.commandName ? `“${props.task?.name}”的命令“${props.commandName}”` : `“${props.task?.name}”`,
)
/** 预检失败：没有计划，且有错误。 */
const preflightFailed = computed(() => !props.plan && !props.loading && Boolean(props.error))
const errorCode = computed(() => (props.error instanceof ApiError ? props.error.code : ''))
/** 预检失败时：后端 message 原样展示；其他错误沿用统一文案。 */
const failureMessage = computed(() =>
  props.error instanceof ApiError && props.error.message
    ? props.error.message
    : errorText(props.error),
)
const failureHint = computed(() => {
  switch (errorCode.value) {
    case 'unsafe_repository':
    case 'unsupported_task':
      return '请打开配置，检查本地仓库路径和 origin 是否正确。'
    case 'ado_request_failed':
      return 'ADO 请求失败，请检查网络或 ADO 连接后重试。'
    case 'revision_conflict':
      return '配置刚刚被修改，已自动刷新。请重试。'
    case 'busy':
      return '系统繁忙，请稍后重试。'
    default:
      return '请重试；仍失败请检查配置。'
  }
})
const showConfigAction = computed(
  () => errorCode.value === 'unsafe_repository' || errorCode.value === 'unsupported_task',
)

/** “开始运行”不可点时的原因；可点时为空。 */
const disabledReason = computed(() => {
  if (props.submitting) return '正在启动，请稍候…'
  if (props.loading) return '正在检查，完成后才能运行'
  if (!props.plan) return '预检未通过，无法运行'
  if (missingCommit.value) return '计划未提供 commit，无法确认精确制品'
  return ''
})
const operationTitle = computed(() => {
  if (props.loading) return `正在检查${subjectText.value}…`
  if (preflightFailed.value)
    return `无法${actionWord.value}${subjectText.value}：${failureMessage.value}`
  if (isDeployOnly.value) return `只发布${subjectText.value}？`
  if (isRollback.value) return `回滚${subjectText.value}？`
  return `运行${subjectText.value}？`
})

const actionWord = computed(() =>
  isDeployOnly.value ? '发布' : isRollback.value ? '回滚' : '运行',
)
const operationNote = computed(() => {
  if (props.loading) return '正在检查仓库和 ADO，请稍候。'
  if (preflightFailed.value) return '预检未通过，没有执行任何推送或发布。'
  if (isDeployOnly.value) return '将只发布选定制品，不执行 Git 同步与构建代码。'
  if (isRollback.value) return '将重新部署指定历史 Release，不执行 Git 同步与构建。'
  return '将按下面的计划执行。推送和发布一旦开始无法撤回。'
})

function onConfirm() {
  if (props.submitting) return
  if (!props.plan?.plan_id || missingCommit.value) return
  emit('confirm', {
    planId: props.plan.plan_id,
    requestId: localRequestId.value,
    ack: true,
  })
}
</script>

<template>
  <Sheet
    :open="open"
    :title="operationTitle"
    :description="operationNote"
    @update:open="emit('update:open', $event)"
  >
    <div v-if="loading && !plan" class="confirm-body" data-testid="preflight-loading">
      <div class="loading-row"><span class="spinner" aria-hidden="true" />正在检查仓库和 ADO…</div>
    </div>

    <div v-else-if="preflightFailed" class="confirm-body" data-testid="preflight-failed">
      <Banner kind="error" class="plan-err" data-testid="plan-error-banner">
        <div data-testid="preflight-error-message">{{ failureMessage }}</div>
        <div class="err-hint" data-testid="preflight-error-hint">{{ failureHint }}</div>
        <template #actions>
          <Button
            v-if="showConfigAction"
            data-testid="preflight-open-config"
            @click="emit('open-config')"
            >打开配置检查本地仓库路径</Button
          >
          <Button data-testid="preflight-retry" @click="emit('retry')">
            {{ errorCode === 'busy' ? '稍后重试' : '重试' }}
          </Button>
        </template>
      </Banner>
    </div>

    <div v-else-if="plan" class="confirm-body" data-testid="run-confirm-sheet">
      <p v-if="routeText" class="confirm-route" data-testid="confirm-command-route">
        {{ routeText }}
      </p>
      <!-- 计划步骤列表 -->
      <ol class="plan-steps-list">
        <li v-for="(s, idx) in plan.steps" :key="idx" class="plan-step-item">
          <template v-if="s.kind === 'git'">
            同步 <span class="mono">{{ task?.local_repo_path }}</span
            >{{ branch?.build_branch ? `（${branch.build_branch} 分支）` : '' }}：更新
            {{ branch?.update_branches?.join(', ') || '—' }}，合并
            {{ branch?.merges?.map((m) => `${m.source} → ${m.target}`).join(', ') || '—' }}，推送
            {{ branch?.push_branches?.join(', ') || '—' }}
          </template>
          <template v-else-if="s.kind === 'build'">
            {{
              getTarget(s.target_index)
                ? `${getTarget(s.target_index)!.name}：构建定义 ${getTarget(s.target_index)!.definition_id}`
                : '构建步骤'
            }}
          </template>
          <template v-else-if="s.kind === 'release'">
            {{
              getTarget(s.target_index)
                ? `${getTarget(s.target_index)!.name}：Release 定义 ${getTarget(s.target_index)!.release_definition_id}`
                : '发布步骤'
            }}
          </template>
          <template v-else-if="s.kind === 'rollback'">
            {{
              getTarget(s.target_index)
                ? `${getTarget(s.target_index)!.name}：重新部署 Release #${getTarget(s.target_index)!.release_id}`
                : '回滚部署'
            }}
          </template>
        </li>
      </ol>

      <!-- 制品信息（只发布或回滚） -->
      <div v-if="isDeployOnly" class="artifact-box info-box">
        <span class="box-title">精确制品：</span>
        <span class="mono">
          {{
            plan.targets
              .map((t) => `${t.name}: #${t.build_id ?? ''} (${t.commit || '计划未提供 commit'})`)
              .join('；')
          }}
        </span>
        <div class="box-sub">发布此制品，不构建当前分支。</div>
      </div>

      <div v-if="isRollback" class="artifact-box warn-box">
        <span class="box-title">回滚目标制品：</span>
        <span class="mono">
          {{
            plan.targets
              .map(
                (t) =>
                  `${t.name}: Release #${t.release_id ?? ''} (${t.commit || '计划未提供 commit'})`,
              )
              .join('；')
          }}
        </span>
        <div class="box-sub">重部署此历史 Release，不执行 Git revert 或创建新 Release。</div>
      </div>

      <!-- 计划警告 -->
      <Banner v-if="plan.warnings?.length" kind="warn" class="plan-warn">
        <div v-for="(w, idx) in plan.warnings" :key="idx">{{ w }}</div>
      </Banner>

      <!-- 错误提示 -->
      <Banner v-if="error" kind="error" class="plan-err" data-testid="plan-error-banner">
        {{ errorText(error) }}
      </Banner>

      <div class="expiry-note">计划 5 分钟内有效</div>
    </div>

    <template #actions>
      <span v-if="disabledReason" class="disabled-reason" data-testid="confirm-disabled-reason">{{
        disabledReason
      }}</span>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="primary"
        data-testid="confirm-start-btn"
        :disabled="Boolean(disabledReason)"
        @click="onConfirm"
      >
        {{ submitting ? '启动中…' : '开始运行' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.loading-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--mute);
}
.spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--ink) 20%, transparent);
  border-top-color: var(--accent);
  animation: confirm-spin 0.8s linear infinite;
}
@keyframes confirm-spin {
  to {
    transform: rotate(360deg);
  }
}
.err-hint {
  margin-top: 4px;
  font-size: var(--text-sub);
}
.disabled-reason {
  margin-right: auto;
  font-size: 11px;
  color: var(--mute);
  align-self: center;
}
.confirm-route {
  margin: 0 0 8px;
  font-size: var(--text-sub);
  color: var(--mute);
  overflow-wrap: anywhere;
}
.confirm-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: var(--text-body);
}
.plan-steps-list {
  margin: 0;
  padding: 10px 14px 10px 28px;
  border-radius: var(--r-ctl);
  background: color-mix(in srgb, var(--ink) 3%, transparent);
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--text-sub);
}
.plan-step-item {
  color: var(--ink);
  line-height: 1.5;
}
.artifact-box {
  padding: 8px 10px;
  border-radius: var(--r-ctl);
  font-size: var(--text-sub);
}
.info-box {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
  color: var(--ink);
}
.warn-box {
  background: var(--bn-warn-bg);
  border: 1px solid var(--bn-warn-line);
  color: var(--bn-warn-fg);
}
.box-title {
  font-weight: 600;
}
.box-sub {
  margin-top: 2px;
  color: var(--mute);
  font-size: 11px;
}
.plan-warn,
.plan-err {
  margin-top: 2px;
}
.expiry-note {
  font-size: 11px;
  color: var(--mute);
  text-align: right;
}
.mono {
  font-family: var(--font-mono);
  word-break: break-all;
  user-select: text;
}
</style>
