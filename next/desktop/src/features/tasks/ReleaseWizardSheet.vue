<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Check, ChevronDown, ChevronRight } from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import AdvancedFold from './AdvancedFold.vue'
import BranchPicker from './BranchPicker.vue'
import BranchRuleFields from './BranchRuleFields.vue'
import QueueSelect from './QueueSelect.vue'
import TargetManualFields from './TargetManualFields.vue'
import TargetAdder from './TargetAdder.vue'
import {
  discoverErrorText,
  discoverNeedsSettings,
  projectNotMatchedText,
  useDiscoverBranches,
  useDiscoverQueues,
  useDiscoverRepo,
  useDiscoverTargets,
} from './discover'
import {
  analyzeMerges,
  blankBranch,
  blankTarget,
  targetIsComplete,
  toBranchInput,
  toTargetInput,
  type EditableBranch,
  type EditableTarget,
} from './release-draft'
import {
  isRevisionConflict,
  releaseErrorText,
  unwrap,
  type CommandCreate,
  type ReleaseCreate,
} from './api'
import { QUERY_DEFAULTS, fetchReleaseConfig, useReleaseActions, useTasksApi } from './queries'

/**
 * 新建发布配置向导：只选不填。
 * 仓库 → 分支 → 发布目标 → Agent 队列 → 运行命令 → 确认，在同一个 Sheet 里分步完成。
 * 分支、目标、队列按步骤懒加载（走到那一步才请求）。目标的环境一律默认不勾选。
 * 保存先建配置、再逐条建命令；配置已建而命令没建完时停在确认页，只重试没建好的命令，不会重复建配置。
 * 手填入口（项目/仓库编号、手动分支、手动目标、队列编号）都收在默认收起的“高级”里。
 */
const props = defineProps<{
  open: boolean
  /** 配置列表当前的版本（乐观锁）。 */
  revision: number
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  /** 配置已创建（命令可能还没建完）：页面据此选中新配置。 */
  created: [id: string]
  /** 用户选择去编辑这个仓库已有的配置。 */
  'edit-existing': [id: string]
}>()

const router = useRouter()
const { api, qc, online } = useTasksApi()
const actions = useReleaseActions()

type StepKey = 'repo' | 'branches' | 'targets' | 'queue' | 'commands' | 'confirm'
const STEPS: Array<{ key: StepKey; label: string }> = [
  { key: 'repo', label: '仓库' },
  { key: 'branches', label: '分支' },
  { key: 'targets', label: '发布目标' },
  { key: 'queue', label: 'Agent 队列' },
  { key: 'commands', label: '运行命令' },
  { key: 'confirm', label: '确认' },
]
const step = ref<StepKey>('repo')
const stepIdx = computed(() => STEPS.findIndex((s) => s.key === step.value))
/** 走到过的最远一步：决定哪些发现接口可以开始请求。 */
const maxStep = ref(0)

// ───────────── 第 1 步：仓库 ─────────────

const adoQ = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: ['settings', 'ado'],
  enabled: computed(() => online.value && props.open),
  queryFn: ({ signal }) => unwrap(api().GET('/api/ado', { signal })),
})
const localRepos = computed(() => adoQ.data.value?.local_repos ?? [])

const pathInput = ref('')
/** 最近一次发起识别时的路径：输入变了就要重新识别。 */
const requestedPath = ref('')
const repoMut = useDiscoverRepo()
const found = computed(() => repoMut.data.value ?? null)
const pathDirty = computed(() => pathInput.value.trim() !== requestedPath.value)
const discoveredOk = computed(
  () => Boolean(found.value?.project_id && found.value?.repo_id) && !pathDirty.value,
)
const repoAdvancedOpen = ref(false)
const manualProjectId = ref('')
const manualRepoId = ref('')
const manualRepoName = ref('')

const effPath = computed(() =>
  discoveredOk.value ? (found.value?.local_repo_path ?? '') : pathInput.value.trim(),
)
const pid = computed(() =>
  discoveredOk.value ? (found.value?.project_id ?? '') : manualProjectId.value.trim(),
)
const rid = computed(() =>
  discoveredOk.value ? (found.value?.repo_id ?? '') : manualRepoId.value.trim(),
)
const effRepoName = computed(() =>
  discoveredOk.value ? (found.value?.repo_name ?? '') : manualRepoName.value.trim(),
)
const canDiscover = computed(() => Boolean(pid.value && rid.value))

function runDiscover(path: string) {
  const p = path.trim()
  if (!p || repoMut.isPending.value || created.value) return
  pathInput.value = p
  requestedPath.value = p
  repoMut.mutate(p, {
    onSuccess: (res) => {
      // 来源变了：旧的分支/目标/队列候选和选择全部作废
      resetDownstream()
      if (!nameTouched.value) name.value = res.suggested_name || res.repo_name || ''
    },
    onError: () => resetDownstream(),
  })
}

function gotoSettings() {
  emit('update:open', false)
  void router.push('/settings')
}

// ───────────── 第 2 步：分支 ─────────────

