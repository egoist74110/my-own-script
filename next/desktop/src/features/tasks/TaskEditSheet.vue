<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import AdvancedFold from './AdvancedFold.vue'
import BranchPicker from './BranchPicker.vue'
import BranchRuleFields from './BranchRuleFields.vue'
import LocalPathField from './LocalPathField.vue'
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
  branchFromView,
  duplicateBranchIndexes,
  parseList,
  safeStageName,
  targetFromView,
  targetProblem,
  toBranchInput,
  toTargetInput,
  type EditableBranch,
  type EditableTarget,
} from './release-draft'
import { useTasksApi } from './queries'
import { releaseErrorText, type ReleaseCreate, type ReleasePatch, type ReleaseView } from './api'

/**
 * 发布配置编辑器（已有配置）：名称、只读的仓库信息（可重新识别）、分支目录（每个分支各有更新/合并/推送规则，可从远端添加）、
 * Agent 队列（下拉）、发布目标目录（可从 ADO 添加，环境默认不勾）。
 * 手填的 ADO 字段（项目/仓库 ID、队列 ID、目标的构建与 Release 定义）全部收在默认收起的“高级（手动填写）”里，ADO 不可达时可退回手填。
 * 分支与目标只在这里增删改；命令用哪个分支、发布哪些目标由「运行命令」选。被命令使用的分支和目标都不能删。
 * 新建配置走向导（ReleaseWizardSheet）。
 */
const props = defineProps<{
  open: boolean
  /** 编辑时传入现有配置。 */
  config: ReleaseView | null
  /** 这份表单所依据的配置版本（乐观锁）。 */
  revision: number
  submitting?: boolean
  error?: unknown
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  save: [payload: ReleaseCreate | ReleasePatch]
}>()

const router = useRouter()
const { qc } = useTasksApi()

const name = ref('')
const projectId = ref('')
const repoId = ref('')
const repoName = ref('')
const localRepoPath = ref('')
const agentQueueId = ref('')
const agentQueueName = ref('')

const targets = ref<EditableTarget[]>([])
const branches = ref<EditableBranch[]>([])

// 发现：每一块按需打开，打开才发请求
const advancedOpen = ref(false)
const remoteBranchesOpen = ref(false)
const remoteBranchSel = ref<string[]>([])
const remoteTargetsOpen = ref(false)
const queueOpen = ref(false)

/** 没有本地路径时，执行器不支持 Git 规则（更新/合并/推送）。 */
const noLocalPath = computed(() => !localRepoPath.value.trim())
const pid = computed(() => projectId.value.trim())
const rid = computed(() => repoId.value.trim())
const canDiscover = computed(() => Boolean(pid.value && rid.value))

const rediscover = useDiscoverRepo()
const pathField = ref<InstanceType<typeof LocalPathField> | null>(null)
/** 展开了某个分支的规则、或打开了“从远端添加分支”才去读远端分支（懒加载，复用缓存）。 */
const branchesQ = useDiscoverBranches(
  pid,
  rid,
  computed(
    () => remoteBranchesOpen.value || (!noLocalPath.value && branches.value.some((b) => b.open)),
  ),
)
/** 正在“修改”的已有目标（按 key）；任何一个展开时才去读 discover/targets，并与“从 ADO 添加目标”共用同一份缓存。 */
const editingKeys = ref<string[]>([])
/** 用户动过环境或配对的目标：这些目标必须至少留一个环境。 */
const touchedKeys = ref<string[]>([])
const targetsQ = useDiscoverTargets(
  pid,
  rid,
  computed(() => remoteTargetsOpen.value || editingKeys.value.length > 0),
)
const queuesQ = useDiscoverQueues(pid, queueOpen)

/** 打开时每个已有目标的内容快照：与当前不同（或是新加的）就标“未保存”。 */
const originalTargets = ref<Record<string, string>>({})
/** 刚从 ADO 添加的目标（高亮并滚动到它）。 */
const addedKey = ref<string | null>(null)
let addedTimer: ReturnType<typeof setTimeout> | null = null
onBeforeUnmount(() => {
  if (addedTimer) clearTimeout(addedTimer)
})
const bodyEl = ref<HTMLElement | null>(null)

function targetUnsaved(t: EditableTarget): boolean {
  const orig = originalTargets.value[t.key]
  return orig === undefined || orig !== JSON.stringify(toTargetInput(t))
}

function initForm() {
  const c = props.config
  name.value = c?.name ?? ''
  projectId.value = c?.project_id ?? ''
  repoId.value = c?.repo_id ?? ''
  repoName.value = c?.repo_name ?? ''
  localRepoPath.value = c?.local_repo_path ?? ''
  branches.value = (c?.branches ?? []).map((b) =>
    // 规则默认收起，点开才读取远端分支（不在打开时发请求）
    branchFromView(b, false),
  )
  agentQueueId.value = c?.agent_queue_id ?? ''
  agentQueueName.value = c?.agent_queue_name ?? ''
  targets.value = (c?.targets ?? []).map(targetFromView)
  originalTargets.value = Object.fromEntries(
    targets.value.map((t) => [t.key, JSON.stringify(toTargetInput(t))]),
  )
  addedKey.value = null
  advancedOpen.value = false
  remoteBranchesOpen.value = false
  remoteBranchSel.value = []
  remoteTargetsOpen.value = false
  editingKeys.value = []
  touchedKeys.value = []
  queueOpen.value = false
  rediscover.reset()
}

