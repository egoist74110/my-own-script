<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronsDown,
  ChevronsUp,
  GitBranch,
  GripVertical,
  ListChecks,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Target,
  Terminal,
  Trash2,
  Upload,
} from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import EmptyState from '@/components/EmptyState.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import OverflowMenu from '@/components/OverflowMenu.vue'
import SearchField from '@/components/SearchField.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import Skeleton from '@/components/Skeleton.vue'
import ToolbarButton from '@/components/ToolbarButton.vue'
import {
  configActiveCommand,
  commandBranch,
  commandRouteText,
  configLastRun,
  formatRelativeTime,
  formatRepoShort,
  isRevisionConflict,
  releaseErrorText,
  resolveConfigPillState,
  unwrap,
  type CommandCreate,
  type CommandPatch,
  type CommandView,
  type PlanResponse,
  type ReleaseCreate,
  type ReleasePatch,
  type ReleaseView,
  type RunResponse,
  type RunStatus,
  type TaskOperation,
} from './api'
import {
  fetchReleaseConfig,
  useConfigRuns,
  useReleaseActions,
  useReleaseConfigs,
  useTasksApi,
} from './queries'
import { useRunLogs } from './useRunLogs'
import CommandEditSheet from './CommandEditSheet.vue'
import CommandPickerSheet from './CommandPickerSheet.vue'
import CommandSection from './CommandSection.vue'
import RunCard from './RunCard.vue'
import RunConfirmSheet from './RunConfirmSheet.vue'
import RunHistory from './RunHistory.vue'
import TaskListItem from './TaskListItem.vue'
import { useOrderedList } from './useOrderedList'
import TaskDeleteSheet from './TaskDeleteSheet.vue'
import ReleaseWizardSheet from './ReleaseWizardSheet.vue'
import TaskEditSheet from './TaskEditSheet.vue'
import TaskInspector from './TaskInspector.vue'
import TaskRollbackSheet from './TaskRollbackSheet.vue'
import { coarseDots, repoLineColor, runDots, type DotState } from './route'

const router = useRouter()
const { api, online, qc, runtime } = useTasksApi()
const actions = useReleaseActions()

// 本地存储仅保存选中的发布配置 id（绝不存日志、配置草稿或凭据）
const STORAGE_KEY = 'toolbox.tasks.selection'
function loadSelectedId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}
function saveSelectedId(id: string | null) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 忽略 localStorage 异常
  }
}

// 发布配置列表 Query：每项一个配置，配置下带运行命令
const configsQuery = useReleaseConfigs(online, api)
const configs = computed<ReleaseView[]>(() => configsQuery.data.value?.items ?? [])
const revision = computed(() => configsQuery.data.value?.revision ?? 0)

const selectedConfigId = ref<string | null>(loadSelectedId())
const selectedConfig = computed(
  () => configs.value.find((c) => c.id === selectedConfigId.value) ?? null,
)

// 当列表更新，确保选择合法
watch(
  configs,
  (list) => {
    if (list.length === 0) {
      selectedConfigId.value = null
      saveSelectedId(null)
      return
    }
    if (selectedConfigId.value && list.some((c) => c.id === selectedConfigId.value)) return
    const first = list[0]
    if (first) {
      selectedConfigId.value = first.id
      saveSelectedId(first.id)
    }
  },
  { immediate: true },
)

watch(selectedConfigId, (id) => {
  saveSelectedId(id)
})

// 搜索与过滤（命令名与 TG 命令只参与搜索，不显示在列表里）
const keyword = ref('')
const filter = ref<'all' | 'running' | 'attention'>('all')

function needsAttention(c: ReleaseView): boolean {
  return Boolean(c.warnings && c.warnings.length > 0)
}

const filterTabs = computed(() => {
  const runningCount = configs.value.filter((c) => configActiveCommand(c)).length
  const attentionCount = configs.value.filter(needsAttention).length
  return [
    { value: 'all', label: '全部' },
    { value: 'running', label: '运行中', count: runningCount || undefined },
    { value: 'attention', label: '需处理', count: attentionCount || undefined },
  ]
})

// 排序：只在“无搜索且显示全部”时可用（过滤视图下的顺序有歧义）
const sortable = computed(() => !keyword.value.trim() && filter.value === 'all')
const SORT_HINT = '清空搜索并切到全部后才能排序'
const configOrder = useOrderedList(configs, {
  commit: (ids, rev) => actions.orderConfigs(ids, rev),
  revision: () => revision.value,
  onError: (e) => {
    configOpError.value = e
  },
})
const orderedConfigs = configOrder.items

const filteredConfigs = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return orderedConfigs.value.filter((c) => {
    if (q) {
      const hay = [
        c.name,
        c.repo_name ?? '',
        c.local_repo_path,
        ...(c.branches ?? []).map((b) => b.build_branch),
        ...c.commands.flatMap((m) => [m.name, m.tg_command]),
      ]
      if (!hay.some((h) => h.toLowerCase().includes(q))) return false
    }
    if (filter.value === 'running') return Boolean(configActiveCommand(c))
    if (filter.value === 'attention') return needsAttention(c)
    return true
  })
})

const activeRunsCount = computed(() => configs.value.filter((c) => configActiveCommand(c)).length)