const branchSel = ref<string[]>([])
const branchTouched = ref(false)
const extraBranches = ref<string[]>([])
const extraBranchInput = ref('')
const rules = reactive<Record<string, EditableBranch>>({})
const rulesOpen = reactive<Record<string, boolean>>({})

const branchesQ = useDiscoverBranches(
  pid,
  rid,
  computed(() => maxStep.value >= 1),
)
const branchList = computed(() => {
  const base = branchesQ.data.value?.branches ?? []
  return [...base, ...extraBranches.value.filter((b) => !base.includes(b))]
})

// 默认勾选默认分支（用户没动过时）
watch(
  () => branchesQ.data.value,
  (d) => {
    if (!d || branchTouched.value || branchSel.value.length > 0) return
    const def = d.default_branch || found.value?.default_branch || null
    if (def && d.branches.includes(def)) branchSel.value = [def]
  },
)
watch(
  branchSel,
  (names) => {
    for (const n of names) {
      if (!rules[n]) rules[n] = blankBranch(n, false)
    }
  },
  { immediate: true, deep: true },
)
function onBranchSelChange(v: string[]) {
  branchTouched.value = true
  branchSel.value = v
}
function addExtraBranch() {
  const n = extraBranchInput.value.trim()
  if (!n) return
  if (!branchList.value.includes(n)) extraBranches.value.push(n)
  if (!branchSel.value.includes(n)) onBranchSelChange([...branchSel.value, n])
  extraBranchInput.value = ''
}
const badMergesByBranch = computed(() => {
  const m = new Map<string, string[]>()
  for (const n of branchSel.value) {
    const { bad } = analyzeMerges(rules[n]?.merges ?? '')
    if (bad.length) m.set(n, bad)
  }
  return m
})

// ───────────── 第 3 步：发布目标 ─────────────

/** 表单式添加进来的目标（可改名、可删）。 */
const addedTargets = ref<EditableTarget[]>([])
const manualTargets = ref<EditableTarget[]>([])
const targetsAdvancedOpen = ref(false)
const targetsQ = useDiscoverTargets(
  pid,
  rid,
  computed(() => maxStep.value >= 2),
)

function manualTargetValid(t: EditableTarget): boolean {
  return Boolean(t.name.trim()) && targetIsComplete(t)
}
/** 最终要加入配置的目标：勾了环境的建议 + 手填且填完整的目标。 */
/** 手填但还不完整的目标：挡住“下一步”，不会被悄悄丢掉或带进保存。 */
const manualIncomplete = computed(() => manualTargets.value.some((t) => !manualTargetValid(t)))
const allTargets = computed<EditableTarget[]>(() => [
  ...addedTargets.value,
  ...manualTargets.value.filter(manualTargetValid),
])
function addTargetFromAdder(t: EditableTarget) {
  addedTargets.value.push(t)
}
function removeAddedTarget(i: number) {
  addedTargets.value.splice(i, 1)
}
/** 目标名称不能为空、不能重名（命令草稿按目标名展示）。 */
const targetNameProblem = computed(() => {
  const seen = new Set<string>()
  for (const t of allTargets.value) {
    const n = t.name.trim()
    if (!n) return '有目标没有名称'
    if (seen.has(n)) return `目标名称“${n}”重复了`
    seen.add(n)
  }
  return null
})
function addManualTarget() {
  manualTargets.value.push(blankTarget(manualTargets.value.length + 1))
}
function removeManualTarget(idx: number) {
  manualTargets.value.splice(idx, 1)
}

// ───────────── 第 4 步：Agent 队列 ─────────────

const queueId = ref('')
const queueName = ref('')
const queueAdvancedOpen = ref(false)
const queuesQ = useDiscoverQueues(
  pid,
  computed(() => maxStep.value >= 3),
)

// ───────────── 第 5 步：运行命令草稿 ─────────────

interface CommandDraft {
  key: string
  branch: string
  targetKey: string
  targetName: string
  include: boolean
  name: string
  /** 用户改过名字后，不再随目标改名自动更新。 */
  touched: boolean
  tgCommand: string
}
const drafts = ref<CommandDraft[]>([])

function defaultCommandName(branch: string, targetName: string): string {
  return `${branch} → ${targetName}`
}

/** 每个勾选分支 × 每个已选目标一条草稿；已有草稿（含用户的改名、取消勾选）按键保留。 */
function syncDrafts() {
  const old = new Map(drafts.value.map((d) => [d.key, d]))
  const next: CommandDraft[] = []
  for (const b of branchSel.value) {
    for (const t of allTargets.value) {
      const key = `${b}\u0000${t.key}`
      const prev = old.get(key)
      next.push({
        key,
        branch: b,
        targetKey: t.key,
        targetName: t.name.trim() || '目标',
        include: prev?.include ?? true,
        name: prev && prev.touched ? prev.name : defaultCommandName(b, t.name.trim() || '目标'),
        touched: prev?.touched ?? false,
        tgCommand: prev?.tgCommand ?? '',
      })
    }
  }
  drafts.value = next
}
function onDraftName(d: CommandDraft, v: string) {
  d.name = v
  d.touched = true
}
const includedDrafts = computed(() => drafts.value.filter((d) => d.include))
const draftsValid = computed(
  () => includedDrafts.value.length > 0 && includedDrafts.value.every((d) => d.name.trim()),
)

