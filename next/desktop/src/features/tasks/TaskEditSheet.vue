<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import TextField from '@/components/TextField.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import {
  errorText,
  type FlowInput,
  type TargetInput,
  type TaskCreate,
  type TaskPatch,
  type TaskView,
} from './api'

const props = defineProps<{
  open: boolean
  task: TaskView | null
  revision: number
  submitting?: boolean
  error?: unknown
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  save: [payload: TaskCreate | TaskPatch]
}>()

const isEdit = computed(() => Boolean(props.task))

// 表单字段
const name = ref('')
const enabled = ref(true)
const localRepoPath = ref('')
const projectId = ref('')
const repoName = ref('')
const buildBranch = ref('main')
const updateBranches = ref('')
const pushBranches = ref('')
const mergeRule = ref('')
const tgCommand = ref('')
const tgDesc = ref('')
const agentQueueId = ref('')

// 目标列表
interface EditableTarget {
  name: string
  enabled: boolean
  build_kind: 'pipeline' | 'build'
  build_id: string
  build_name: string
  release_id: string
  release_name: string
  release_stage_names: string
}

const targets = ref<EditableTarget[]>([])

function initForm() {
  if (props.task) {
    const t = props.task
    name.value = t.name ?? ''
    enabled.value = t.enabled ?? true
    localRepoPath.value = t.local_repo_path ?? ''
    projectId.value = t.project_id ?? ''
    repoName.value = t.repo_name ?? ''
    buildBranch.value = t.git_flow?.build_branch ?? 'main'
    updateBranches.value = t.git_flow?.update_branches?.join(', ') ?? ''
    pushBranches.value = t.git_flow?.push_branches?.join(', ') ?? ''
    mergeRule.value = t.git_flow?.merges?.map((m) => `${m.source}:${m.target}`).join(', ') ?? ''
    tgCommand.value = t.tg_command ?? ''
    tgDesc.value = t.tg_desc ?? ''
    agentQueueId.value = t.agent_queue_id ?? ''
    targets.value =
      t.targets?.map((tgt) => ({
        name: tgt.name ?? '目标',
        enabled: tgt.enabled ?? true,
        build_kind: (tgt.build_kind as 'pipeline' | 'build') ?? 'build',
        build_id: tgt.build_id ? String(tgt.build_id) : '',
        build_name: tgt.build_name ?? '',
        release_id: tgt.release_id ? String(tgt.release_id) : '',
        release_name: tgt.release_name ?? '',
        release_stage_names: tgt.release_stage_names?.join(', ') ?? '',
      })) ?? []
  } else {
    name.value = ''
    enabled.value = true
    localRepoPath.value = ''
    projectId.value = ''
    repoName.value = ''
    buildBranch.value = 'main'
    updateBranches.value = ''
    pushBranches.value = ''
    mergeRule.value = ''
    tgCommand.value = ''
    tgDesc.value = ''
    agentQueueId.value = ''
    targets.value = [
      {
        name: '目标 1',
        enabled: true,
        build_kind: 'build',
        build_id: '',
        build_name: '',
        release_id: '',
        release_name: '',
        release_stage_names: '',
      },
    ]
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) initForm()
  },
)

function addTarget() {
  targets.value.push({
    name: `目标 ${targets.value.length + 1}`,
    enabled: true,
    build_kind: 'build',
    build_id: '',
    build_name: '',
    release_id: '',
    release_name: '',
    release_stage_names: '',
  })
}

function removeTarget(idx: number) {
  targets.value.splice(idx, 1)
}

function parseList(s: string): string[] {
  return s
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
}

function parseMerges(s: string): Array<{ source: string; target: string }> {
  return s
    .split(',')
    .map((item) => {
      const parts = item.split(':').map((x) => x.trim())
      if (parts.length >= 2 && parts[0] && parts[1]) {
        return { source: parts[0], target: parts[1] }
      }
      return null
    })
    .filter((x): x is { source: string; target: string } => x !== null)
}

function onSubmit() {
  const gitFlow: FlowInput = {
    build_branch: buildBranch.value.trim() || 'main',
    update_branches: parseList(updateBranches.value),
    push_branches: parseList(pushBranches.value),
    merges: parseMerges(mergeRule.value),
  }

  const tgts: TargetInput[] = targets.value.map((t) => ({
    name: t.name.trim() || '目标',
    enabled: t.enabled,
    build_kind: t.build_kind,
    build_id: t.build_id.trim() || null,
    build_name: t.build_name.trim() || null,
    release_id: t.release_id.trim() || null,
    release_name: t.release_name.trim() || null,
    release_stage_names: parseList(t.release_stage_names),
  }))

  const payload: TaskCreate = {
    name: name.value.trim(),
    enabled: enabled.value,
    local_repo_path: localRepoPath.value.trim(),
    project_id: projectId.value.trim() || null,
    repo_name: repoName.value.trim() || null,
    sort_order: props.task?.sort_order ?? 0,
    git_flow: gitFlow,
    targets: tgts,
    tg_command: tgCommand.value.trim(),
    tg_desc: tgDesc.value.trim(),
    agent_queue_id: agentQueueId.value.trim() || null,
    revision: props.revision,
  }

  emit('save', payload)
}
</script>