// 运行记录：这个配置下所有命令的运行，合并后按时间倒序
const commandIds = computed(() => selectedConfig.value?.commands.map((c) => c.id) ?? [])
const commandNames = computed<Record<string, string>>(() =>
  Object.fromEntries((selectedConfig.value?.commands ?? []).map((c) => [c.id, c.name])),
)
const commandBranches = computed<Record<string, string>>(() => {
  const cfg = selectedConfig.value
  if (!cfg) return {}
  return Object.fromEntries(
    cfg.commands.flatMap((c) => {
      const b = commandBranch(cfg, c)
      return b ? [[c.id, `${b.build_branch} 分支`]] : []
    }),
  )
})
const runsQuery = useConfigRuns(commandIds, online, api)
const historyRuns = computed<RunResponse[]>(() => runsQuery.data.value?.items ?? [])

// 当前选中的运行 ID
const inspectedRunId = ref<string | null>(null)
// 用户手动选择的运行 ID，防止后台刷新抢回焦点
const userSelectedRunId = ref<string | null>(null)

function onSelectConfig(id: string) {
  selectedConfigId.value = id
  userSelectedRunId.value = null
  configOpError.value = null
  commandOpError.value = null
}

function onSelectHistoryRun(run: RunResponse) {
  userSelectedRunId.value = run.run_id
  inspectedRunId.value = run.run_id
}

watch(
  [selectedConfig, historyRuns],
  ([cfg, runs]) => {
    const active = cfg ? configActiveCommand(cfg) : null
    // 若有命令正在运行，自动跟随这次运行
    if (active?.active_run_id) {
      userSelectedRunId.value = null
      inspectedRunId.value = active.active_run_id
      return
    }

    // 若用户手动选择过某次运行且仍在当前历史中，不要被后台刷新抢回
    if (userSelectedRunId.value && runs.some((r) => r.run_id === userSelectedRunId.value)) {
      inspectedRunId.value = userSelectedRunId.value
      return
    }

    // 默认展示最新一条：优先各命令 last_run 里最新的，否则取合并历史第一条
    const last = cfg ? configLastRun(cfg) : null
    if (last?.run_id) {
      inspectedRunId.value = last.run_id
    } else if (runs.length > 0 && runs[0]) {
      inspectedRunId.value = runs[0].run_id
    } else {
      inspectedRunId.value = null
    }
  },
  { immediate: true },
)

// 日志与步骤同步器
const {
  lines,
  totalLineCount,
  steps,
  currentRun,
  status: runStatus,
  summary: runSummary,
  loading: logsLoading,
  gapWarning,
  refresh: refreshRun,
} = useRunLogs(inspectedRunId, runtime, online, api)

/** 本次运行用的命令名（运行快照里的 task_id 就是命令 id）。 */
const currentCommandName = computed(() => {
  const r = currentRun.value
  if (!r) return undefined
  return commandNames.value[r.task_id] || r.task_snapshot?.tg_desc || r.task_snapshot?.tg_command
})

// 运行进入终态时，刷新配置列表与历史运行记录。
// “需核实”(unknown) 也算起点：点「立即核对」后运行会从 unknown 变成 succeeded/failed/cancelled，
// 若只认 queued/running/cancelling，这一步就不会刷新，列表和历史会停在旧状态。
const ACTIVE_OR_UNVERIFIED: ReadonlyArray<RunStatus | null | undefined> = [
  'queued',
  'running',
  'cancelling',
  'unknown',
]
async function refreshTasksAndRuns() {
  await qc.invalidateQueries({ queryKey: ['release-configs'] })
  await qc.invalidateQueries({ queryKey: ['tasks'] })
  await qc.invalidateQueries({ queryKey: ['runs'] })
}
watch(runStatus, async (newStatus, oldStatus) => {
  const isFinal = newStatus === 'succeeded' || newStatus === 'failed' || newStatus === 'cancelled'
  if (isFinal && ACTIVE_OR_UNVERIFIED.includes(oldStatus)) {
    await refreshTasksAndRuns()
  }
})

// 状态横幅逻辑
const isUnknown = computed(
  () => runStatus.value === 'unknown' || currentRun.value?.status === 'unknown',
)
const unknownDesc = computed(() => {
  const why = runSummary.value
    ? `${runSummary.value.replace(/。$/, '')}。`
    : '远端操作已发出，但结果未能确认。'
  return currentRun.value?.recovery_state === 'manual_required'
    ? `${why}已超过 15 分钟自动核对窗口，请到 ADO 确认后点「立即核对」。`
    : `${why}工具箱不会自动重发；每 30 秒只读核对一次，最长 15 分钟。`
})
const reconciling = ref(false)
const reconcileError = ref<unknown>(null)

async function onReconcile() {
  if (!inspectedRunId.value) return
  reconciling.value = true
  reconcileError.value = null
  try {
    await unwrap(
      api().POST('/api/runs/{run_id}/reconcile', {
        params: { path: { run_id: inspectedRunId.value } },
      }),
    )
    // 核对是异步受理（202）：这里先对齐一次运行快照，并立刻刷新列表与历史；
    // 之后运行若变成终态，上面的 watch(runStatus) 还会再刷新一次，所以最终一定落到新状态。
    await qc.invalidateQueries({ queryKey: ['run', inspectedRunId.value] })
    refreshRun()
    await refreshTasksAndRuns()
  } catch (e) {
    reconcileError.value = e
  } finally {
    reconciling.value = false
  }
}

// 停止运行
async function onCancelRun(runId: string) {
  try {
    await unwrap(
      api().POST('/api/runs/{run_id}/cancel', {
        params: { path: { run_id: runId } },
      }),
    )
    await qc.invalidateQueries({ queryKey: ['run', runId] })
  } catch {
    // 错误在 RunCard / Banner 展示
  }
}