// 保存失败时把错误滚到可见位置
watch(
  () => props.error,
  (e) => {
    if (e && bodyEl.value) bodyEl.value.scrollTop = 0
  },
)

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) initForm()
  },
)

// ───────────── 仓库信息（只读）与重新识别 ─────────────

const repoLinked = computed(() => Boolean(pid.value && rid.value))
const found = computed(() => rediscover.data.value ?? null)
const foundDiffers = computed(() => {
  const f = found.value
  if (!f?.project_id || !f.repo_id) return false
  return (
    f.project_id !== projectId.value.trim() ||
    f.repo_id !== repoId.value.trim() ||
    (f.repo_name ?? '') !== repoName.value.trim()
  )
})

function runRediscover() {
  const path = localRepoPath.value.trim()
  if (!path || rediscover.isPending.value) return
  rediscover.mutate(path)
}

function adoptFound() {
  const f = found.value
  if (!f?.project_id || !f.repo_id) return
  projectId.value = f.project_id
  repoId.value = f.repo_id
  repoName.value = f.repo_name ?? ''
  // 换了仓库：旧仓库里的勾选作废，发现查询按新的项目/仓库重新读取
  remoteBranchSel.value = []
  void qc.removeQueries({ queryKey: ['release-discover'] })
}

function gotoSettings() {
  emit('update:open', false)
  void router.push('/settings')
}

// ───────────── 分支 ─────────────

function addBranch() {
  branches.value.push(blankBranch(''))
}

const existingBranchNames = computed(() =>
  branches.value.map((b) => b.build_branch.trim()).filter(Boolean),
)

function addRemoteBranches() {
  for (const n of remoteBranchSel.value) {
    if (existingBranchNames.value.includes(n)) continue
    branches.value.push(blankBranch(n, false))
  }
  remoteBranchSel.value = []
  remoteBranchesOpen.value = false
}

/** 分支 id → 正在使用它的命令名（删除前提示用）。 */
const branchUsedBy = computed(() => {
  const map = new Map<string, string[]>()
  for (const cmd of props.config?.commands ?? []) {
    if (!cmd.branch_id) continue
    map.set(cmd.branch_id, [...(map.get(cmd.branch_id) ?? []), cmd.name || cmd.tg_command])
  }
  return map
})

function branchUsers(b: EditableBranch): string[] {
  return b.id ? (branchUsedBy.value.get(b.id) ?? []) : []
}

function removeBranch(idx: number) {
  const b = branches.value[idx]
  if (!b || branchUsers(b).length > 0) return
  branches.value.splice(idx, 1)
}

/** 构建分支名重复或为空的分支下标（同一配置里构建分支不能重复）。 */
const duplicateBranchIdx = computed(() => duplicateBranchIndexes(branches.value))
const emptyBranchIdx = computed(
  () => new Set(branches.value.flatMap((b, i) => (b.build_branch.trim() ? [] : [i]))),
)
const branchesInvalid = computed(
  () => duplicateBranchIdx.value.size > 0 || emptyBranchIdx.value.size > 0,
)

/** 分支下标 → 该分支合并规则里格式不对的项。 */
const badMergesByIdx = computed(() => {
  const m = new Map<number, string[]>()
  branches.value.forEach((b, i) => {
    const { bad } = analyzeMerges(b.merges)
    if (bad.length) m.set(i, bad)
  })
  return m
})
const mergesInvalid = computed(() => badMergesByIdx.value.size > 0)

// ───────────── 发布目标 ─────────────

function addTarget() {
  targets.value.push(blankTarget(targets.value.length + 1))
}

/** 目标 id → 正在使用它的命令名（删除前提示用）。 */
const usedBy = computed(() => {
  const map = new Map<string, string[]>()
  for (const cmd of props.config?.commands ?? []) {
    for (const tid of cmd.target_ids ?? []) {
      map.set(tid, [...(map.get(tid) ?? []), cmd.name || cmd.tg_command])
    }
  }
  return map
})

function usersOf(t: EditableTarget): string[] {
  return t.id ? (usedBy.value.get(t.id) ?? []) : []
}

function removeTarget(idx: number) {
  const t = targets.value[idx]
  if (!t || usersOf(t).length > 0) return
  targets.value.splice(idx, 1)
}