// ───────────── 第 6 步：确认与保存 ─────────────

const name = ref('')
const nameTouched = ref(false)
function onName(v: string) {
  name.value = v
  nameTouched.value = true
}

interface Created {
  configId: string
  revision: number
  /** 分支名 → 分支 id；刚建完还没读回时为 null。 */
  branchIds: Record<string, string> | null
  /** 目标键 → 目标 id。 */
  targetIds: Record<string, string> | null
}
const created = ref<Created | null>(null)
/** 已经建成功的命令草稿键。 */
const doneKeys = ref<string[]>([])
const saving = ref(false)
const saveError = ref<unknown>(null)

const pendingDrafts = computed(() =>
  includedDrafts.value.filter((d) => !doneKeys.value.includes(d.key)),
)
const partial = computed(() => Boolean(created.value) && Boolean(saveError.value))

function buildCreatePayload(): ReleaseCreate {
  return {
    name: name.value.trim(),
    local_repo_path: effPath.value,
    project_id: pid.value || null,
    repo_id: rid.value || null,
    repo_name: effRepoName.value || null,
    sort_order: 0,
    branches: branchSel.value.map((n) => toBranchInput(rules[n] ?? blankBranch(n, false))),
    agent_queue_id: queueId.value.trim() || null,
    agent_queue_name: queueName.value.trim() || null,
    targets: allTargets.value.map(toTargetInput),
    revision: props.revision,
  }
}

/** 配置建好后读回服务端生成的分支/目标 id 和最新版本，命令靠它们关联。 */
async function ensureIds(c: Created) {
  if (c.branchIds && c.targetIds) return
  const fresh = await fetchReleaseConfig(qc, api, c.configId)
  c.revision = fresh.revision
  // 按内容匹配服务端返回的分支/目标，不依赖返回顺序；匹配不唯一就报错，绝不猜
  const branchIds: Record<string, string> = {}
  for (const n of branchSel.value) {
    const hits = (fresh.item.branches ?? []).filter((b) => b.build_branch === n)
    if (hits.length !== 1)
      throw new Error(
        `新配置里分支“${n}”匹配到 ${hits.length} 个，无法确定对应关系，请到配置里手动添加命令`,
      )
    branchIds[n] = hits[0]!.id
  }
  const targetIds: Record<string, string> = {}
  for (const t of allTargets.value) {
    const hits = (fresh.item.targets ?? []).filter(
      (g) =>
        String(g.build_id ?? '') === t.build_id.trim() &&
        String(g.release_id ?? '') === t.release_id.trim() &&
        g.name === t.name.trim(),
    )
    if (hits.length !== 1)
      throw new Error(
        `新配置里目标“${t.name.trim()}”匹配到 ${hits.length} 个，无法确定对应关系，请到配置里手动添加命令`,
      )
    targetIds[t.key] = hits[0]!.id
  }
  c.branchIds = branchIds
  c.targetIds = targetIds
}

async function save() {
  if (saving.value) return
  saving.value = true
  saveError.value = null
  try {
    if (!created.value) {
      const res = await actions.createConfig(buildCreatePayload())
      if (!res.id) throw new Error('后端没有返回新配置的编号，请在列表里确认是否已创建')
      created.value = { configId: res.id, revision: res.revision, branchIds: null, targetIds: null }
      emit('created', res.id)
    }
    const c = created.value
    await ensureIds(c)
    for (const [i, d] of pendingDrafts.value.entries()) {
      const branchId = c.branchIds?.[d.branch]
      const targetId = c.targetIds?.[d.targetKey]
      if (!branchId || !targetId)
        throw new Error(`没有在新配置里找到“${d.name}”对应的分支或目标，请到配置里手动添加这条命令`)
      const body: CommandCreate = {
        name: d.name.trim(),
        tg_command: d.tgCommand.trim(),
        tg_desc: '',
        enabled: true,
        branch_id: branchId,
        sort_order: doneKeys.value.length + i,
        target_ids: [targetId],
        revision: c.revision,
      }
      const res = await actions.createCommand(c.configId, body)
      c.revision = res.revision
      doneKeys.value.push(d.key)
    }
    emit('update:open', false)
  } catch (e) {
    saveError.value = e
    const c = created.value
    if (c && isRevisionConflict(e)) {
      // 版本冲突：读回最新版本，下次重试用它
      try {
        c.revision = (await fetchReleaseConfig(qc, api, c.configId)).revision
      } catch {
        /* 读不到就保留旧版本，重试时会再次提示 */
      }
    }
  } finally {
    saving.value = false
  }
}

const errorText = computed(() => releaseErrorText(saveError.value))

// ───────────── 步骤导航 ─────────────

const stepOk = computed<Record<StepKey, boolean>>(() => ({
  repo:
    !repoMut.isPending.value &&
    (discoveredOk.value || (repoAdvancedOpen.value && Boolean(pathInput.value.trim()))),
  branches: branchSel.value.length > 0 && badMergesByBranch.value.size === 0,
  targets:
    allTargets.value.length > 0 && !manualIncomplete.value && targetNameProblem.value === null,
  queue: true,
  commands: draftsValid.value,
  confirm: Boolean(name.value.trim()),
}))

