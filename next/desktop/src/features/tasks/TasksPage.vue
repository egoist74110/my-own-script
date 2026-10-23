<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  FileDown,
  ListChecks,
  Play,
  Plus,
  RotateCcw,
  Trash2,
} from 'lucide-vue-next'
import Button from '@/components/Button.vue'
import EmptyState from '@/components/EmptyState.vue'
import InspectorToggle from '@/components/InspectorToggle.vue'
import ListRow from '@/components/ListRow.vue'
import SearchField from '@/components/SearchField.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import Skeleton from '@/components/Skeleton.vue'
import StatusPill from '@/components/StatusPill.vue'
import ToolbarButton from '@/components/ToolbarButton.vue'
import {
  formatRelativeTime,
  formatRepoShort,
  resolveRowPillState,
  unwrap,
  type PlanResponse,
  type RunResponse,
  type TaskCreate,
  type TaskOperation,
  type TaskPatch,
  type TaskView,
} from './api'
import { useTasksApi, useTasksList, useTaskRuns } from './queries'
import { useRunLogs } from './useRunLogs'
import RunCard from './RunCard.vue'
import RunConfirmSheet from './RunConfirmSheet.vue'
import RunHistory from './RunHistory.vue'
import TaskDeleteSheet from './TaskDeleteSheet.vue'
import TaskEditSheet from './TaskEditSheet.vue'
import TaskInspector from './TaskInspector.vue'
import TaskRollbackSheet from './TaskRollbackSheet.vue'

const router = useRouter()
const { api, online, qc, runtime } = useTasksApi()

// 本地存储仅保存选中的 task_id（绝不存日志、配置草稿或凭据）
const STORAGE_KEY = 'toolbox.tasks.selection'
function loadSelectedTaskId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}
function saveSelectedTaskId(id: string | null) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 忽略 localStorage 异常
  }
}

// 任务列表 Query
const tasksQuery = useTasksList(online, api)
const tasks = computed<TaskView[]>(() => tasksQuery.data.value?.items ?? [])
const revision = computed(() => tasksQuery.data.value?.revision ?? 0)

// 选中的任务 ID
const selectedTaskId = ref<string | null>(loadSelectedTaskId())

// 选中的任务对象
const selectedTask = computed(() => tasks.value.find((t) => t.id === selectedTaskId.value) ?? null)

// 当任务列表更新，确保选择合法
watch(
  tasks,
  (list) => {
    if (list.length === 0) {
      selectedTaskId.value = null
      saveSelectedTaskId(null)
      return
    }
    if (selectedTaskId.value && list.some((t) => t.id === selectedTaskId.value)) return
    const first = list[0]
    if (first) {
      selectedTaskId.value = first.id
      saveSelectedTaskId(first.id)
    }
  },
  { immediate: true },
)

watch(selectedTaskId, (id) => {
  saveSelectedTaskId(id)
})

// 搜索与过滤
const keyword = ref('')
const filter = ref<'all' | 'running' | 'attention'>('all')

const filterTabs = computed(() => {
  const runningCount = tasks.value.filter((t) => Boolean(t.active_run_id)).length
  const attentionCount = tasks.value.filter(
    (t) => !t.validation?.valid || (t.warnings && t.warnings.length > 0),
  ).length
  return [
    { value: 'all', label: '全部' },
    { value: 'running', label: '运行中', count: runningCount || undefined },
    { value: 'attention', label: '需处理', count: attentionCount || undefined },
  ]
})

const filteredTasks = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return tasks.value.filter((t) => {
    // 文本匹配
    if (q) {
      const matchName = t.name.toLowerCase().includes(q)
      const matchRepo = (t.repo_name ?? t.local_repo_path).toLowerCase().includes(q)
      const matchBranch = (t.git_flow?.build_branch ?? '').toLowerCase().includes(q)
      if (!matchName && !matchRepo && !matchBranch) return false
    }
    // 状态分类过滤
    if (filter.value === 'running') {
      return Boolean(t.active_run_id)
    }
    if (filter.value === 'attention') {
      return !t.validation?.valid || (t.warnings && t.warnings.length > 0)
    }
    return true
  })
})