// 选择运行命令：运行、只发布、回滚都先选一条命令，再进入预检与确认
const pickerOpen = ref(false)
const pickerOperation = ref<TaskOperation>('sync_build_release')
const pickedCommand = ref<CommandView | null>(null)
const pickedBranch = computed(() =>
  selectedConfig.value && pickedCommand.value
    ? commandBranch(selectedConfig.value, pickedCommand.value)
    : null,
)
const pickedRouteText = computed(() =>
  selectedConfig.value && pickedCommand.value
    ? commandRouteText(selectedConfig.value, pickedCommand.value)
    : '',
)

function openPicker(operation: TaskOperation) {
  pickerOperation.value = operation
  pickerOpen.value = true
}

function onPickCommand(command: CommandView) {
  pickedCommand.value = command
  pickerOpen.value = false
  if (pickerOperation.value === 'rollback') rollbackSheetOpen.value = true
  else void startPreflight(pickerOperation.value)
}

// 预检与执行计划确认 Sheet（接口里的 task_id 就是所选运行命令的 id）
const confirmSheetOpen = ref(false)
const confirmOperation = ref<TaskOperation>('sync_build_release')
const confirmPlan = ref<PlanResponse | null>(null)
const confirmSubmitting = ref(false)
const confirmError = ref<unknown>(null)
const confirmLoading = ref(false)
let lastPreflight: { operation: TaskOperation; rollbackOffset?: number } | null = null

function retryPreflight() {
  if (lastPreflight) void startPreflight(lastPreflight.operation, lastPreflight.rollbackOffset)
}

function onConfirmOpenConfig() {
  confirmSheetOpen.value = false
  void openEditConfig()
}

async function startPreflight(operation: TaskOperation, rollbackOffset?: number) {
  const command = pickedCommand.value
  if (!command) return
  lastPreflight = { operation, rollbackOffset }
  confirmOperation.value = operation
  confirmError.value = null
  confirmPlan.value = null
  confirmLoading.value = true
  confirmSheetOpen.value = true
  try {
    const plan = await unwrap(
      api().POST('/api/tasks/{task_id}/preflight', {
        params: { path: { task_id: command.id } },
        body: {
          operation,
          revision: revision.value,
          rollback_offset: rollbackOffset,
        },
      }),
    )
    confirmPlan.value = plan
  } catch (e) {
    confirmError.value = e
    // 配置已变：重新读取，不自动重发
    if (isRevisionConflict(e)) await qc.invalidateQueries({ queryKey: ['release-configs'] })
  } finally {
    confirmLoading.value = false
  }
}

async function onStartConfirm(payload: { planId: string; requestId: string; ack: true }) {
  if (confirmSubmitting.value) return
  const command = pickedCommand.value
  if (!command) return
  confirmSubmitting.value = true
  confirmError.value = null
  try {
    const res = await unwrap(
      api().POST('/api/tasks/{task_id}/runs', {
        params: { path: { task_id: command.id } },
        body: {
          plan_id: payload.planId,
          request_id: payload.requestId,
          // 后端契约仍要求该字段（Literal[True]），前端不再让用户勾选，固定传 true。
          ack_old_app_idle: true,
        },
      }),
    )
    confirmSheetOpen.value = false
    userSelectedRunId.value = null
    inspectedRunId.value = res.run_id
    await qc.invalidateQueries({ queryKey: ['release-configs'] })
    await qc.invalidateQueries({ queryKey: ['tasks'] })
    await qc.invalidateQueries({ queryKey: ['runs'] })
  } catch (e) {
    confirmError.value = e
  } finally {
    confirmSubmitting.value = false
  }
}

// 回滚选择 Sheet
const rollbackSheetOpen = ref(false)
function onRollbackOffsetChosen(offset: number) {
  void startPreflight('rollback', offset)
}

// 读取最新配置，拿到编辑所依据的 revision；读取失败就用列表里已有的版本
async function readFresh(id: string): Promise<{ item: ReleaseView; revision: number } | null> {
  try {
    return await fetchReleaseConfig(qc, api, id)
  } catch {
    const item = configs.value.find((c) => c.id === id)
    return item ? { item, revision: revision.value } : null
  }
}

// 新建 / 编辑发布配置 Sheet
const editSheetOpen = ref(false)
const configToEdit = ref<ReleaseView | null>(null)
const editBaseRevision = ref(0)
const editSubmitting = ref(false)
const editError = ref<unknown>(null)
const configOpError = ref<unknown>(null)
/** 保存配置成功后的明确反馈（页面内提示条，几秒后自动消失）。 */
const configSavedNotice = ref<string | null>(null)
let savedTimer: ReturnType<typeof setTimeout> | null = null
function showSaved(msg: string) {
  configSavedNotice.value = msg
  if (savedTimer) clearTimeout(savedTimer)
  savedTimer = setTimeout(() => {
    configSavedNotice.value = null
  }, 8000)
}
onBeforeUnmount(() => {
  if (savedTimer) clearTimeout(savedTimer)
})

function openCreateConfig() {
  configToEdit.value = null
  editBaseRevision.value = revision.value
  editError.value = null
  editSheetOpen.value = true
}

async function openEditConfig() {
  const cfg = selectedConfig.value
  if (!cfg) return
  await openEditConfigById(cfg.id, cfg)
}

/** 编辑指定配置（向导里“去编辑已有配置”也走这里）；先读最新内容再打开。 */
async function openEditConfigById(id: string, fallback?: ReleaseView) {
  const cfg = fallback ?? configs.value.find((c) => c.id === id)
  const fresh = await readFresh(id)
  const item = fresh?.item ?? cfg
  if (!item) return
  configToEdit.value = item
  editBaseRevision.value = fresh?.revision ?? revision.value
  editError.value = null
  selectedConfigId.value = id
  editSheetOpen.value = true
}