const nextBlockedHint = computed(() => {
  switch (step.value) {
    case 'repo':
      return repoMut.isPending.value ? '' : '先选一个仓库并识别，或展开“高级”手动填写。'
    case 'branches':
      return badMergesByBranch.value.size > 0
        ? '有分支的合并规则格式不对，改好后才能继续。'
        : '至少勾选一个分支。'
    case 'targets':
      return manualIncomplete.value
        ? '有手动目标没填完整（要有名称、构建定义 ID、Release 定义 ID 和至少一个环境 ID），补全或删除后才能继续。'
        : targetNameProblem.value
          ? `${targetNameProblem.value}，改好后才能继续。`
          : '至少添加一个目标（勾选环境后点“添加这个目标”），才能继续。'
    case 'commands':
      return '至少保留一条命令，并且每条都要有名称。'
    default:
      return ''
  }
})

/** 配置建好后，只允许回到“运行命令”修没建成的命令，前面的步骤已经落库，不能再改。 */
const canBack = computed(() => {
  if (saving.value) return false
  if (stepIdx.value === 0) return false
  if (created.value) return step.value === 'confirm'
  return true
})

function goNext() {
  if (!stepOk.value[step.value]) return
  const next = STEPS[stepIdx.value + 1]
  if (!next) return
  if (next.key === 'commands') syncDrafts()
  step.value = next.key
  maxStep.value = Math.max(maxStep.value, stepIdx.value)
}
function goBack() {
  if (!canBack.value) return
  const prev = STEPS[stepIdx.value - 1]
  if (prev) step.value = prev.key
}

// 来源变化：清掉依赖仓库的所有选择
function resetDownstream() {
  maxStep.value = Math.min(maxStep.value, 0)
  branchSel.value = []
  branchTouched.value = false
  extraBranches.value = []
  for (const k of Object.keys(rules)) delete rules[k]
  for (const k of Object.keys(rulesOpen)) delete rulesOpen[k]
  addedTargets.value = []
  manualTargets.value = []
  queueId.value = ''
  queueName.value = ''
  drafts.value = []
}

function initWizard() {
  step.value = 'repo'
  maxStep.value = 0
  pathInput.value = ''
  requestedPath.value = ''
  repoMut.reset()
  repoAdvancedOpen.value = false
  manualProjectId.value = ''
  manualRepoId.value = ''
  manualRepoName.value = ''
  extraBranchInput.value = ''
  targetsAdvancedOpen.value = false
  queueAdvancedOpen.value = false
  name.value = ''
  nameTouched.value = false
  created.value = null
  doneKeys.value = []
  saving.value = false
  saveError.value = null
  resetDownstream()
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) initWizard()
  },
  { immediate: true },
)

function envNames(t: EditableTarget): string[] {
  return (t.release_stage_names.trim() ? t.release_stage_names : t.release_stage_ids)
    .split(/[,，、\n\r]+/)
    .map((x) => x.trim())
    .filter(Boolean)
}
function branchRuleSummary(n: string): string {
  const r = rules[n]
  if (!r) return '不更新、不合并、不推送'
  const parts = [
    r.update_branches.trim() && `更新 ${r.update_branches.trim()}`,
    r.merges.trim() && `合并 ${r.merges.trim()}`,
    r.push_branches.trim() && `推送 ${r.push_branches.trim()}`,
  ].filter(Boolean)
  return parts.length ? parts.join('，') : '不更新、不合并、不推送'
}
</script>