/** 一句话说明目标连到了哪里：构建定义 → Release 定义，环境名。 */
function targetSummary(t: EditableTarget): string {
  const build = t.build_name.trim() || (t.build_id.trim() ? `构建 ${t.build_id.trim()}` : '')
  const rel = t.release_name.trim() || (t.release_id.trim() ? `Release ${t.release_id.trim()}` : '')
  const parts = [build && `构建定义：${build}`, rel && `Release 定义：${rel}`].filter(Boolean)
  return parts.length ? parts.join('，') : '还没有关联构建或 Release 定义'
}
function targetEnvNames(t: EditableTarget): string[] {
  const names = t.release_stage_names.trim() ? t.release_stage_names : t.release_stage_ids
  return names
    .split(/[,，、\n\r]+/)
    .map((x) => x.trim())
    .filter(Boolean)
}

/** 表单式添加：目标加进下面的目标列表，面板自动收起，并滚动到新卡片、高亮、标“未保存”。 */
function addTargetFromAdder(t: EditableTarget) {
  targets.value.push(t)
  remoteTargetsOpen.value = false
  addedKey.value = t.key
  if (addedTimer) clearTimeout(addedTimer)
  addedTimer = setTimeout(() => {
    addedKey.value = null
  }, 4000)
  void nextTick(() => {
    const el = bodyEl.value?.querySelector<HTMLElement>(`[data-target-key="${t.key}"]`)
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  })
}

/** 目标下标 → 问题提示。 */
const targetProblems = computed(() => {
  const m = new Map<number, string>()
  targets.value.forEach((t, i) => {
    const p =
      targetProblem(t) ??
      (touchedKeys.value.includes(t.key) && parseList(t.release_stage_ids).length === 0
        ? '至少保留一个环境，请勾选要发布到的环境'
        : null)
    if (p) m.set(i, p)
  })
  return m
})
const targetsInvalid = computed(() => targetProblems.value.size > 0)

// ───────────── 修改已有目标：环境与构建/Release 配对 ─────────────

function isEditing(t: EditableTarget): boolean {
  return editingKeys.value.includes(t.key)
}
function toggleEditing(t: EditableTarget) {
  editingKeys.value = isEditing(t)
    ? editingKeys.value.filter((k) => k !== t.key)
    : [...editingKeys.value, t.key]
}
function touch(t: EditableTarget) {
  if (!touchedKeys.value.includes(t.key)) touchedKeys.value.push(t.key)
}

const discovered = computed(() => targetsQ.data.value ?? null)
const releasesOfBuild = (bid: string) =>
  (discovered.value?.releases ?? []).filter((r) => r.build_definition_ids.includes(bid))

/** 构建定义选项：ADO 全部构建（没被 Release 引用的不可选）；当前值不在其中时仍保留。 */
function buildOptionsFor(t: EditableTarget) {
  const list = (discovered.value?.builds ?? []).map((b) => ({
    id: b.id,
    label: releasesOfBuild(b.id).length ? b.name : `${b.name}：没有关联的 Release，无法发布`,
    disabled: releasesOfBuild(b.id).length === 0 && b.id !== t.build_id.trim(),
  }))
  const cur = t.build_id.trim()
  if (cur && !list.some((o) => o.id === cur))
    list.unshift({
      id: cur,
      label: `${t.build_name || cur}（当前，ADO 里已不存在）`,
      disabled: false,
    })
  return list
}
/** Release 定义选项：只列引用了所选构建定义的；当前值不在其中时仍保留。 */
function releaseOptionsFor(t: EditableTarget) {
  const list = releasesOfBuild(t.build_id.trim()).map((r) => ({ id: r.id, label: r.name }))
  const cur = t.release_id.trim()
  if (cur && !list.some((o) => o.id === cur))
    list.unshift({ id: cur, label: `${t.release_name || cur}（当前，不在所选构建的 Release 里）` })
  return list
}
function setRelease(t: EditableTarget, id: string, resetStages: boolean) {
  const r = (discovered.value?.releases ?? []).find((x) => x.id === id)
  t.release_id = id
  t.release_name = r?.name ?? ''
  // 换了 Release 定义，原来的环境不再适用：清空，必须重新勾选（不默认勾）
  if (resetStages) {
    t.release_stage_ids = ''
    t.release_stage_names = ''
  }
  touch(t)
}
function onBuildChange(t: EditableTarget, id: string) {
  const b = (discovered.value?.builds ?? []).find((x) => x.id === id)
  if (!b) return
  t.build_kind = b.kind
  t.build_id = b.id
  t.build_name = b.name
  const rs = releasesOfBuild(id)
  // 原 Release 仍引用这个构建就保留；只有一个就自动选；否则清空等用户选
  if (rs.some((r) => r.id === t.release_id.trim())) touch(t)
  else if (rs.length === 1) setRelease(t, rs[0]!.id, true)
  else setRelease(t, '', true)
}
function onReleaseChange(t: EditableTarget, id: string) {
  if (id !== t.release_id.trim()) setRelease(t, id, true)
}