/** 向导已建好配置：选中它；列表刷新由写操作负责。 */
function onWizardCreated(id: string) {
  selectedConfigId.value = id
}

async function onSaveConfig(payload: ReleaseCreate | ReleasePatch) {
  editSubmitting.value = true
  editError.value = null
  try {
    if (configToEdit.value) {
      await actions.patchConfig(configToEdit.value.id, payload as ReleasePatch)
      showSaved(`已保存发布配置“${(payload as ReleasePatch).name ?? configToEdit.value.name}”。`)
    } else {
      const res = await actions.createConfig(payload as ReleaseCreate)
      if (res.id) selectedConfigId.value = res.id
    }
    editSheetOpen.value = false
  } catch (e) {
    editError.value = e
    if (isRevisionConflict(e)) {
      // 已重新读取：后续保存按最新版本提交，用户先核对表单与最新目标使用情况
      editBaseRevision.value = revision.value
      const id = configToEdit.value?.id
      const latest = id ? configs.value.find((c) => c.id === id) : null
      if (latest) configToEdit.value = latest
    }
  } finally {
    editSubmitting.value = false
  }
}

// 新建 / 编辑运行命令 Sheet
const commandSheetOpen = ref(false)
const commandToEdit = ref<CommandView | null>(null)
const commandBaseRevision = ref(0)
const commandSubmitting = ref(false)
const commandError = ref<unknown>(null)
const commandOpError = ref<unknown>(null)

async function openCreateCommand() {
  const cfg = selectedConfig.value
  if (!cfg) return
  const fresh = await readFresh(cfg.id)
  commandToEdit.value = null
  commandBaseRevision.value = fresh?.revision ?? revision.value
  commandError.value = null
  commandSheetOpen.value = true
}

async function openEditCommand(cmd: CommandView) {
  const cfg = selectedConfig.value
  if (!cfg) return
  const fresh = await readFresh(cfg.id)
  commandToEdit.value = fresh?.item.commands.find((c) => c.id === cmd.id) ?? cmd
  commandBaseRevision.value = fresh?.revision ?? revision.value
  commandError.value = null
  commandSheetOpen.value = true
}

async function onSaveCommand(payload: CommandCreate | CommandPatch) {
  const cfg = selectedConfig.value
  if (!cfg) return
  commandSubmitting.value = true
  commandError.value = null
  try {
    if (commandToEdit.value) {
      await actions.patchCommand(cfg.id, commandToEdit.value.id, payload as CommandPatch)
    } else {
      await actions.createCommand(cfg.id, payload as CommandCreate)
    }
    commandSheetOpen.value = false
  } catch (e) {
    commandError.value = e
    if (isRevisionConflict(e)) commandBaseRevision.value = revision.value
  } finally {
    commandSubmitting.value = false
  }
}

// 删除发布配置或运行命令（共用确认单；遇到权限组引用走解除确认再重试）
const deleteSheetOpen = ref(false)
const deleteSubmitting = ref(false)
const deleteError = ref<unknown>(null)
const deleteTarget = ref<
  | { kind: 'config'; name: string; commandCount: number }
  | { kind: 'command'; name: string; id: string }
  | null
>(null)

function openDeleteConfig() {
  const cfg = selectedConfig.value
  if (!cfg) return
  deleteTarget.value = { kind: 'config', name: cfg.name, commandCount: cfg.commands.length }
  deleteError.value = null
  deleteSheetOpen.value = true
}

function openDeleteCommand(cmd: CommandView) {
  deleteTarget.value = { kind: 'command', name: cmd.name || cmd.tg_command, id: cmd.id }
  deleteError.value = null
  deleteSheetOpen.value = true
}

async function onConfirmDelete(detachAcl = false) {
  const cfg = selectedConfig.value
  const target = deleteTarget.value
  if (!cfg || !target) return
  deleteSubmitting.value = true
  deleteError.value = null
  try {
    if (target.kind === 'config') {
      await actions.deleteConfig(cfg.id, revision.value, detachAcl)
      selectedConfigId.value = null
    } else {
      await actions.deleteCommand(cfg.id, target.id, revision.value, detachAcl)
    }
    deleteSheetOpen.value = false
  } catch (e) {
    deleteError.value = e
  } finally {
    deleteSubmitting.value = false
  }
}

// 列表项的线路色、时间文案与迷你线路
function configRepoName(c: ReleaseView): string {
  return formatRepoShort(c.repo_name, c.local_repo_path)
}
function rowWhen(c: ReleaseView): string {
  const last = configLastRun(c)
  return last?.created_at ? formatRelativeTime(last.created_at) : '从未运行'
}
function rowDots(c: ReleaseView): DotState[] {
  const live = currentRun.value
  const last = configLastRun(c)
  const activeId = configActiveCommand(c)?.active_run_id
  // 选中且正在看这个配置最新一次运行时，用真实步骤；其余只知道运行结果，画粗略线路
  if (
    c.id === selectedConfigId.value &&
    live &&
    (live.run_id === last?.run_id || live.run_id === activeId)
  ) {
    return runDots(steps.value, runStatus.value ?? live.status)
  }
  const targetCount = last?.command.target_ids?.length ?? c.targets?.length ?? 1
  const count = Math.min(7, 1 + 2 * Math.max(1, targetCount))
  return coarseDots(activeId ? 'running' : (last?.status ?? null), count)
}
const selectedLineColor = computed(() =>
  selectedConfig.value ? repoLineColor(configRepoName(selectedConfig.value)) : repoLineColor(null),
)