<template>
  <Sheet
    :open="open"
    wide
    title="新建发布配置"
    description="选好仓库、分支和要发布的环境，其余编号由程序自动识别。"
    @update:open="emit('update:open', $event)"
  >
    <div class="wz" data-testid="release-wizard">
      <!-- 步骤条 -->
      <ol class="wz-steps" aria-label="新建步骤">
        <li
          v-for="(s, i) in STEPS"
          :key="s.key"
          class="wz-step"
          :data-state="i < stepIdx ? 'done' : i === stepIdx ? 'current' : 'todo'"
          :aria-current="i === stepIdx ? 'step' : undefined"
          :data-testid="`wizard-stepper-${s.key}`"
        >
          <span class="wz-dot">
            <Check v-if="i < stepIdx" :size="11" aria-hidden="true" />
            <template v-else>{{ i + 1 }}</template>
          </span>
          <span class="wz-step-name">{{ s.label }}</span>
        </li>
      </ol>

      <div class="wz-body">
        <!-- 1. 仓库 -->
        <section v-if="step === 'repo'" class="wz-sec" data-testid="wizard-step-repo">
          <h4 class="sec-title">选择本地仓库</h4>
          <p class="hint">点选设置里登记过的本地仓库，程序会读取它的远端地址并匹配 ADO 项目。</p>

          <p v-if="adoQ.isPending.value && online" class="hint" role="status">
            正在读取已登记的本地仓库…
          </p>
          <Banner v-else-if="adoQ.error.value" kind="warn" data-testid="wizard-repos-error">
            读不到已登记的本地仓库。仍然可以在下面直接输入仓库路径。
            <template #actions><Button @click="adoQ.refetch()">重试</Button></template>
          </Banner>
          <p v-else-if="localRepos.length === 0" class="hint" data-testid="wizard-repos-empty">
            设置里还没有登记本地仓库。可以直接在下面输入仓库路径，或先去设置里登记。
          </p>
          <ul v-else class="repo-list" aria-label="已登记的本地仓库">
            <li v-for="r in localRepos" :key="r.id">
              <button
                type="button"
                class="repo-btn"
                :data-selected="pathInput.trim() === r.path ? 'true' : 'false'"
                :disabled="!r.exists || repoMut.isPending.value || Boolean(created)"
                :data-testid="`wizard-local-repo-${r.id}`"
                @click="runDiscover(r.path)"
              >
                <span class="repo-name">{{ r.name }}</span>
                <span class="repo-path mono">{{ r.path }}</span>
                <Tag v-if="!r.exists" tone="warn">路径不存在</Tag>
              </button>
            </li>
          </ul>

          <form class="path-row" @submit.prevent="runDiscover(pathInput)">
            <div class="fld grow">
              <span class="fld-lbl">其他路径</span>
              <TextField
                v-model="pathInput"
                label="其他仓库路径"
                placeholder="~/code/my-repo"
                data-testid="wizard-path-input"
              />
            </div>
            <Button
              type="submit"
              data-testid="wizard-discover-btn"
              :disabled="repoMut.isPending.value || !pathInput.trim()"
            >
              {{ repoMut.isPending.value ? '识别中…' : '识别' }}
            </Button>
          </form>

          <Banner v-if="repoMut.error.value" kind="error" data-testid="wizard-discover-error">
            {{ discoverErrorText(repoMut.error.value) }}
            <template #actions>
              <Button v-if="discoverNeedsSettings(repoMut.error.value)" @click="gotoSettings"
                >去设置</Button
              >
              <Button v-else :disabled="repoMut.isPending.value" @click="runDiscover(pathInput)"
                >重试</Button
              >
            </template>
          </Banner>

          <template v-if="found && !pathDirty">
            <Banner
              v-if="!found.project_id"
              kind="warn"
              title="没有匹配到 ADO 项目"
              data-testid="wizard-not-matched"
            >
              {{ projectNotMatchedText() }}
              <template #actions>
                <Button data-testid="wizard-goto-settings" @click="gotoSettings">去设置</Button>
                <Button @click="repoAdvancedOpen = true">高级：手动填写</Button>
              </template>
            </Banner>
            <div v-else class="result" data-testid="wizard-repo-result">
              <p class="result-line"><span class="k">ADO 项目</span>{{ found.project_label }}</p>
              <p class="result-line"><span class="k">仓库</span>{{ found.repo_name }}</p>
              <p class="result-line">
                <span class="k">默认分支</span>{{ found.default_branch || '未设置' }}
              </p>
              <p class="result-line">
                <span class="k">远端</span><span class="mono">{{ found.remote_url }}</span>
              </p>
            </div>
            <p v-if="!found.project_id" class="hint mono">远端：{{ found.remote_url }}</p>
            <Banner
              v-if="found.existing_config_id"
              kind="info"
              title="这个仓库已有配置"
              data-testid="wizard-existing-config"
            >
              同一个仓库已经建过发布配置。可以去编辑它，也可以继续新建一份。
              <template #actions>
                <Button
                  data-testid="wizard-edit-existing-btn"
                  @click="emit('edit-existing', found.existing_config_id!)"
                >
                  去编辑已有配置
                </Button>
              </template>
            </Banner>
          </template>

          <AdvancedFold
            v-model:open="repoAdvancedOpen"
            title="高级：手动填写"
            data-testid="wizard-advanced-repo"
          >
            <p class="hint">
              识别不了时可以只用路径继续，也可以直接填 ADO 的项目 ID 与仓库
              ID（填了之后仍可读取分支和目标）。
            </p>
            <div class="two-cols">
              <div class="fld">
                <span class="fld-lbl">ADO 项目 ID</span>
                <TextField v-model="manualProjectId" label="ADO 项目 ID" placeholder="project id" />
              </div>
              <div class="fld">
                <span class="fld-lbl">远端仓库名</span>
                <TextField v-model="manualRepoName" label="远端仓库名" placeholder="repo name" />
              </div>
            </div>
            <div class="fld">
              <span class="fld-lbl">远端仓库 ID</span>
              <TextField v-model="manualRepoId" label="远端仓库 ID" placeholder="repo id" />
            </div>
          </AdvancedFold>
        </section>

        <!-- 2. 分支 -->
        <section v-else-if="step === 'branches'" class="wz-sec" data-testid="wizard-step-branches">
          <h4 class="sec-title">选择要发布的分支</h4>
          <p class="hint">
            勾选的每个分支会生成一份分支配置。默认只勾选仓库的默认分支；Git
            规则默认全空（不更新、不合并、不推送）。
          </p>
          <p
            v-if="branchesQ.isFetching.value"
            class="hint"
            role="status"
            data-testid="wizard-branches-loading"
          >
            正在读取远端分支…
          </p>
          <Banner
            v-else-if="branchesQ.error.value"
            kind="error"
            data-testid="wizard-branches-error"
          >
            {{ discoverErrorText(branchesQ.error.value) }}
            <template #actions>
              <Button @click="branchesQ.refetch()">重试</Button>
            </template>
          </Banner>
          <p v-else-if="!canDiscover" class="hint" data-testid="wizard-branches-manual">
            没有关联到 ADO 仓库，读不到远端分支。请在下面直接输入分支名。
          </p>
          <BranchPicker
            v-if="branchList.length > 0"
            :model-value="branchSel"
            :branches="branchList"
            :default-branch="branchesQ.data.value?.default_branch ?? found?.default_branch"
            @update:model-value="onBranchSelChange"
          />
          <form class="path-row" @submit.prevent="addExtraBranch">
            <div class="fld grow">
              <span class="fld-lbl">添加其他分支（手动输入分支名）</span>
              <TextField
                v-model="extraBranchInput"
                label="手动输入分支名"
                placeholder="release/1.0"
              />
            </div>
            <Button
              type="submit"
              data-testid="wizard-add-extra-branch"
              :disabled="!extraBranchInput.trim()"
            >
              添加
            </Button>
          </form>

          <h4 v-if="branchSel.length > 0" class="sec-title">已选 {{ branchSel.length }} 个分支</h4>
          <ul class="sel-list">
            <li v-for="n in branchSel" :key="n" class="sel-box" :data-testid="`wizard-branch-${n}`">
              <button
                type="button"
                class="branch-toggle"
                :aria-expanded="Boolean(rulesOpen[n])"
                :data-testid="`wizard-rules-toggle-${n}`"
                @click="rulesOpen[n] = !rulesOpen[n]"
              >
                <component
                  :is="rulesOpen[n] ? ChevronDown : ChevronRight"
                  :size="14"
                  aria-hidden="true"
                />
                <span class="mono">{{ n }}</span>
                <span class="hint">Git 规则：{{ branchRuleSummary(n) }}</span>
              </button>
              <BranchRuleFields
                v-if="rulesOpen[n] && rules[n]"
                v-model="rules[n]!"
                :label-prefix="`分支 ${n}`"
                :testid-prefix="`wbranch-${n}`"
                :options="branchList"
                :loading="branchesQ.isFetching.value"
              />
            </li>
          </ul>
        </section>

        <!-- 3. 发布目标 -->
        <section v-else-if="step === 'targets'" class="wz-sec" data-testid="wizard-step-targets">
          <h4 class="sec-title">选择发布目标</h4>
          <p class="hint">
            先选构建定义，再选 Release
            定义，勾选要发布到的环境（默认都不勾，至少勾一个；尤其留意正式环境），点“添加这个目标”。同一个构建和
            Release 可以添加多次，环境不同即可。
          </p>
          <p
            v-if="targetsQ.isFetching.value"
            class="hint"
            role="status"
            data-testid="wizard-targets-loading"
          >
            正在读取构建与 Release 定义…
          </p>
          <Banner v-else-if="targetsQ.error.value" kind="error" data-testid="wizard-targets-error">
            {{ discoverErrorText(targetsQ.error.value) }}
            <template #actions>
              <Button @click="targetsQ.refetch()">重试</Button>
            </template>
          </Banner>
          <p v-else-if="!canDiscover" class="hint" data-testid="wizard-targets-manual">
            没有关联到 ADO 仓库，读不到目标。请展开下面的“高级”手动填写。
          </p>
          <TargetAdder
            v-else-if="targetsQ.data.value"
            :data="targetsQ.data.value"
            :existing="allTargets"
            @add="addTargetFromAdder"
          />

          <h4 v-if="allTargets.length > 0" class="sec-title">已加入的目标</h4>
          <ul class="sel-list">
            <li
              v-for="(t, i) in addedTargets"
              :key="t.key"
              class="sel-box"
              :data-testid="`wizard-added-target-${i}`"
            >
              <div class="sel-head">
                <TextField
                  v-model="t.name"
                  :label="`已加入目标 ${i + 1} 名称`"
                  placeholder="目标名称"
                />
                <Button
                  variant="destructive"
                  :data-testid="`wizard-remove-target-${i}`"
                  @click="removeAddedTarget(i)"
                  >删除</Button
                >
              </div>
              <p class="hint">
                构建定义：{{ t.build_name || t.build_id }}，Release 定义：{{
                  t.release_name || t.release_id
                }}
              </p>
              <span class="env-tags">
                <Tag v-for="e in envNames(t)" :key="e">{{ e }}</Tag>
              </span>
            </li>
          </ul>
          <p v-if="targetNameProblem" class="need" role="alert">{{ targetNameProblem }}</p>

          <AdvancedFold
            v-model:open="targetsAdvancedOpen"
            title="高级：手动填写目标"
            data-testid="wizard-advanced-targets"
          >
            <div v-for="(t, i) in manualTargets" :key="t.key" class="sel-box">
              <div class="sel-head">
                <span class="k">手动目标 {{ i + 1 }}</span>
                <Button variant="destructive" @click="removeManualTarget(i)">删除</Button>
              </div>
              <TargetManualFields v-model="manualTargets[i]!" show-name />
              <p v-if="!manualTargetValid(t)" class="need">
                要填目标名称、构建定义 ID、Release 定义 ID 和至少一个环境 ID，才会加入。
              </p>
            </div>
            <div>
              <Button data-testid="wizard-add-manual-target" @click="addManualTarget">
                手动添加目标
              </Button>
            </div>
          </AdvancedFold>
          <p class="hint" data-testid="wizard-targets-count">
            已加入 {{ allTargets.length }} 个目标。
          </p>
        </section>

        <!-- 4. Agent 队列 -->
        <section v-else-if="step === 'queue'" class="wz-sec" data-testid="wizard-step-queue">
          <h4 class="sec-title">选择 Agent 队列</h4>
          <p class="hint">构建用哪个 Agent 队列。可以选“不指定”，由流水线自己决定。</p>
          <QueueSelect
            v-if="pid"
            v-model:queue-id="queueId"
            v-model:queue-name="queueName"
            :queues="queuesQ.data.value?.queues"
            :loading="queuesQ.isFetching.value"
            :error="queuesQ.error.value"
            @retry="queuesQ.refetch()"
          />
          <p v-else class="hint" data-testid="wizard-queue-manual">
            没有关联到 ADO 项目，读不到队列。可留空，或展开下面的“高级”手动填写。
          </p>
          <AdvancedFold
            v-model:open="queueAdvancedOpen"
            title="高级：手动填写"
            data-testid="wizard-advanced-queue"
          >
            <div class="two-cols">
              <div class="fld">
                <span class="fld-lbl">Agent 队列 ID</span>
                <TextField v-model="queueId" label="Agent 队列 ID" placeholder="可选" />
              </div>
              <div class="fld">
                <span class="fld-lbl">队列名称</span>
                <TextField v-model="queueName" label="队列名称" placeholder="可选" />
              </div>
            </div>
          </AdvancedFold>
        </section>

        <!-- 5. 运行命令 -->
        <section v-else-if="step === 'commands'" class="wz-sec" data-testid="wizard-step-commands">
          <h4 class="sec-title">运行命令</h4>
          <p class="hint">
            每个分支配每个目标预生成一条命令。可以改名、取消不要的，至少保留一条。TG
            命令名可留空，需要从 Telegram 触发时再填。
          </p>
          <ul class="sel-list">
            <li
              v-for="(d, i) in drafts"
              :key="d.key"
              class="sel-box"
              :data-included="d.include ? 'true' : 'false'"
              :data-testid="`wizard-draft-${i}`"
            >
              <label class="inc">
                <input
                  v-model="d.include"
                  type="checkbox"
                  :disabled="doneKeys.includes(d.key)"
                  :data-testid="`wizard-draft-include-${i}`"
                />
                <span>生成这条命令</span>
                <Tag v-if="doneKeys.includes(d.key)" tone="ok">已创建</Tag>
              </label>
              <div class="two-cols">
                <div class="fld">
                  <span class="fld-lbl">命令名称</span>
                  <TextField
                    :model-value="d.name"
                    :label="`命令 ${i + 1} 名称`"
                    :disabled="!d.include || doneKeys.includes(d.key)"
                    @update:model-value="onDraftName(d, $event)"
                  />
                </div>
                <div class="fld">
                  <span class="fld-lbl">TG 命令名（可选）</span>
                  <TextField
                    v-model="d.tgCommand"
                    :label="`命令 ${i + 1} TG 命令名`"
                    placeholder="留空则不从 Telegram 触发"
                    :disabled="!d.include || doneKeys.includes(d.key)"
                  />
                </div>
              </div>
            </li>
          </ul>
          <p
            v-if="includedDrafts.length === 0"
            class="need"
            role="alert"
            data-testid="wizard-drafts-none"
          >
            至少保留一条命令。
          </p>
          <p v-else-if="!draftsValid" class="need" role="alert">每条保留的命令都要有名称。</p>
        </section>

        <!-- 6. 确认 -->
        <section v-else class="wz-sec" data-testid="wizard-step-confirm">
          <h4 class="sec-title">确认并保存</h4>
          <div class="fld">
            <span class="fld-lbl">配置名称</span>
            <TextField
              :model-value="name"
              label="配置名称"
              placeholder="例如：CG_Vue_Event"
              :disabled="Boolean(created)"
              @update:model-value="onName"
            />
          </div>
          <dl class="sum" data-testid="wizard-summary">
            <div class="sum-row">
              <dt>仓库</dt>
              <dd>
                {{ effRepoName || '未关联 ADO 仓库' }}
                <span class="hint mono">{{ effPath }}</span>
              </dd>
            </div>
            <div class="sum-row">
              <dt>分支</dt>
              <dd>
                <p v-for="n in branchSel" :key="n" class="sum-line">
                  <span class="mono">{{ n }}</span>
                  <span class="hint">{{ branchRuleSummary(n) }}</span>
                </p>
              </dd>
            </div>
            <div class="sum-row">
              <dt>发布目标</dt>
              <dd>
                <div v-for="t in allTargets" :key="t.key" class="sum-line col">
                  <span>{{ t.name.trim() || '目标' }}</span>
                  <span class="env-tags">
                    <Tag v-for="e in envNames(t)" :key="e">{{ e }}</Tag>
                  </span>
                </div>
              </dd>
            </div>
            <div class="sum-row">
              <dt>Agent 队列</dt>
              <dd>{{ queueName.trim() || queueId.trim() || '不指定' }}</dd>
            </div>
            <div class="sum-row">
              <dt>运行命令</dt>
              <dd>
                <p v-for="d in includedDrafts" :key="d.key" class="sum-line">
                  <span>{{ d.name.trim() }}</span>
                  <Tag v-if="doneKeys.includes(d.key)" tone="ok">已创建</Tag>
                  <span v-if="d.tgCommand.trim()" class="hint mono">/{{ d.tgCommand.trim() }}</span>
                </p>
              </dd>
            </div>
          </dl>

          <Banner
            v-if="partial"
            kind="error"
            title="配置已创建，命令没有建完"
            data-testid="wizard-partial-error"
          >
            配置“{{ name.trim() }}”已经保存，已创建 {{ doneKeys.length }} 条命令，还差
            {{ pendingDrafts.length }} 条没建成：{{ errorText }}
            点“重试”只会补建剩下的命令，不会重复创建配置。也可以回到上一步改命令名，或先到这里为止、之后在配置里手动添加。
            <template #actions>
              <Button @click="emit('update:open', false)">先到这里</Button>
            </template>
          </Banner>
          <Banner v-else-if="saveError" kind="error" data-testid="wizard-save-error">
            {{ errorText }}
          </Banner>
        </section>
      </div>
    </div>

    <template #actions>
      <Button :disabled="saving" data-testid="wizard-cancel" @click="emit('update:open', false)">
        {{ created ? '关闭' : '取消' }}
      </Button>
      <p
        v-if="!stepOk[step] && nextBlockedHint"
        class="need save-need"
        data-testid="wizard-blocked-hint"
      >
        {{ nextBlockedHint }}
      </p>
      <span v-else class="spacer"></span>
      <Button data-testid="wizard-back" :disabled="!canBack" @click="goBack">上一步</Button>
      <Button
        v-if="step !== 'confirm'"
        variant="primary"
        data-testid="wizard-next"
        :disabled="!stepOk[step]"
        @click="goNext"
      >
        下一步
      </Button>
      <Button
        v-else
        variant="primary"
        data-testid="wizard-save"
        :disabled="saving || !stepOk.confirm"
        @click="save"
      >
        {{
          saving
            ? '保存中…'
            : created
              ? `重试创建剩余 ${pendingDrafts.length} 条命令`
              : `创建配置和 ${includedDrafts.length} 条命令`
        }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.wz {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.wz-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 0;
  padding: 0 0 8px;
  list-style: none;
  border-bottom: 1px solid var(--line);
}
.wz-step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.wz-dot {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  box-sizing: border-box;
  border: 1.5px dashed var(--field-line);
  font-size: 10px;
  font-family: var(--font-mono);
}
.wz-step[data-state='done'] .wz-dot {
  border: 0;
  background: var(--st-success-dot);
  color: var(--on-accent);
}
.wz-step[data-state='current'] {
  color: var(--ink);
  font-weight: 700;
}
.wz-step[data-state='current'] .wz-dot {
  border: 0;
  background: var(--ink);
  color: var(--bg-window);
}
.wz-body {
  max-height: min(56vh, 540px);
  overflow-y: auto;
  padding: 2px;
}
.wz-sec {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sec-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
}
.hint {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.need {
  margin: 0;
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--bn-warn-fg);
}
.save-need {
  align-self: center;
  margin-right: auto;
}
.spacer {
  flex: 1;
}
.mono {
  font-family: var(--font-mono);
}
.fld {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fld.grow {
  flex: 1;
  min-width: 0;
}
.fld-lbl,
.k {
  font-size: var(--text-sub);
  color: var(--mute);
}
.two-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.path-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.repo-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 180px;
  overflow-y: auto;
}
.repo-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  background: var(--bg-window);
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.repo-btn:hover:not(:disabled) {
  background: var(--hover);
}
.repo-btn[data-selected='true'] {
  border-color: var(--accent);
  background: var(--sel-blur);
}
.repo-btn:disabled {
  color: var(--disabled);
  cursor: not-allowed;
}
.repo-name {
  flex: none;
  font-weight: 600;
}
.repo-path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-sub);
  color: var(--mute);
}
.result {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--st-success-dot);
  background: var(--st-success-bg);
}
.result-line {
  margin: 0;
  display: flex;
  gap: 10px;
  overflow-wrap: anywhere;
}
.result-line .k {
  flex: none;
  min-width: 56px;
}
.sel-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sel-box {
  padding: 10px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--ink) 2%, transparent);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sel-box[data-included='false'] {
  opacity: 0.6;
}
.sel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.branch-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.inc {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.sum {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sum-row {
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.sum-row dt {
  font-size: var(--text-sub);
  color: var(--mute);
}
.sum-row dd {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.sum-line {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.sum-line.col {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.env-tags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