const activeRunsCount = computed(() => tasks.value.filter((t) => Boolean(t.active_run_id)).length)

// 运行记录列表
const runsQuery = useTaskRuns(selectedTaskId, online, api)
const historyRuns = computed<RunResponse[]>(() => runsQuery.data.value?.items ?? [])

// 当前选中的运行 ID
const inspectedRunId = ref<string | null>(null)
// 用户手动选择的运行 ID，防止后台刷新抢回焦点
const userSelectedRunId = ref<string | null>(null)

function onSelectTask(taskId: string) {
  selectedTaskId.value = taskId
  userSelectedRunId.value = null
}

function onSelectHistoryRun(run: RunResponse) {
  userSelectedRunId.value = run.run_id
  inspectedRunId.value = run.run_id
}

watch(
  [selectedTask, historyRuns],
  ([task, runs]) => {
    // 若任务有活动运行，自动跟随活动运行
    if (task?.active_run_id) {
      userSelectedRunId.value = null
      inspectedRunId.value = task.active_run_id
      return
    }

    // 若用户手动选择过某次运行且仍在当前历史中，不要被后台刷新抢回
    if (userSelectedRunId.value && runs.some((r) => r.run_id === userSelectedRunId.value)) {
      inspectedRunId.value = userSelectedRunId.value
      return
    }

    // 默认展示最新一条：优先 task.last_run.run_id，否则取 desc 历史第一条
    if (task?.last_run?.run_id) {
      inspectedRunId.value = task.last_run.run_id
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
} = useRunLogs(inspectedRunId, runtime, online, api)

// 运行从活动态进入终态或未知态时，自动刷新任务列表活跃状态与历史运行记录
watch(runStatus, async (newStatus, oldStatus) => {
  const wasActive = oldStatus === 'queued' || oldStatus === 'running' || oldStatus === 'cancelling'
  const isTerminal =
    newStatus === 'succeeded' ||
    newStatus === 'failed' ||
    newStatus === 'cancelled' ||
    newStatus === 'unknown'

  if (wasActive && isTerminal) {
    await qc.invalidateQueries({ queryKey: ['tasks'] })
    if (selectedTaskId.value) {
      await qc.invalidateQueries({ queryKey: ['runs', selectedTaskId.value] })
    }
  }
})

// 状态横幅逻辑
const isUnknown = computed(
  () => runStatus.value === 'unknown' || currentRun.value?.status === 'unknown',
)
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
    await qc.invalidateQueries({ queryKey: ['run', inspectedRunId.value] })
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

// 预检与执行计划确认 Sheet
const confirmSheetOpen = ref(false)
const confirmOperation = ref<TaskOperation>('sync_build_release')
const confirmPlan = ref<PlanResponse | null>(null)
const confirmSubmitting = ref(false)
const confirmError = ref<unknown>(null)

async function startPreflight(operation: TaskOperation, rollbackOffset?: number) {
  if (!selectedTaskId.value) return
  confirmOperation.value = operation
  confirmError.value = null
  confirmPlan.value = null
  try {
    const plan = await unwrap(
      api().POST('/api/tasks/{task_id}/preflight', {
        params: { path: { task_id: selectedTaskId.value } },
        body: {
          operation,
          revision: revision.value,
          rollback_offset: rollbackOffset,
        },
      }),
    )
    confirmPlan.value = plan
    confirmSheetOpen.value = true
  } catch (e) {
    confirmError.value = e
    confirmSheetOpen.value = true
  }
}

async function onStartConfirm(payload: { planId: string; requestId: string; ack: true }) {
  if (confirmSubmitting.value) return
  if (!selectedTaskId.value) return
  confirmSubmitting.value = true
  confirmError.value = null
  try {
    const res = await unwrap(
      api().POST('/api/tasks/{task_id}/runs', {
        params: { path: { task_id: selectedTaskId.value } },
        body: {
          plan_id: payload.planId,
          request_id: payload.requestId,
          ack_old_app_idle: true,
        },
      }),
    )
    confirmSheetOpen.value = false
    userSelectedRunId.value = null
    inspectedRunId.value = res.run_id
    await qc.invalidateQueries({ queryKey: ['tasks'] })
    await qc.invalidateQueries({ queryKey: ['runs', selectedTaskId.value] })
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

// 新建 / 编辑任务 Sheet
const editSheetOpen = ref(false)
const taskToEdit = ref<TaskView | null>(null)
const editSubmitting = ref(false)
const editError = ref<unknown>(null)

function openCreateTask() {
  taskToEdit.value = null
  editError.value = null
  editSheetOpen.value = true
}

function openEditTask() {
  if (!selectedTask.value) return
  taskToEdit.value = selectedTask.value
  editError.value = null
  editSheetOpen.value = true
}

async function onSaveTask(payload: TaskCreate | TaskPatch) {
  editSubmitting.value = true
  editError.value = null
  try {
    if (taskToEdit.value) {
      await unwrap(
        api().PATCH('/api/tasks/{task_id}', {
          params: { path: { task_id: taskToEdit.value.id } },
          body: payload as TaskPatch,
        }),
      )
    } else {
      const res = await unwrap(
        api().POST('/api/tasks', {
          body: payload as TaskCreate,
        }),
      )
      if (res.id) {
        selectedTaskId.value = res.id
      }
    }
    editSheetOpen.value = false
    await qc.invalidateQueries({ queryKey: ['tasks'] })
  } catch (e) {
    editError.value = e
  } finally {
    editSubmitting.value = false
  }
}

// 删除任务 Sheet
const deleteSheetOpen = ref(false)
const deleteSubmitting = ref(false)
const deleteError = ref<unknown>(null)

function openDeleteTask() {
  if (!selectedTask.value) return
  deleteError.value = null
  deleteSheetOpen.value = true
}

async function onConfirmDeleteTask() {
  if (!selectedTask.value) return
  deleteSubmitting.value = true
  deleteError.value = null
  try {
    await unwrap(
      api().DELETE('/api/tasks/{task_id}', {
        params: {
          path: { task_id: selectedTask.value.id },
          query: { revision: revision.value },
        },
      }),
    )
    deleteSheetOpen.value = false
    selectedTaskId.value = null
    await qc.invalidateQueries({ queryKey: ['tasks'] })
  } catch (e) {
    deleteError.value = e
  } finally {
    deleteSubmitting.value = false
  }
}

// 排序：上移 / 下移
async function moveTask(direction: -1 | 1) {
  if (!selectedTask.value) return
  const list = [...tasks.value]
  const idx = list.findIndex((t) => t.id === selectedTask.value!.id)
  if (idx < 0) return
  const targetIdx = idx + direction
  if (targetIdx < 0 || targetIdx >= list.length) return

  // 交换位置
  const temp = list[idx]!
  list[idx] = list[targetIdx]!
  list[targetIdx] = temp

  try {
    await unwrap(
      api().PUT('/api/tasks/order', {
        body: {
          ids: list.map((t) => t.id),
          revision: revision.value,
        },
      }),
    )
    await qc.invalidateQueries({ queryKey: ['tasks'] })
  } catch {
    // 排序冲突刷新
    await qc.invalidateQueries({ queryKey: ['tasks'] })
  }
}
</script>

<template>
  <div class="tasks-page" data-testid="tasks-page">
    <!-- 左侧：任务列表 -->
    <section aria-label="任务列表" class="tasks-listcol">
      <header class="topbar" data-tauri-drag-region>
        <div class="header-title-wrap">
          <h1>任务</h1>
          <span class="sub-meta">
            {{ tasks.length }} 个任务
            <template v-if="activeRunsCount > 0"> · {{ activeRunsCount }} 运行中</template>
          </span>
        </div>
        <span class="spacer"></span>
        <ToolbarButton label="新建任务" data-testid="new-task-btn" @click="openCreateTask">
          <Plus :size="16" aria-hidden="true" />
        </ToolbarButton>
      </header>

      <div class="filters-bar">
        <SearchField v-model="keyword" label="搜索任务" placeholder="搜索任务、仓库、分支" />
        <SegmentedControl
          v-model="filter"
          :items="filterTabs"
          label="筛选任务"
          panel-id="tasks-list-panel"
          fill
        />
      </div>

      <!-- 任务列表容器 -->
      <div id="tasks-list-panel" role="tabpanel" class="tasks-list-body">
        <!-- 读取中骨架 -->
        <template v-if="tasksQuery.isPending.value && online">
          <Skeleton />
          <p class="sr-only" role="status">读取任务中…</p>
        </template>

        <!-- 完全没有任务时的空态 -->
        <EmptyState
          v-else-if="tasks.length === 0"
          :icon="ListChecks"
          title="还没有任务"
          description="任务把“同步分支 → 构建 → 发布”串成一次点击。可以从旧应用导入，或新建一个。"
          data-testid="tasks-empty-state"
        >
          <template #actions>
            <Button data-testid="goto-import-btn" @click="router.push('/settings')">
              从旧配置导入…
            </Button>
            <Button variant="primary" data-testid="create-first-task-btn" @click="openCreateTask">
              新建任务
            </Button>
          </template>
        </EmptyState>

        <!-- 搜索无结果 -->
        <p v-else-if="filteredTasks.length === 0" class="empty-search-text">没有匹配的任务</p>

        <!-- 任务列表 -->
        <ul v-else class="b-list tasks-rows" aria-label="任务列表项">
          <li v-for="t in filteredTasks" :key="t.id">
            <ListRow
              :title="t.name"
              :meta="t.last_run?.created_at ? formatRelativeTime(t.last_run.created_at) : '未运行'"
              :selected="t.id === selectedTaskId"
              :data-testid="`task-row-${t.id}`"
              @click="onSelectTask(t.id)"
            >
              <template #default>
                <div class="task-row-meta">
                  <span class="task-repo-branch mono">
                    {{ formatRepoShort(t.repo_name, t.local_repo_path) }} ·
                    {{ t.git_flow?.build_branch || 'main' }}
                  </span>
                  <span
                    v-if="resolveRowPillState(t, t.id === selectedTaskId, runStatus)"
                    class="row-pill-wrap"
                  >
                    <StatusPill
                      :state="resolveRowPillState(t, t.id === selectedTaskId, runStatus)!"
                    />
                  </span>
                </div>
              </template>
            </ListRow>
          </li>
        </ul>
      </div>
    </section>

    <!-- 中间：任务详情 -->
    <div class="tasks-detailcol">
      <header class="topbar detail-topbar" data-tauri-drag-region>
        <template v-if="selectedTask">
          <Button
            variant="primary"
            data-testid="run-task-btn"
            :disabled="!selectedTask.enabled || !online"
            @click="startPreflight('sync_build_release')"
          >
            <Play :size="12" fill="currentColor" aria-hidden="true" />
            运行
          </Button>

          <!-- 只发布 / 回滚 动作 -->
          <Button
            variant="default"
            data-testid="deploy-only-btn"
            :disabled="!selectedTask.enabled || !online"
            @click="startPreflight('deploy_only')"
          >
            <FileDown :size="13" aria-hidden="true" />
            只发布
          </Button>

          <Button
            variant="default"
            data-testid="rollback-btn"
            :disabled="!selectedTask.enabled || !online"
            @click="rollbackSheetOpen = true"
          >
            <RotateCcw :size="13" aria-hidden="true" />
            回滚…
          </Button>

          <span class="spacer"></span>

          <!-- 编辑 / 上移 / 下移 / 删除 -->
          <ToolbarButton label="编辑任务" data-testid="edit-task-btn" @click="openEditTask">
            编辑
          </ToolbarButton>

          <ToolbarButton label="上移" data-testid="move-up-task-btn" @click="moveTask(-1)">
            <ArrowUp :size="14" aria-hidden="true" />
          </ToolbarButton>

          <ToolbarButton label="下移" data-testid="move-down-task-btn" @click="moveTask(1)">
            <ArrowDown :size="14" aria-hidden="true" />
          </ToolbarButton>

          <ToolbarButton label="删除任务" data-testid="delete-task-btn" @click="openDeleteTask">
            <Trash2 :size="14" aria-hidden="true" />
          </ToolbarButton>

          <span class="bar-divider"></span>
          <InspectorToggle />
        </template>
      </header>

      <section aria-label="任务详情" class="tasks-detailbody">
        <template v-if="selectedTask">
          <div class="detail-content">
            <!-- 标题区 -->
            <h2 class="task-title" data-testid="task-title">{{ selectedTask.name }}</h2>
            <div class="task-sub-info">
              <span>{{ selectedTask.project_id || 'Portal' }}</span>
              <span aria-hidden="true">·</span>
              <span class="mono">{{ selectedTask.repo_name || selectedTask.local_repo_path }}</span>
              <span aria-hidden="true">·</span>
              <span>构建分支 {{ selectedTask.git_flow?.build_branch || 'main' }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ selectedTask.targets?.length ?? 0 }} 个目标</span>
              <template v-if="selectedTask.tg_command">
                <span aria-hidden="true">·</span>
                <span class="mono">TG {{ selectedTask.tg_command }}</span>
              </template>
            </div>

            <!-- 需要核实 (Unknown) 告警横幅 -->
            <div v-if="isUnknown" class="unknown-banner" role="status" data-testid="unknown-banner">
              <AlertTriangle :size="18" class="unknown-icon" aria-hidden="true" />
              <div class="unknown-body">
                <div class="unknown-title">结果需要核实</div>
                <div class="unknown-desc">
                  {{
                    runSummary ||
                    '创建 Release 时连接中断，无法确认 ADO 是否已收到请求。工具箱不会自动重发；每 30 秒只读核对一次，最长 15 分钟。'
                  }}
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

            <!-- 本次运行卡片（步骤 + 实时日志） -->
            <RunCard
              v-if="currentRun"
              :run="currentRun"
              :steps="steps"
              :lines="lines"
              :total-line-count="totalLineCount"
              :loading="logsLoading"
              :warning="gapWarning"
              @cancel="onCancelRun"
            />

            <!-- 运行历史表 -->
            <RunHistory
              :runs="historyRuns"
              :selected-run-id="inspectedRunId"
              @select="onSelectHistoryRun"
            />
          </div>
        </template>
        <div v-else class="no-selection-placeholder">未选择任务</div>
      </section>
    </div>

    <!-- 右侧：检查器 -->
    <TaskInspector v-if="selectedTask" :task="selectedTask" />

    <!-- 弹窗 Sheets -->
    <RunConfirmSheet
      v-model:open="confirmSheetOpen"
      :task="selectedTask"
      :operation="confirmOperation"
      :plan="confirmPlan"
      :submitting="confirmSubmitting"
      :error="confirmError"
      @confirm="onStartConfirm"
    />

    <TaskRollbackSheet
      v-model:open="rollbackSheetOpen"
      :task="selectedTask"
      @submit="onRollbackOffsetChosen"
    />

    <TaskEditSheet
      v-model:open="editSheetOpen"
      :task="taskToEdit"
      :revision="revision"
      :submitting="editSubmitting"
      :error="editError"
      @save="onSaveTask"
    />

    <TaskDeleteSheet
      v-model:open="deleteSheetOpen"
      :task="selectedTask"
      :submitting="deleteSubmitting"
      :error="deleteError"
      @confirm="onConfirmDeleteTask"
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
  width: 320px;
  flex: none;
  border-right: 1px solid var(--line);
  background: var(--bg-list);
  display: flex;
  flex-direction: column;
  min-height: 0;
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
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 12px 10px;
}
.tasks-list-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.tasks-rows {
  margin: 0;
  padding: 0 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  list-style: none;
}
.task-row-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sub);
  color: var(--mute);
  width: 100%;
  min-width: 0;
}
.task-repo-branch {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.row-pill-wrap {
  flex: none;
  margin-left: auto;
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
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg-window);
}
.detail-topbar {
  padding: 0 16px;
  gap: 8px;
}
.bar-divider {
  width: 1px;
  height: 18px;
  background: var(--line);
  margin: 0 4px;
}
.tasks-detailbody {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.detail-content {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
}
.task-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.2px;
}
.task-sub-info {
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sub);
  color: var(--mute);
  flex-wrap: wrap;
}
.unknown-banner {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: var(--r-ctl);
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