// 配置排序：乐观更新、串行提交、失败回滚（见 useOrderedList）
function moveConfigBy(id: string, delta: number) {
  if (!sortable.value) return
  configOrder.moveBy(id, delta)
}
function moveConfig(direction: -1 | 1) {
  const cfg = selectedConfig.value
  if (cfg) moveConfigBy(cfg.id, direction)
}
function moveConfigTo(id: string, index: number) {
  if (!sortable.value) return
  configOrder.moveTo(id, index)
}
function configIndex(id: string): number {
  return orderedConfigs.value.findIndex((c) => c.id === id)
}
function onRowKey(e: KeyboardEvent, id: string) {
  if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return
  e.preventDefault()
  moveConfigBy(id, e.key === 'ArrowUp' ? -1 : 1)
}

// 拖拽排序：只从手柄开始（整行点击仍是选中）；原生 pointer 事件，不引入依赖
const dragId = ref<string | null>(null)
const dropIndex = ref<number | null>(null)
const rowsEl = ref<HTMLElement | null>(null)

function dropIndexAt(clientY: number): number {
  const rows = Array.from(rowsEl.value?.querySelectorAll<HTMLElement>('[data-row-id]') ?? [])
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i]!.getBoundingClientRect()
    if (clientY < r.top + r.height / 2) return i
  }
  return rows.length
}
function onDragMove(e: PointerEvent | MouseEvent) {
  if (dragId.value) dropIndex.value = dropIndexAt(e.clientY)
}
function endDrag(commit: boolean) {
  const id = dragId.value
  const to = dropIndex.value
  dragId.value = null
  dropIndex.value = null
  document.removeEventListener('pointermove', onDragMove)
  document.removeEventListener('pointerup', onDragUp)
  document.removeEventListener('pointercancel', onDragCancel)
  if (!commit || !id || to === null) return
  const from = configIndex(id)
  const dest = to > from ? to - 1 : to
  if (from >= 0 && dest !== from) moveConfigTo(id, dest)
}
function onDragUp() {
  endDrag(true)
}
function onDragCancel() {
  endDrag(false)
}
function startDrag(e: PointerEvent | MouseEvent, id: string) {
  if (!sortable.value || ('button' in e && e.button !== 0)) return
  e.preventDefault()
  dragId.value = id
  dropIndex.value = dropIndexAt(e.clientY)
  document.addEventListener('pointermove', onDragMove)
  document.addEventListener('pointerup', onDragUp)
  document.addEventListener('pointercancel', onDragCancel)
}
onBeforeUnmount(() => endDrag(false))

// 命令排序：同一套乐观/串行/回滚逻辑
const commandOrder = useOrderedList(
  computed(() => selectedConfig.value?.commands ?? []),
  {
    commit: (ids, rev) => {
      const cfg = selectedConfig.value
      if (!cfg) return Promise.reject(new Error('没有选中的发布配置'))
      return actions.orderCommands(cfg.id, ids, rev)
    },
    revision: () => revision.value,
    onError: (e) => {
      commandOpError.value = e
    },
  },
)
const commandsConfig = computed<ReleaseView | null>(() =>
  selectedConfig.value
    ? ({ ...selectedConfig.value, commands: commandOrder.items.value } as ReleaseView)
    : null,
)
function moveCommand(cmd: CommandView, direction: -1 | 1) {
  commandOrder.moveBy(cmd.id, direction)
}
</script>

