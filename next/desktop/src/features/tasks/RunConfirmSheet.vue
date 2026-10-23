<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import {
  errorText,
  type PlanResponse,
  type PlanTarget,
  type TaskOperation,
  type TaskView,
} from './api'

const props = defineProps<{
  open: boolean
  task: TaskView | null
  operation: TaskOperation
  plan: PlanResponse | null
  submitting?: boolean
  error?: unknown
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  confirm: [{ planId: string; requestId: string; ack: true }]
}>()

const ackIdle = ref(false)
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
      ackIdle.value = false
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

const operationTitle = computed(() => {
  if (isDeployOnly.value) return `只发布“${props.task?.name}”？`
  if (isRollback.value) return `回滚“${props.task?.name}”？`
  return `运行“${props.task?.name}”？`
})

const operationNote = computed(() => {
  if (isDeployOnly.value) return '将只发布选定制品，不执行 Git 同步与构建代码。'
  if (isRollback.value) return '将重新部署指定历史 Release，不执行 Git 同步与构建。'
  return '将按下面的计划执行。推送和发布一旦开始无法撤回。'
})

function onConfirm() {
  if (props.submitting) return
  if (!ackIdle.value || !props.plan?.plan_id || missingCommit.value) return
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
    <div v-if="plan" class="confirm-body" data-testid="run-confirm-sheet">
      <!-- 计划步骤列表 -->
      <ol class="plan-steps-list">
        <li v-for="(s, idx) in plan.steps" :key="idx" class="plan-step-item">
          <template v-if="s.kind === 'git'">
            同步 <span class="mono">{{ task?.local_repo_path }}</span
            >：更新 {{ task?.git_flow?.update_branches?.join(', ') || '—' }}，合并
            {{
              task?.git_flow?.merges?.map((m) => `${m.source} → ${m.target}`).join(', ') || '—'
            }}，推送 {{ task?.git_flow?.push_branches?.join(', ') || '—' }}
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
              .join(' · ')
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
              .join(' · ')
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

      <!-- 必选确认旧应用空闲勾选 -->
      <label class="ack-checkbox-label">
        <input
          v-model="ackIdle"
          type="checkbox"
          data-testid="ack-old-app-idle-checkbox"
          class="ack-checkbox"
        />
        <span class="ack-text">我已确认旧应用没有在运行同一个任务</span>
      </label>

      <div class="expiry-note">计划 5 分钟内有效</div>
    </div>

    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="primary"
        data-testid="confirm-start-btn"
        :disabled="!ackIdle || submitting || missingCommit"
        @click="onConfirm"
      >
        {{ submitting ? '启动中…' : '开始运行' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
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
.ack-checkbox-label {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 6px;
  cursor: pointer;
  user-select: none;
}
.ack-checkbox {
  margin-top: 2px;
  cursor: pointer;
}
.ack-text {
  font-size: var(--text-body);
  font-weight: 500;
  color: var(--ink);
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