<template>
  <Sheet
    :open="open"
    :title="isEdit ? '编辑任务' : '新建任务'"
    description="配置本地仓库、Git 流水线以及 ADO 构建与发布定义。"
    @update:open="emit('update:open', $event)"
  >
    <div class="edit-sheet-body" data-testid="task-edit-sheet">
      <Banner v-if="error" kind="error" class="mb-2" data-testid="task-edit-error">
        {{ errorText(error) }}
      </Banner>

      <form class="task-form" @submit.prevent="onSubmit">
        <!-- 基本信息 -->
        <div class="form-row">
          <TextField v-model="name" label="任务名称" placeholder="例如：web-portal 发布" required />
          <div class="switch-row">
            <span class="switch-label">启用任务</span>
            <Switch v-model:checked="enabled" />
          </div>
        </div>

        <div class="form-row">
          <TextField
            v-model="localRepoPath"
            label="本地仓库路径"
            placeholder="~/code/my-repo"
            required
          />
        </div>

        <div class="form-row two-cols">
          <TextField v-model="projectId" label="ADO 项目 ID" placeholder="project id" />
          <TextField v-model="repoName" label="远端仓库名" placeholder="repo name" />
        </div>

        <!-- Git 规则 -->
        <h4 class="form-sec-title">Git 流程</h4>
        <div class="form-row two-cols">
          <TextField v-model="buildBranch" label="构建分支" placeholder="main" required />
          <TextField
            v-model="updateBranches"
            label="更新分支 (逗号分隔)"
            placeholder="dev, release"
          />
        </div>
        <div class="form-row two-cols">
          <TextField
            v-model="mergeRule"
            label="合并规则 (源:目标)"
            placeholder="dev:main, feature:dev"
          />
          <TextField v-model="pushBranches" label="推送分支 (逗号分隔)" placeholder="main" />
        </div>

        <!-- 发布目标 -->
        <div class="targets-header">
          <h4 class="form-sec-title">发布目标</h4>
          <Button variant="default" type="button" @click="addTarget">＋ 添加目标</Button>
        </div>

        <div v-for="(tgt, idx) in targets" :key="idx" class="target-edit-box">
          <div class="target-edit-head">
            <span class="target-num">目标 #{{ idx + 1 }}</span>
            <div class="target-head-actions">
              <label class="inline-switch">
                <span>启用</span>
                <Switch v-model:checked="tgt.enabled" />
              </label>
              <Button
                v-if="targets.length > 1"
                variant="destructive"
                type="button"
                @click="removeTarget(idx)"
              >
                删除
              </Button>
            </div>
          </div>

          <div class="form-row two-cols">
            <TextField v-model="tgt.name" label="目标名称" placeholder="staging-a" required />
            <div class="fld">
              <label class="fld-lbl">类型</label>
              <select v-model="tgt.build_kind" class="sel-ctl">
                <option value="build">Build</option>
                <option value="pipeline">Pipeline</option>
              </select>
            </div>
          </div>

          <div class="form-row two-cols">
            <TextField
              v-model="tgt.build_id"
              label="构建定义 ID（文本输入）"
              placeholder="例如：12"
            />
            <TextField v-model="tgt.build_name" label="构建定义名" placeholder="可选显示名" />
          </div>

          <div class="form-row two-cols">
            <TextField
              v-model="tgt.release_id"
              label="Release 定义 ID（文本输入）"
              placeholder="例如：7"
            />
            <TextField
              v-model="tgt.release_stage_names"
              label="环境 Stage 名 (逗号分隔)"
              placeholder="QA, Staging"
            />
          </div>
        </div>

        <!-- Telegram -->
        <h4 class="form-sec-title">Telegram 触发（可选）</h4>
        <div class="form-row two-cols">
          <TextField v-model="tgCommand" label="TG 命令" placeholder="/deploy_portal" />
          <TextField v-model="tgDesc" label="TG 描述" placeholder="发布 Portal 到测试环境" />
        </div>
      </form>
    </div>

    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="primary"
        data-testid="save-task-btn"
        :disabled="submitting || !name || !localRepoPath"
        @click="onSubmit"
      >
        {{ submitting ? '保存中…' : '保存任务' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.edit-sheet-body {
  max-height: 65vh;
  overflow-y: auto;
  padding: 4px 2px;
}
.task-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.two-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
}
.switch-label {
  font-size: var(--text-body);
  color: var(--ink);
  font-weight: 500;
}
.form-sec-title {
  margin: 12px 0 4px;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  border-bottom: 1px solid var(--line);
  padding-bottom: 4px;
}
.targets-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.target-edit-box {
  padding: 10px;
  border-radius: var(--r-ctl);
  background: color-mix(in srgb, var(--ink) 2%, transparent);
  border: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.target-edit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.target-num {
  font-weight: 600;
  font-size: 12px;
  color: var(--mute);
}
.target-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.inline-switch {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.fld {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fld-lbl {
  font-size: var(--text-sub);
  color: var(--mute);
}
.sel-ctl {
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--ink);
  padding: 0 8px;
  font: inherit;
}
.mb-2 {
  margin-bottom: 8px;
}
</style>