<template>
  <div class="tasks-page" data-testid="tasks-page">
    <!-- 左侧：发布配置列表（只显示配置名称，命令不在这里展开） -->
    <section aria-label="任务列表" class="tasks-listcol">
      <header class="topbar" data-tauri-drag-region>
        <div class="header-title-wrap">
          <h1>任务</h1>
          <span class="sub-meta">
            {{ configs.length }} 个发布配置<template v-if="activeRunsCount > 0"
              >，{{ activeRunsCount }} 个正在运行</template
            >
          </span>
        </div>
        <span class="spacer"></span>
        <ToolbarButton label="新建发布配置" data-testid="new-task-btn" @click="openCreateConfig">
          <Plus :size="16" aria-hidden="true" />
        </ToolbarButton>
      </header>

      <div class="filters-bar">
        <SearchField v-model="keyword" label="搜索发布配置" placeholder="搜索配置、仓库、分支" />
        <SegmentedControl
          v-model="filter"
          :items="filterTabs"
          label="筛选发布配置"
          panel-id="tasks-list-panel"
          fill
        />
      </div>

      <div id="tasks-list-panel" role="tabpanel" class="tasks-list-body">
        <!-- 读取中骨架 -->
        <template v-if="configsQuery.isPending.value && online">
          <Skeleton />
          <p class="sr-only" role="status">读取发布配置中…</p>
        </template>

        <!-- 完全没有配置时的空态 -->
        <EmptyState
          v-else-if="configs.length === 0"
          :icon="ListChecks"
          title="还没有任务"
          description="发布配置把仓库、分支、Git 规则和发布目标放在一起，配上运行命令后一次点击完成“同步分支 → 构建 → 发布”。可以从旧应用导入，或新建一个。"
          data-testid="tasks-empty-state"
        >
          <template #actions>
            <Button data-testid="goto-import-btn" @click="router.push('/settings')">
              从旧配置导入…
            </Button>
            <Button variant="primary" data-testid="create-first-task-btn" @click="openCreateConfig">
              新建发布配置
            </Button>
          </template>
        </EmptyState>

        <!-- 搜索无结果 -->
        <p v-else-if="filteredConfigs.length === 0" class="empty-search-text">没有匹配的发布配置</p>

        <!-- 配置列表 -->
        <ul v-else ref="rowsEl" class="tasks-rows" aria-label="发布配置列表项">
          <li
            v-for="c in filteredConfigs"
            :key="c.id"
            class="row"
            :data-row-id="c.id"
            :data-drag="dragId === c.id ? 'true' : undefined"
            :data-drop="
              dragId && dropIndex === filteredConfigs.indexOf(c)
                ? 'before'
                : dragId &&
                    dropIndex === filteredConfigs.length &&
                    c === filteredConfigs[filteredConfigs.length - 1]
                  ? 'after'
                  : undefined
            "
            @keydown="onRowKey($event, c.id)"
          >
            <button
              v-if="sortable"
              type="button"
              class="row-handle"
              :aria-label="`拖动调整顺序：${c.name}`"
              :data-testid="`row-handle-${c.id}`"
              @pointerdown="startDrag($event, c.id)"
            >
              <GripVertical :size="14" aria-hidden="true" />
            </button>
            <TaskListItem
              :name="c.name"
              :when="rowWhen(c)"
              :pill="resolveConfigPillState(c, c.id === selectedConfigId, runStatus)"
              :dots="rowDots(c)"
              :color="repoLineColor(configRepoName(c))"
              :selected="c.id === selectedConfigId"
              :data-testid="`task-row-${c.id}`"
              @click="onSelectConfig(c.id)"
            />
            <div class="row-menu">
              <OverflowMenu :label="`排序与更多：${c.name}`">
                <p v-if="!sortable" class="menu-hint" :data-testid="`row-sort-hint-${c.id}`">
                  {{ SORT_HINT }}
                </p>
                <button
                  type="button"
                  role="menuitem"
                  class="menu-item"
                  :disabled="!sortable || configIndex(c.id) <= 0"
                  :title="sortable ? undefined : SORT_HINT"
                  :data-testid="`row-move-up-${c.id}`"
                  @click="moveConfigBy(c.id, -1)"
                >
                  <ArrowUp :size="14" aria-hidden="true" />
                  上移
                </button>
                <button
                  type="button"
                  role="menuitem"
                  class="menu-item"
                  :disabled="!sortable || configIndex(c.id) >= orderedConfigs.length - 1"
                  :title="sortable ? undefined : SORT_HINT"
                  :data-testid="`row-move-down-${c.id}`"
                  @click="moveConfigBy(c.id, 1)"
                >
                  <ArrowDown :size="14" aria-hidden="true" />
                  下移
                </button>
                <button
                  type="button"
                  role="menuitem"
                  class="menu-item"
                  :disabled="!sortable || configIndex(c.id) <= 0"
                  :title="sortable ? undefined : SORT_HINT"
                  :data-testid="`row-move-top-${c.id}`"
                  @click="moveConfigTo(c.id, 0)"
                >
                  <ChevronsUp :size="14" aria-hidden="true" />
                  移到顶部
                </button>
                <button
                  type="button"
                  role="menuitem"
                  class="menu-item"
                  :disabled="!sortable || configIndex(c.id) >= orderedConfigs.length - 1"
                  :title="sortable ? undefined : SORT_HINT"
                  :data-testid="`row-move-bottom-${c.id}`"
                  @click="moveConfigTo(c.id, orderedConfigs.length - 1)"
                >
                  <ChevronsDown :size="14" aria-hidden="true" />
                  移到底部
                </button>
              </OverflowMenu>
            </div>
          </li>
        </ul>
      </div>
    </section>

    <!-- 中间：配置详情 -->
    <div class="tasks-detailcol">
      <header class="topbar detail-topbar" data-tauri-drag-region>
        <template v-if="selectedConfig">
          <!-- 主操作：运行（墨色实底，全视图只有这一个主按钮）与只发布；都先选一条运行命令 -->
          <Button
            variant="primary"
            data-testid="run-task-btn"
            :disabled="!online"
            @click="openPicker('sync_build_release')"
          >
            <Play :size="12" fill="currentColor" aria-hidden="true" />
            运行
          </Button>

          <Button
            variant="default"
            data-testid="deploy-only-btn"
            :disabled="!online"
            @click="openPicker('deploy_only')"
          >
            <Upload :size="13" aria-hidden="true" />
            只发布
          </Button>

          <!-- 详情区 ≥560px 时回滚/编辑直接摆在工具条；更窄时只在「⋯」菜单里出现（CSS 容器查询切换） -->
          <Button
            variant="default"
            class="wide-only"
            data-testid="rollback-btn"
            :disabled="!online"
            @click="openPicker('rollback')"
          >
            <RotateCcw :size="13" aria-hidden="true" />
            回滚…
          </Button>
          <Button
            variant="default"
            class="wide-only"
            data-testid="edit-task-btn"
            aria-label="编辑发布配置"
            @click="openEditConfig"
          >
            <Pencil :size="13" aria-hidden="true" />
            编辑配置
          </Button>

          <OverflowMenu label="更多操作">
            <button
              type="button"
              role="menuitem"
              class="menu-item narrow-only"
              data-testid="rollback-menu-item"
              :disabled="!online"
              @click="openPicker('rollback')"
            >
              <RotateCcw :size="14" aria-hidden="true" />
              回滚…
            </button>
            <button
              type="button"
              role="menuitem"
              class="menu-item narrow-only"
              data-testid="edit-task-menu-item"
              @click="openEditConfig"
            >
              <Pencil :size="14" aria-hidden="true" />
              编辑配置
            </button>
            <div class="menu-sep narrow-only" role="separator"></div>
            <button
              type="button"
              role="menuitem"
              class="menu-item"
              data-testid="move-up-task-btn"
              @click="moveConfig(-1)"
            >
              <ArrowUp :size="14" aria-hidden="true" />
              上移
            </button>
            <button
              type="button"
              role="menuitem"
              class="menu-item"
              data-testid="move-down-task-btn"
              @click="moveConfig(1)"
            >
              <ArrowDown :size="14" aria-hidden="true" />
              下移
            </button>
            <div class="menu-sep" role="separator"></div>
            <button
              type="button"
              role="menuitem"
              class="menu-item"
              data-danger="true"
              data-testid="delete-task-btn"
              @click="openDeleteConfig"
            >
              <Trash2 :size="14" aria-hidden="true" />
              删除配置
            </button>
          </OverflowMenu>

          <span class="spacer"></span>
          <InspectorToggle />
        </template>
      </header>

      <section aria-label="任务详情" class="tasks-detailbody">
        <template v-if="selectedConfig">
          <div class="detail-content">
            <!-- 标题区：标题是配置名称，不显示英文命令 -->
            <h2 class="task-title" data-testid="task-title">{{ selectedConfig.name }}</h2>
            <div class="task-sub-info">
              <span class="repo-tag" data-testid="task-repo">
                {{ selectedConfig.repo_name || selectedConfig.local_repo_path }}
              </span>
              <span data-testid="task-branch-count">
                <GitBranch :size="13" aria-hidden="true" />
                {{ selectedConfig.branches?.length ?? 0 }} 个分支
              </span>
              <span data-testid="task-target-count">
                <Target :size="13" aria-hidden="true" />
                {{ selectedConfig.targets?.length ?? 0 }} 个发布目标
              </span>
              <span data-testid="task-command-count">
                <Terminal :size="13" aria-hidden="true" />
                {{ selectedConfig.commands.length }} 条运行命令
              </span>
            </div>

            <Banner
              v-if="configSavedNotice"
              kind="info"
              class="op-error"
              data-testid="config-saved-notice"
            >
              {{ configSavedNotice }}
            </Banner>

            <Banner
              v-if="configOpError"
              kind="error"
              class="op-error"
              data-testid="config-op-error"
            >
              {{ releaseErrorText(configOpError) }}
            </Banner>

            <!-- 需要核实 (Unknown) 告警横幅 -->
            <div v-if="isUnknown" class="unknown-banner" role="status" data-testid="unknown-banner">
              <AlertTriangle :size="18" class="unknown-icon" aria-hidden="true" />
              <div class="unknown-body">
                <div class="unknown-title">结果需要核实</div>
                <div class="unknown-desc">
                  {{ unknownDesc }}
                </div>
                <div class="unknown-warn-note">注意：停止不会回滚已部署内容。</div>
                <div class="unknown-actions">
                  <Button
                    variant="default"
                    data-testid="reconcile-btn"
                    :disabled="reconciling"
                    @click="onReconcile"
                  >
                    {{ reconciling ? '正在核对…' : '立即核对' }}
                  </Button>
                </div>
              </div>
            </div>

            <!-- 本次运行卡片（步骤 + 实时日志），标明是哪条命令 -->
            <RunCard
              v-if="currentRun"
              :run="currentRun"
              :steps="steps"
              :lines="lines"
              :total-line-count="totalLineCount"
              :loading="logsLoading"
              :warning="gapWarning"
              :color="selectedLineColor"
              :command-name="currentCommandName"
              :branch-text="currentRun ? commandBranches[currentRun.task_id] : undefined"
              @cancel="onCancelRun"
            />

            <!-- 运行命令：新建、编辑、删除、排序 -->
            <CommandSection
              v-if="commandsConfig"
              :config="commandsConfig"
              :error="commandOpError"
              @create="openCreateCommand"
              @edit="openEditCommand"
              @delete="openDeleteCommand"
              @move="moveCommand"
            />

            <!-- 运行记录：配置下所有命令的运行 -->
            <RunHistory
              :runs="historyRuns"
              :selected-run-id="inspectedRunId"
              :color="selectedLineColor"
              :command-names="commandNames"
              :command-branches="commandBranches"
              @select="onSelectHistoryRun"
            />
          </div>
        </template>
        <div v-else class="no-selection-placeholder">未选择发布配置</div>
      </section>
    </div>

    <!-- 右侧：检查器 -->
    <TaskInspector v-if="selectedConfig" :config="selectedConfig" />

    <!-- 弹窗 Sheets -->
    <CommandPickerSheet
      v-model:open="pickerOpen"
      :config="selectedConfig"
      :operation="pickerOperation"
      @pick="onPickCommand"
    />

    <RunConfirmSheet
      v-model:open="confirmSheetOpen"
      :task="selectedConfig"
      :command-name="pickedCommand?.name"
      :branch="pickedBranch"
      :route-text="pickedRouteText"
      :operation="confirmOperation"
      :plan="confirmPlan"
      :submitting="confirmSubmitting"
      :loading="confirmLoading"
      :error="confirmError"
      @confirm="onStartConfirm"
      @retry="retryPreflight"
      @open-config="onConfirmOpenConfig"
    />

    <TaskRollbackSheet
      v-model:open="rollbackSheetOpen"
      :task="selectedConfig"
      :command-name="pickedCommand?.name"
      @submit="onRollbackOffsetChosen"
    />

    <ReleaseWizardSheet
      :open="editSheetOpen && !configToEdit"
      :revision="revision"
      @update:open="editSheetOpen = $event"
      @created="onWizardCreated"
      @edit-existing="openEditConfigById"
    />

    <TaskEditSheet
      :open="editSheetOpen && Boolean(configToEdit)"
      :config="configToEdit"
      :revision="editBaseRevision"
      :submitting="editSubmitting"
      :error="editError"
      @update:open="editSheetOpen = $event"
      @save="onSaveConfig"
    />

    <CommandEditSheet
      v-model:open="commandSheetOpen"
      :config="selectedConfig"
      :command="commandToEdit"
      :revision="commandBaseRevision"
      :submitting="commandSubmitting"
      :error="commandError"
      @save="onSaveCommand"
    />

    <TaskDeleteSheet
      v-model:open="deleteSheetOpen"
      :task="deleteTarget"
      :kind="deleteTarget?.kind"
      :command-count="deleteTarget?.kind === 'config' ? deleteTarget.commandCount : 0"
      :submitting="deleteSubmitting"
      :error="deleteError"
      @confirm="onConfirmDelete(false)"
      @confirm-detach="onConfirmDelete(true)"
    />
  </div>