interface StageRow {
  id: string
  name: string
  checked: boolean
  gone: boolean
}
/** 该目标 Release 的全部环境（来自 ADO），加上已保存但 ADO 里已不存在的环境。 */
function stageRows(t: EditableTarget): StageRow[] {
  const ids = parseList(t.release_stage_ids)
  const names = parseList(t.release_stage_names)
  const savedName = new Map(ids.map((id, i) => [id, names[i] ?? '']))
  const rel = targetsQ.data.value?.releases.find((r) => r.id === t.release_id.trim())
  const rows: StageRow[] = (rel?.environments ?? []).map((e) => ({
    id: e.id,
    name: e.name,
    checked: ids.includes(e.id),
    gone: false,
  }))
  for (const id of ids) {
    if (!rows.some((r) => r.id === id))
      rows.push({ id, name: safeStageName(savedName.get(id) ?? '', id), checked: true, gone: true })
  }
  return rows
}
function toggleStage(t: EditableTarget, id: string, on: boolean) {
  const rows = stageRows(t)
  const chosen = rows.filter((r) => (r.id === id ? on : r.checked))
  // ids 与 names 始终等长
  t.release_stage_ids = chosen.map((r) => r.id).join(', ')
  t.release_stage_names = chosen.map((r) => safeStageName(r.name, r.id)).join(', ')
  touch(t)
}

// ───────────── 保存按钮的所有禁用原因：都在按钮旁写出来，指向收起区域的给“去修改” ─────────────

/** 没有本地路径时，执行器不支持 Git 规则（更新/合并/推送）：对应分支行提示并禁止保存。 */
const anyRules = computed(() => gitRulesNoPath.value.size > 0)
function focusPath() {
  pathField.value?.focus()
}
function clearAllRules() {
  for (const b of branches.value) {
    b.update_branches = ''
    b.merges = ''
    b.push_branches = ''
  }
}
const gitRulesNoPath = computed(() => {
  const m = new Map<number, string>()
  if (localRepoPath.value.trim()) return m
  branches.value.forEach((b, i) => {
    if (b.update_branches.trim() || b.merges.trim() || b.push_branches.trim())
      m.set(i, '没有本地仓库路径时不支持更新、合并、推送规则。')
  })
  return m
})

interface Blocker {
  key: string
  testid: string
  text: string
  /** 问题字段在收起的折叠区里时，给一个跳转动作。 */
  fix?: { label: string; run: () => void }
}
function openAdvanced() {
  advancedOpen.value = true
}
const saveBlockers = computed<Blocker[]>(() => {
  const out: Blocker[] = []
  if (!name.value.trim())
    out.push({ key: 'name', testid: 'name-empty', text: '请填写配置名称，才能保存。' })
  if (branchesInvalid.value)
    out.push({
      key: 'branches',
      testid: 'branches-invalid',
      text: '分支有重复或空的构建分支名，改好后才能保存。',
    })
  if (mergesInvalid.value)
    out.push({
      key: 'merges',
      testid: 'merges-invalid',
      text: '有分支的合并规则格式不对，改好后才能保存。',
    })
  if (gitRulesNoPath.value.size > 0)
    out.push({
      key: 'gitrules',
      testid: 'gitrules-nopath',
      text: '没有本地仓库路径，但分支配了 Git 规则，清空规则或填写本地路径后才能保存。',
      fix: { label: '选择本地仓库', run: focusPath },
    })
  if (targetsInvalid.value) {
    const [idx, msg] = [...targetProblems.value.entries()][0]!
    const inAdvanced = !targets.value[idx]?.id && msg.includes('构建定义')
    out.push({
      key: 'targets',
      testid: 'targets-invalid',
      text: `发布目标 ${idx + 1} 有问题：${msg}。改好后才能保存。`,
      fix: inAdvanced ? { label: '去修改', run: openAdvanced } : undefined,
    })
  }
  return out
})

function onSubmit() {
  if (props.submitting || saveBlockers.value.length > 0) return
  const payload: ReleaseCreate = {
    name: name.value.trim(),
    local_repo_path: localRepoPath.value.trim(),
    project_id: projectId.value.trim() || null,
    repo_id: repoId.value.trim() || null,
    repo_name: repoName.value.trim() || null,
    sort_order: props.config?.sort_order ?? 0,
    branches: branches.value.map(toBranchInput),
    agent_queue_id: agentQueueId.value.trim() || null,
    agent_queue_name: agentQueueName.value.trim() || null,
    targets: targets.value.map(toTargetInput),
    revision: props.revision,
  }
  emit('save', payload)
}
</script>