</template>

<style scoped>
.tasks-page {
  flex: 1;
  min-width: 0;
  display: flex;
  overflow: hidden;
}
.tasks-listcol {
  /* 规范：≥1440 列表 320；窄窗 300；960–1099 为 280 */
  width: 300px;
  flex: none;
  border-right: 1px solid var(--line);
  background: var(--bg-list);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
@media (min-width: 1440px) {
  .tasks-listcol {
    width: var(--list-w);
  }
}
@media (max-width: 1099px) {
  .tasks-listcol {
    width: 280px;
  }
}
.topbar {
  flex: none;
  display: flex;
  align-items: center;
  height: var(--topbar-h);
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
  gap: 8px;
}
.header-title-wrap {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
h1 {
  margin: 0;
  font-size: var(--text-page);
  font-weight: 700;
  color: var(--ink);
}
.sub-meta {
  font-size: var(--text-sub);
  color: var(--mute);
}
.spacer {
  flex: 1;
}
.filters-bar {
  /* 搜索 + 分段控件为一组：组内 --sp-2；离上方分隔线与左右同为 --sp-4（容得下 3px 聚焦外扩）；离列表略大 */
  flex: none;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-4) var(--sp-4) var(--sp-3);
}
.tasks-list-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.row {
  position: relative;
}
/* 手柄占用行左侧固定的 14px 槽位（悬停/聚焦/拖动时才显现），不挤压标题 */
.row :deep(.task-item) {
  padding-left: 18px;
  padding-right: 34px;
}
.row-handle {
  position: absolute;
  left: 2px;
  top: 50%;
  translate: 0 -50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--mute);
  cursor: grab;
  touch-action: none;
  opacity: 0;
}
.row:hover .row-handle,
.row:focus-within .row-handle,
.row[data-drag='true'] .row-handle {
  opacity: 1;
}
.row-handle:active {
  cursor: grabbing;
}
.row-menu {
  position: absolute;
  right: 4px;
  top: 6px;
  opacity: 0;
}
.row:hover .row-menu,
.row:focus-within .row-menu,
.row[data-drag='true'] .row-menu {
  opacity: 1;
}
.row[data-drag='true'] {
  opacity: 0.55;
}
/* 插入位置指示线 */
.row[data-drop='before']::before,
.row[data-drop='after']::after {
  content: '';
  position: absolute;
  left: 4px;
  right: 4px;
  height: 2px;
  border-radius: 1px;
  background: var(--accent);
}
.row[data-drop='before']::before {
  top: -2px;
}
.row[data-drop='after']::after {
  bottom: -2px;
}
.menu-hint {
  margin: 0;
  padding: 4px 10px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.tasks-rows {
  margin: 0;
  padding: 4px 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  list-style: none;
}
.empty-search-text {
  margin: 0;
  padding: 24px;
  text-align: center;
  color: var(--mute);
}
.tasks-detailcol {
  flex: 1;
  min-width: 0;
  /* 详情区自己的宽度（不是窗口宽度）决定工具条怎么收：<560px 时次要操作进「⋯」 */
  container: detail / inline-size;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg-window);
}
.detail-topbar {
  padding: 0 16px;
  gap: 6px;
  white-space: nowrap;
  min-width: 0;
}
@container detail (max-width: 559px) {
  .wide-only {
    display: none;
  }
}
@container detail (min-width: 560px) {
  .narrow-only {
    display: none;
  }
}
.tasks-detailbody {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.detail-content {
  padding: 18px 20px 24px;
  max-width: 860px;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.task-title {
  margin: 0;
  font-size: 20px;
  font-weight: 650;
  color: var(--ink);
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}
/* 元信息：图标分隔，不用中点拼接；每项不折行，放不下时整项换到下一行 */
.task-sub-info {
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 4px 14px;
  font-size: var(--text-body);
  color: var(--mute);
  flex-wrap: wrap;
}
.task-sub-info > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.task-sub-info svg {
  color: var(--faint);
}
.op-error {
  margin-top: 12px;
}
/* 仓库归属标记：仓库线路色的小色条 */
.repo-tag::before {
  content: '';
  width: 10px;
  height: 3px;
  border-radius: 2px;
  background: v-bind(selectedLineColor);
}
.unknown-banner {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--bn-warn-bg);
  box-shadow: inset 0 0 0 1px var(--bn-warn-line);
  display: flex;
  gap: 10px;
}
.unknown-icon {
  color: var(--bn-warn-fg);
  flex: none;
  margin-top: 2px;
}
.unknown-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.unknown-title {
  font-weight: 600;
  color: var(--bn-warn-fg);
}
.unknown-desc {
  font-size: var(--text-body);
  color: color-mix(in srgb, var(--bn-warn-fg) 80%, black);
}
.unknown-warn-note {
  font-size: 11px;
  font-weight: 500;
  color: var(--bn-warn-fg);
}
.unknown-actions {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}
.no-selection-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--mute);
  font-size: 15px;
}
.mono {
  font-family: var(--font-mono);
}
</style>