<template>
  <Sheet
    :open="open"
    wide
    title="编辑发布配置"
    description="在这里设定分支、Git 规则和可发布的目标。要发布哪些目标，在“运行命令”里选。"
    @update:open="emit('update:open', $event)"
  >
    <div ref="bodyEl" class="edit-sheet-body" data-testid="task-edit-sheet">
      <Banner v-if="error" kind="error" class="mb-2" data-testid="task-edit-error">
        {{ releaseErrorText(error) }}
      </Banner>

      <form class="task-form" @submit.prevent="onSubmit">
        <div class="fld">
          <span class="fld-lbl">配置名称</span>
          <TextField v-model="name" label="配置名称" placeholder="例如：CG_Vue_Event" required />
        </div>

        <div class="fld">
          <span class="fld-lbl"
            >本地仓库路径（可留空：只构建发布，用远端最新代码；设置 Git 规则需要它）</span
          >
          <LocalPathField
            ref="pathField"
            v-model="localRepoPath"
            :repo-id="repoId"
            :repo-name="repoName"
          />
        </div>

        <!-- 仓库信息：只读，靠“重新识别”刷新 -->
        <h4 class="form-sec-title">仓库</h4>
        <div class="repo-info" data-testid="repo-info">
          <p class="repo-line">
            <span class="repo-k">ADO 仓库</span>
            <template v-if="repoLinked">
              <span>{{ repoName || '已关联' }}</span>
              <Tag tone="ok">已关联</Tag>
            </template>
            <template v-else>
              <span>还没有关联 ADO 仓库</span>
              <Tag tone="warn">未关联</Tag>
            </template>
          </p>
          <div class="repo-actions">
            <Button
              data-testid="rediscover-btn"
              :disabled="rediscover.isPending.value || !localRepoPath.trim()"
              @click="runRediscover"
            >
              {{ rediscover.isPending.value ? '识别中…' : '重新识别' }}
            </Button>
            <span class="hint">按本地路径重新读取远端地址，并匹配设置里的 ADO 项目。</span>
          </div>
          <Banner v-if="rediscover.error.value" kind="error" data-testid="rediscover-error">
            {{ discoverErrorText(rediscover.error.value) }}
            <template v-if="discoverNeedsSettings(rediscover.error.value)" #actions>
              <Button @click="gotoSettings">去设置</Button>
            </template>
          </Banner>
          <Banner
            v-else-if="found && !found.project_id"
            kind="warn"
            data-testid="rediscover-nomatch"
          >
            {{ projectNotMatchedText() }}
            <template #actions><Button @click="gotoSettings">去设置</Button></template>
          </Banner>
          <Banner v-else-if="found" kind="info" data-testid="rediscover-result">
            识别到：{{ found.project_label }}，仓库 {{ found.repo_name }}，默认分支
            {{ found.default_branch || '未设置' }}。
            <template v-if="foundDiffers">与当前保存的关联不同，采用后保存才生效。</template>
            <template v-else>与当前关联一致。</template>
            <template v-if="foundDiffers" #actions>
              <Button data-testid="adopt-discovery-btn" @click="adoptFound">采用识别结果</Button>
            </template>
          </Banner>
        </div>

        <div class="targets-header">
          <h4 class="form-sec-title">分支</h4>
          <div class="header-btns">
            <Button
              type="button"
              data-testid="add-remote-branches-btn"
              :disabled="!canDiscover"
              @click="remoteBranchesOpen = !remoteBranchesOpen"
            >
              从远端添加分支
            </Button>
            <Button variant="default" type="button" data-testid="add-branch-btn" @click="addBranch">
              添加分支
            </Button>
          </div>
        </div>
        <p class="hint">
          每个分支有自己的更新、合并、推送规则。运行命令选一个分支，运行时按这个分支的规则同步代码。
        </p>
        <p v-if="!canDiscover" class="hint" data-testid="discover-unavailable">
          还没有关联 ADO 仓库，无法读取远端分支与目标。先点“重新识别”，或在“高级”里手动填写。
        </p>

        <div v-if="remoteBranchesOpen" class="remote-box" data-testid="remote-branches-box">
          <p v-if="branchesQ.isFetching.value" class="hint" role="status">正在读取远端分支…</p>
          <Banner
            v-else-if="branchesQ.error.value"
            kind="error"
            data-testid="remote-branches-error"
          >
            {{ discoverErrorText(branchesQ.error.value) }}
            <template #actions>
              <Button @click="branchesQ.refetch()">重试</Button>
            </template>
          </Banner>
          <template v-else-if="branchesQ.data.value">
            <BranchPicker
              v-model="remoteBranchSel"
              :branches="branchesQ.data.value.branches"
              :default-branch="branchesQ.data.value.default_branch"
              :disabled="existingBranchNames"
            />
            <div class="remote-actions">
              <Button
                variant="primary"
                data-testid="confirm-remote-branches-btn"
                :disabled="remoteBranchSel.length === 0"
                @click="addRemoteBranches"
              >
                添加所选分支（{{ remoteBranchSel.length }}）
              </Button>
              <Button @click="remoteBranchesOpen = false">收起</Button>
            </div>
          </template>
        </div>

        <div v-if="noLocalPath" class="rules-off" data-testid="rules-disabled">
          <p class="hint">
            没有本地仓库路径时，Git
            规则（更新、合并、推送）暂不可用：执行器只会用远端最新代码构建发布。选择本地仓库后才能设置规则。
          </p>
          <div class="remote-actions">
            <Button type="button" data-testid="choose-local-repo-btn" @click="focusPath">
              选择本地仓库
            </Button>
            <Button
              v-if="anyRules"
              type="button"
              data-testid="clear-rules-btn"
              @click="clearAllRules"
            >
              清空这些规则
            </Button>
          </div>
          <p v-if="anyRules" class="hint">
            下面分支里已有的规则只读显示，保存前需要清空，或先选择本地仓库。
          </p>
        </div>

        <p v-if="branches.length === 0" class="hint" data-testid="branch-empty">
          还没有分支。添加一个，才能新建运行命令。
        </p>

        <div
          v-for="(br, idx) in branches"
          :key="br.key"
          class="target-edit-box"
          :data-testid="`branch-edit-${idx}`"
        >
          <div class="target-edit-head">
            <button
              type="button"
              class="branch-toggle"
              :aria-expanded="br.open"
              :data-testid="`toggle-branch-${idx}`"
              @click="br.open = !br.open"
            >
              <component :is="br.open ? ChevronDown : ChevronRight" :size="14" aria-hidden="true" />
              <span class="target-num">分支 {{ idx + 1 }}</span>
              <span class="branch-name mono">{{ br.build_branch.trim() || '未命名' }}</span>
            </button>
            <Button
              variant="destructive"
              type="button"
              :disabled="branchUsers(br).length > 0"
              :data-testid="`remove-branch-${idx}`"
              @click="removeBranch(idx)"
            >
              删除
            </Button>
          </div>
          <p
            v-if="branchUsers(br).length > 0"
            class="target-used"
            :data-testid="`branch-used-${idx}`"
            role="note"
          >
            正在被命令“{{
              branchUsers(br).join('”“')
            }}”使用，不能删除。要删它，先把这些命令改用别的分支。
          </p>
          <p
            v-if="duplicateBranchIdx.has(idx)"
            class="need"
            :data-testid="`branch-dup-${idx}`"
            role="alert"
          >
            构建分支“{{ br.build_branch.trim() }}”在这个配置里重复了。每个分支的构建分支名不能相同。
          </p>
          <p v-else-if="emptyBranchIdx.has(idx)" class="need" role="alert">请填写构建分支名。</p>

          <BranchRuleFields
            v-if="br.open"
            v-model="branches[idx]!"
            show-name
            :label-prefix="`分支 ${idx + 1}`"
            :testid-prefix="`branch-${idx}`"
            :options="branchesQ.data.value?.branches"
            :loading="branchesQ.isFetching.value"
            :disabled="noLocalPath"
          />
        </div>

        <h4 class="form-sec-title">构建队列</h4>
        <div class="queue-box" data-testid="queue-section">
          <p class="repo-line">
            <span class="repo-k">当前队列</span>
            <span v-if="agentQueueId.trim() || agentQueueName.trim()">{{
              agentQueueName.trim() || `队列 ${agentQueueId.trim()}`
            }}</span>
            <span v-else class="hint">不指定</span>
            <Button
              type="button"
              data-testid="change-queue-btn"
              :disabled="!pid"
              @click="queueOpen = !queueOpen"
            >
              {{ queueOpen ? '收起' : '更换队列' }}
            </Button>
          </p>
          <QueueSelect
            v-if="queueOpen"
            v-model:queue-id="agentQueueId"
            v-model:queue-name="agentQueueName"
            :queues="queuesQ.data.value?.queues"
            :loading="queuesQ.isFetching.value"
            :error="queuesQ.error.value"
            @retry="queuesQ.refetch()"
          />
        </div>

        <div class="targets-header">
          <h4 class="form-sec-title">发布目标</h4>
          <Button
            type="button"
            data-testid="add-remote-targets-btn"
            :disabled="!canDiscover"
            @click="remoteTargetsOpen = !remoteTargetsOpen"
          >
            从 ADO 添加目标
          </Button>
        </div>
        <p class="hint">目标是“构建流水线 + Release + 环境”的组合。命令里勾选它才会被发布。</p>

        <div v-if="remoteTargetsOpen" class="remote-box" data-testid="remote-targets-box">
          <p v-if="targetsQ.isFetching.value" class="hint" role="status">
            正在读取构建与 Release 定义…
          </p>
          <Banner v-else-if="targetsQ.error.value" kind="error" data-testid="remote-targets-error">
            {{ discoverErrorText(targetsQ.error.value) }}
            <template #actions>
              <Button @click="targetsQ.refetch()">重试</Button>
            </template>
          </Banner>
          <template v-else-if="targetsQ.data.value">
            <p class="hint">
              先选构建定义，再选 Release
              定义，勾选要发布到的环境（默认都不勾），点“添加这个目标”。同一个构建和 Release
              可以添加多次，环境不同即可。
            </p>
            <TargetAdder
              :key="`${pid}|${rid}`"
              :data="targetsQ.data.value"
              :existing="targets"
              @add="addTargetFromAdder"
            />
          </template>
          <div class="remote-actions">
            <Button @click="remoteTargetsOpen = false">收起</Button>
          </div>
        </div>

        <div
          v-for="(tgt, idx) in targets"
          :key="tgt.key"
          class="target-edit-box"
          :data-added="addedKey === tgt.key ? 'true' : undefined"
          :data-target-key="tgt.key"
          :data-testid="`target-edit-${idx}`"
        >
          <div class="target-edit-head">
            <span class="target-num"
              >目标 {{ idx + 1 }}
              <Tag v-if="targetUnsaved(tgt)" tone="warn" :data-testid="`target-unsaved-${idx}`"
                >未保存</Tag
              ></span
            >
            <Button
              variant="destructive"
              type="button"
              :disabled="usersOf(tgt).length > 0"
              :data-testid="`remove-target-${idx}`"
              @click="removeTarget(idx)"
            >
              删除
            </Button>
          </div>
          <p
            v-if="usersOf(tgt).length > 0"
            class="target-used"
            :data-testid="`target-used-${idx}`"
            role="note"
          >
            正在被命令“{{
              usersOf(tgt).join('”“')
            }}”使用，不能删除。要删它，先在这些命令里取消勾选这个目标。
          </p>
          <div class="fld">
            <span class="fld-lbl">目标名称</span>
            <TextField v-model="tgt.name" label="目标名称" placeholder="staging-a" required />
          </div>
          <p
            v-if="targetProblems.has(idx)"
            class="need"
            role="alert"
            :data-testid="`target-problem-${idx}`"
          >
            {{ targetProblems.get(idx) }}
          </p>
          <p class="hint">{{ targetSummary(tgt) }}</p>
          <div v-if="targetEnvNames(tgt).length" class="env-tags">
            <Tag v-for="(e, i) in targetEnvNames(tgt)" :key="`${i}-${e}`">{{ e }}</Tag>
          </div>
          <p v-else class="hint">未选环境。</p>
          <div>
            <Button
              type="button"
              :data-testid="`edit-target-btn-${idx}`"
              :aria-expanded="isEditing(tgt)"
              @click="toggleEditing(tgt)"
            >
              {{ isEditing(tgt) ? '完成' : '修改' }}
            </Button>
          </div>

          <div v-if="isEditing(tgt)" class="remote-box" :data-testid="`target-editor-${idx}`">
            <p
              v-if="usersOf(tgt).length > 0"
              class="target-used"
              role="note"
              :data-testid="`target-impact-${idx}`"
            >
              修改会影响命令：{{ usersOf(tgt).join('、') }}。目标本身不变，这些命令仍然指向它。
            </p>
            <p v-if="targetsQ.isFetching.value" class="hint" role="status">
              正在读取构建与 Release 定义…
            </p>
            <Banner
              v-else-if="targetsQ.error.value || !canDiscover"
              kind="warn"
              :data-testid="`target-editor-error-${idx}`"
            >
              <template v-if="targetsQ.error.value">{{
                discoverErrorText(targetsQ.error.value)
              }}</template>
              <template v-else>还没有关联 ADO 仓库，读不到环境。</template>
              可以在下面的“高级（手动填写）”里直接改构建定义、Release 定义和环境。
              <template #actions>
                <Button v-if="targetsQ.error.value" @click="targetsQ.refetch()">重试</Button>
                <Button v-if="discoverNeedsSettings(targetsQ.error.value)" @click="gotoSettings"
                  >去设置</Button
                >
                <Button @click="advancedOpen = true">打开高级</Button>
              </template>
            </Banner>
            <template v-else-if="targetsQ.data.value">
              <div class="fld">
                <label class="fld-lbl" :for="`target-build-${tgt.key}`">构建定义</label>
                <select
                  :id="`target-build-${tgt.key}`"
                  class="sel-ctl"
                  :value="tgt.build_id.trim()"
                  :data-testid="`target-build-${idx}`"
                  @change="onBuildChange(tgt, ($event.target as HTMLSelectElement).value)"
                >
                  <option
                    v-for="o in buildOptionsFor(tgt)"
                    :key="o.id"
                    :value="o.id"
                    :disabled="o.disabled"
                  >
                    {{ o.label }}
                  </option>
                </select>
              </div>
              <div class="fld">
                <label class="fld-lbl" :for="`target-release-${tgt.key}`">Release 定义</label>
                <select
                  :id="`target-release-${tgt.key}`"
                  class="sel-ctl"
                  :value="tgt.release_id.trim()"
                  :data-testid="`target-release-${idx}`"
                  @change="onReleaseChange(tgt, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="" disabled>请选择 Release 定义</option>
                  <option v-for="o in releaseOptionsFor(tgt)" :key="o.id" :value="o.id">
                    {{ o.label }}
                  </option>
                </select>
              </div>
              <p class="hint">要发布到的环境（至少留一个；换了 Release 定义后要重新勾选）</p>
              <div class="env-checks">
                <label v-for="r in stageRows(tgt)" :key="r.id" class="env-check">
                  <input
                    type="checkbox"
                    :checked="r.checked"
                    :data-testid="`target-stage-${idx}-${r.id}`"
                    @change="toggleStage(tgt, r.id, ($event.target as HTMLInputElement).checked)"
                  />
                  <span>{{ r.name }}</span>
                  <Tag v-if="r.gone" tone="warn" :data-testid="`target-stage-gone-${idx}-${r.id}`"
                    >ADO 中已不存在</Tag
                  >
                </label>
                <span v-if="stageRows(tgt).length === 0" class="hint"
                  >这个 Release 定义没有环境。</span
                >
              </div>
            </template>
          </div>
        </div>

        <AdvancedFold
          v-model:open="advancedOpen"
          title="高级（手动填写）"
          data-testid="edit-advanced"
        >
          <p class="hint">
            平时用上面的识别和选择就够了。ADO
            连不上时，可以在这里直接填写项目、仓库、队列和目标的编号。
          </p>
          <div class="two-cols">
            <div class="fld">
              <span class="fld-lbl">ADO 项目 ID</span>
              <TextField v-model="projectId" label="ADO 项目 ID" placeholder="project id" />
            </div>
            <div class="fld">
              <span class="fld-lbl">远端仓库名</span>
              <TextField v-model="repoName" label="远端仓库名" placeholder="repo name" />
            </div>
          </div>
          <div class="fld">
            <span class="fld-lbl">远端仓库 ID</span>
            <TextField v-model="repoId" label="远端仓库 ID" placeholder="repo id" />
          </div>
          <div class="two-cols">
            <div class="fld">
              <span class="fld-lbl">Agent 队列 ID</span>
              <TextField v-model="agentQueueId" label="Agent 队列 ID" placeholder="可选" />
            </div>
            <div class="fld">
              <span class="fld-lbl">队列名称</span>
              <TextField v-model="agentQueueName" label="队列名称" placeholder="可选" />
            </div>
          </div>
          <div class="targets-header">
            <h4 class="form-sec-title sec-flat">目标的构建与 Release 定义</h4>
            <Button variant="default" type="button" data-testid="add-target-btn" @click="addTarget">
              手动添加目标
            </Button>
          </div>
          <div v-for="(tgt, idx) in targets" :key="tgt.key" class="target-edit-box">
            <span class="target-num">目标 {{ idx + 1 }}：{{ tgt.name.trim() || '未命名' }}</span>
            <TargetManualFields v-model="targets[idx]!" />
          </div>
        </AdvancedFold>
      </form>
    </div>

    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <div v-if="saveBlockers.length" class="save-needs" data-testid="save-blockers">
        <p
          v-for="b in saveBlockers"
          :key="b.key"
          class="need save-need"
          :data-testid="b.testid"
          role="alert"
        >
          {{ b.text }}
          <button v-if="b.fix" type="button" class="need-fix" @click="b.fix.run()">
            {{ b.fix.label }}
          </button>
        </p>
      </div>
      <Button
        variant="primary"
        data-testid="save-task-btn"
        :disabled="submitting || saveBlockers.length > 0"
        @click="onSubmit"
      >
        {{ submitting ? '保存中…' : '保存配置' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.edit-sheet-body {
  max-height: min(64vh, 620px);
  overflow-y: auto;
  padding: 4px 2px;
}
.task-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.two-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.form-sec-title {
  margin: 12px 0 4px;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  border-bottom: 1px solid var(--line);
  padding-bottom: 4px;
}
.sec-flat {
  border-bottom: 0;
  margin: 0;
}
.targets-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.header-btns {
  display: flex;
  gap: 6px;
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
.hint {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.target-used {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--bn-warn-fg);
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
.need {
  margin: 0;
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--bn-warn-fg);
}
.save-needs {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-self: center;
  margin-right: auto;
  min-width: 0;
}
.save-need {
  overflow-wrap: anywhere;
}
.need-fix {
  margin-left: 6px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--link);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.target-edit-box[data-added='true'] {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent);
}
.branch-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ink);
  font: inherit;
  cursor: pointer;
}
.branch-name {
  overflow-wrap: anywhere;
  color: var(--ink);
}
.mono {
  font-family: var(--font-mono);
}
.mb-2 {
  margin-bottom: 8px;
}
.repo-info,
.queue-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.repo-line {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.repo-k {
  flex: none;
  min-width: 64px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.rules-off {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  border-radius: var(--r-ctl);
  border: 1px dashed var(--field-line);
}
.repo-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.remote-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border-radius: var(--r-ctl);
  border: 1px dashed var(--field-line);
}
.remote-actions {
  display: flex;
  gap: 8px;
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
.env-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}
.env-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.env-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
