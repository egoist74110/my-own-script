<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import {
  CalendarPlus,
  CornerLeftUp,
  ExternalLink,
  Flag,
  GitCommitHorizontal,
  History,
  Link,
  Sparkles,
  User,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import OverflowMenu from '@/components/OverflowMenu.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import SafeHtml from '@/components/SafeHtml.vue'
import Sheet from '@/components/Sheet.vue'
import { createMediaCache, mediaCacheKey } from '@/components/media'
import { openExternal } from '@/components/open-external'
import {
  createWorkItemAiAnalysis,
  fetchWorkItemAiPrompt,
  toApiError,
  type ProfileView,
  type RepoView,
} from '@/features/ai/api'
import { formatAiError } from '@/features/ai/terminal-protocol'
import AttachmentsPane from './AttachmentsPane.vue'
import BoardLine from './BoardLine.vue'
import ChildrenPane from './ChildrenPane.vue'
import CommentsPane from './CommentsPane.vue'
import ErrorNotice from './ErrorNotice.vue'
import HistoryPane from './HistoryPane.vue'
import { badShape, unwrap, type HtmlField, type WorkItemDetail } from './api'
import { formatDate, kindColor } from './format'
import { QUERY_DEFAULTS, WI_KEY, projectKey, useBoardColumns, useWiApi } from './queries'
import './panes.css'

/**
 * 工单详情。本组件由页面以 `${projectId}:${id}` 作 key：切换工单/项目或离开页面即卸载，
 * 页面级媒体缓存随之 clear()（中止请求 + revokeObjectURL 全部 blob）。
 */
const props = defineProps<{ projectId: string; id: number }>()
const emit = defineEmits<{ select: [id: number]; loaded: [detail: WorkItemDetail | null] }>()
const { api, maybeApi, online, qc } = useWiApi()

const { columns: boardColumns } = useBoardColumns()
const media = createMediaCache(maybeApi)
provide(mediaCacheKey, media)
onBeforeUnmount(() => media.clear())

const q = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: [...projectKey(props.projectId), 'detail', props.id],
  enabled: online,
  queryFn: async ({ signal }): Promise<WorkItemDetail> => {
    const d = await unwrap(
      api().GET('/api/work-items/{id}', {
        signal,
        params: { path: { id: props.id }, query: { project_id: props.projectId } },
      }),
    )
    if (typeof d?.id !== 'number' || !Array.isArray(d.attachments) || !d.html) throw badShape()
    return d
  },
})
const d = computed(() => q.data.value ?? null)

const tab = ref('desc')
const tabs = computed(() => [
  { value: 'desc', label: '描述' },
  { value: 'comments', label: '评论' },
  { value: 'children', label: '子项', count: d.value?.child_ids?.length },
  { value: 'history', label: '历史' },
  { value: 'files', label: '附件', count: d.value?.attachments?.length },
])

const sections = computed(() => {
  const h = d.value?.html
  if (!h) return []
  const all: [string, string, HtmlField | null | undefined][] = [
    ['desc', '描述', h.description],
    ['repro', '复现步骤', h.repro_steps],
    ['ac', '验收标准', h.acceptance_criteria],
  ]
  return all.filter(([, , f]) => f && (f.html || f.omitted))
})

// 检查器（页面级）需要详情数据：加载完成时上报，卸载时清空
watch(d, (x) => emit('loaded', x), { immediate: true })
onBeforeUnmount(() => emit('loaded', null))

// 先失效并等当前详情（及已打开的评论）重取完成，再清失败条目：
// 否则旧 id 会先被重试一遍，而新 id 成功后过期提示仍在（CR-S2B-002）
async function refreshDetail() {
  await qc.invalidateQueries({ queryKey: projectKey(props.projectId) })
  media.forgetFailed()
}

const router = useRouter()

// 查询 ADO 仓库列表与 AI 配置（仅在 online 状态下）
const adoQ = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: [...WI_KEY, 'ado'],
  enabled: online,
  queryFn: async ({ signal }) => {
    return unwrap(api().GET('/api/ado', { signal }))
  },
})

const aiQ = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: ['ai', 'overview'],
  enabled: online,
  queryFn: async ({ signal }) => {
    const res = await api().GET('/api/ai', { signal })
    return res.data ?? null
  },
})

const localRepos = computed<RepoView[]>(() => (adoQ.data.value?.local_repos as RepoView[]) ?? [])
const profiles = computed<ProfileView[]>(() => {
  const pList = aiQ.data.value?.profiles ?? []
  return (pList as ProfileView[]).filter((p) => typeof p === 'object' && p !== null && 'id' in p)
})
const availableProfiles = computed(() => profiles.value.filter((p) => p.resolved?.ok))
const canAnalyze = computed(() => localRepos.value.length > 0 && availableProfiles.value.length > 0)

// AI 分析弹窗状态
const analysisSheetOpen = ref(false)
const selectedRepoId = ref('')
const selectedProfileId = ref('')
const analysisAckHighRisk = ref(false)
const analysisSubmitting = ref(false)
const analysisError = ref<string | null>(null)

const selectedProfile = computed(() =>
  availableProfiles.value.find((p) => String(p.id) === selectedProfileId.value),
)
const isHighRiskProfile = computed(() => {
  const p = selectedProfile.value
  if (!p) return false
  return String(p.cli) === 'agy'
})

watch(analysisSheetOpen, (isOpen) => {
  if (isOpen) {
    analysisError.value = null
    analysisAckHighRisk.value = false
    analysisSubmitting.value = false
    if (!selectedRepoId.value && localRepos.value.length > 0) {
      selectedRepoId.value = localRepos.value[0]!.id
    }
    if (!selectedProfileId.value && availableProfiles.value.length > 0) {
      selectedProfileId.value = String(availableProfiles.value[0]!.id)
    }
  }
})

async function startAnalysis() {
  if (analysisSubmitting.value || !selectedRepoId.value || !selectedProfileId.value) return
  if (isHighRiskProfile.value && !analysisAckHighRisk.value) {
    analysisError.value = formatAiError('high_risk_ack_required')
    return
  }

  analysisSubmitting.value = true
  analysisError.value = null
  try {
    const session = await createWorkItemAiAnalysis(api(), props.id, {
      request_id: crypto.randomUUID(),
      project_id: props.projectId,
      repo_id: selectedRepoId.value,
      profile_id: selectedProfileId.value,
      ack_high_risk: analysisAckHighRisk.value,
    })
    analysisSheetOpen.value = false
    void router.push({
      path: '/ai',
      query: session?.id ? { session: session.id } : undefined,
    })
  } catch (err: unknown) {
    const apiErr = err instanceof Error && 'code' in err ? err : toApiError(500, err)
    analysisError.value = formatAiError((apiErr as { code?: string }).code, '启动 AI 分析失败')
  } finally {
    analysisSubmitting.value = false
  }
}

// 复制链接：写入工单在 ADO 里的网址
async function handleCopyLink() {
  const url = d.value?.web_url
  if (!url) return
  copyToast.value = null
  try {
    await navigator.clipboard.writeText(url)
    copyToast.value = '链接已复制到剪贴板'
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copyToast.value = null
    }, 3000)
  } catch {
    copyToast.value = '复制链接失败'
  }
}

// 复制提示词状态
const copyToast = ref<string | null>(null)
const promptWarnings = ref<string[]>([])
let copyTimer: ReturnType<typeof setTimeout> | null = null

async function handleCopyPrompt() {
  copyToast.value = null
  promptWarnings.value = []
  try {
    const res = await fetchWorkItemAiPrompt(api(), props.id, props.projectId, 'claude')
    if (res.prompt) {
      await navigator.clipboard.writeText(res.prompt)
      copyToast.value = '提示词已复制到剪贴板'
      if (res.warnings && res.warnings.length > 0) {
        promptWarnings.value = res.warnings
      }
      if (copyTimer) clearTimeout(copyTimer)
      copyTimer = setTimeout(() => {
        copyToast.value = null
      }, 3000)
    }
  } catch {
    copyToast.value = '复制提示词失败'
  }
}
</script>

<template>
  <div class="detail" :aria-busy="q.isPending.value">
    <div v-if="q.isPending.value" class="wi-pane" role="status">
      <div class="skel" aria-hidden="true">
        <span class="bar" style="width: 30%"></span>
        <span class="bar tall" style="width: 70%"></span>
        <span class="bar" style="width: 45%"></span>
      </div>
      <p class="wi-muted">读取工单中…</p>
    </div>
    <ErrorNotice v-else-if="q.error.value" :error="q.error.value" retry @retry="q.refetch()" />
    <template v-else-if="d">
      <!-- 工具条：主操作 AI 分析；详情区 ≥560px 时其余操作直接摆出来，更窄时收进「⋯」（CSS 容器查询切换） -->
      <div class="d-tools">
        <Button
          variant="primary"
          data-testid="ai-analysis-btn"
          :disabled="!canAnalyze"
          :title="canAnalyze ? '' : '需配置本地仓库且有可用 AI CLI'"
          @click="analysisSheetOpen = true"
        >
          <Sparkles :size="13" aria-hidden="true" />
          AI 分析
        </Button>
        <Button
          variant="default"
          class="wide-only"
          data-testid="copy-prompt-btn"
          @click="handleCopyPrompt"
        >
          复制提示词
        </Button>
        <Button
          variant="default"
          class="wide-only"
          data-testid="open-web"
          @click="openExternal(d.web_url)"
        >
          <ExternalLink :size="13" aria-hidden="true" />
          在 ADO 打开
        </Button>
        <OverflowMenu label="更多操作">
          <button
            type="button"
            role="menuitem"
            class="menu-item narrow-only"
            data-testid="copy-prompt-menu-item"
            @click="handleCopyPrompt"
          >
            <Sparkles :size="14" aria-hidden="true" />
            复制提示词
          </button>
          <button
            type="button"
            role="menuitem"
            class="menu-item narrow-only"
            data-testid="open-web-menu-item"
            @click="openExternal(d.web_url)"
          >
            <ExternalLink :size="14" aria-hidden="true" />
            在 ADO 打开
          </button>
          <button
            type="button"
            role="menuitem"
            class="menu-item"
            data-testid="copy-link-menu-item"
            @click="handleCopyLink"
          >
            <Link :size="14" aria-hidden="true" />
            复制链接
          </button>
        </OverflowMenu>
      </div>

      <header class="d-head">
        <h2>{{ d.title }}</h2>
        <!-- 元信息：用图标分隔，不用“·”拼接 -->
        <div class="meta" data-testid="wi-meta">
          <span class="type" :data-type="d.type ?? ''"
            ><span class="kd" :style="{ background: kindColor(d.type) }" aria-hidden="true"></span
            >{{ d.type ?? '—' }}</span
          >
          <span class="num">#{{ d.id }}</span>
          <span v-if="d.parent_id" class="parent-wrap"
            ><CornerLeftUp :size="13" aria-hidden="true" />父项
            <button
              type="button"
              class="parent"
              data-testid="open-parent"
              @click="emit('select', d.parent_id!)"
            >
              #{{ d.parent_id }}
            </button></span
          >
          <span><User :size="13" aria-hidden="true" />{{ d.assigned_to ?? '未指派' }}</span>
          <span v-if="d.priority !== null && d.priority !== undefined"
            ><Flag :size="13" aria-hidden="true" />P{{ d.priority }}</span
          >
          <span class="num"
            ><CalendarPlus :size="13" aria-hidden="true" />创建
            {{ formatDate(d.created_date) }}</span
          >
          <span class="num"
            ><History :size="13" aria-hidden="true" />更新 {{ formatDate(d.changed_date) }}</span
          >
          <span v-if="d.rev !== null && d.rev !== undefined" class="num"
            ><GitCommitHorizontal :size="13" aria-hidden="true" />r{{ d.rev }}</span
          >
        </div>

        <!-- 复制提示词 Toast 提示与 Warnings -->
        <Banner
          v-if="copyToast"
          kind="info"
          role="status"
          class="mt-2"
          data-testid="copy-prompt-toast"
        >
          {{ copyToast }}
        </Banner>
        <Banner
          v-if="promptWarnings.length > 0"
          kind="warn"
          role="alert"
          class="mt-2"
          data-testid="prompt-warnings"
        >
          <span>提示词警示：{{ promptWarnings.join(', ') }}</span>
        </Banner>
      </header>
      <BoardLine :columns="boardColumns" :current="d.board_column" class="d-route" />
      <Banner
        v-if="media.expired.value > 0"
        kind="warn"
        role="status"
        class="expired"
        data-testid="media-expired"
      >
        部分图片已过期
        <template #actions>
          <Button data-testid="refresh-detail" @click="refreshDetail">刷新详情</Button>
        </template>
      </Banner>
      <SegmentedControl v-model="tab" :items="tabs" label="工单内容" class="d-tabs">
        <template #default="{ item }">
          <div v-if="item.value === 'desc'" class="wi-pane prose" data-testid="wi-body">
            <template v-for="[key, label, f] in sections" :key="key">
              <h3 v-if="sections.length > 1" class="wi-sec-h">{{ label }}</h3>
              <SafeHtml v-if="f?.html" :html="f.html" :media="media" />
              <p v-else class="wi-muted">内容过大，未显示</p>
            </template>
            <p v-if="!sections.length" class="wi-muted">暂无描述</p>
            <template v-if="d.links.length">
              <h3 class="wi-sec-h">关联</h3>
              <ul class="wi-list" data-testid="wi-links">
                <li v-for="(l, i) in d.links" :key="i">
                  <button v-if="l.url" type="button" class="link" @click="openExternal(l.url)">
                    {{ l.label }}
                  </button>
                  <span v-else>{{ l.label }}</span>
                </li>
              </ul>
            </template>
          </div>
          <CommentsPane
            v-else-if="item.value === 'comments'"
            :id="id"
            :project-id="projectId"
            @go-history="tab = 'history'"
          />
          <ChildrenPane
            v-else-if="item.value === 'children'"
            :id="id"
            :project-id="projectId"
            @select="emit('select', $event)"
          />
          <HistoryPane v-else-if="item.value === 'history'" :id="id" :project-id="projectId" />
          <AttachmentsPane v-else :attachments="d.attachments" />
        </template>
      </SegmentedControl>
    </template>

    <!-- 工单 AI 分析 Sheet -->
    <Sheet
      v-model:open="analysisSheetOpen"
      :title="`工单 AI 分析 (#${props.id})`"
      description="在指定的本地代码仓库中通过 AI CLI 对该工单进行代码分析。"
    >
      <form class="ai-analysis-form" data-testid="ai-analysis-form" @submit.prevent="startAnalysis">
        <Banner v-if="analysisError" kind="error" class="mb-3" data-testid="analysis-error-banner">
          {{ analysisError }}
        </Banner>

        <div class="field-row mb-3">
          <label for="analysis-repo-select" class="field-label">工作目录（本地仓库）</label>
          <select
            id="analysis-repo-select"
            v-model="selectedRepoId"
            class="b-select"
            data-testid="analysis-repo-select"
            :disabled="analysisSubmitting"
          >
            <option v-for="r in localRepos" :key="r.id" :value="r.id">
              {{ r.name }}
            </option>
          </select>
        </div>

        <div class="field-row mb-3">
          <label for="analysis-profile-select" class="field-label">AI CLI 配置</label>
          <select
            id="analysis-profile-select"
            v-model="selectedProfileId"
            class="b-select"
            data-testid="analysis-profile-select"
            :disabled="analysisSubmitting"
          >
            <option v-for="p in availableProfiles" :key="String(p.id)" :value="String(p.id)">
              {{ String(p.name) }} ({{ String(p.cli) }})
            </option>
          </select>
        </div>

        <!-- 高权限二次确认 -->
        <div
          v-if="isHighRiskProfile"
          class="high-risk-box mb-3"
          data-testid="analysis-high-risk-box"
        >
          <Banner kind="warn" class="mb-2">
            所选 AI CLI 包含高风险或全自动权限，需二次确认。
          </Banner>
          <label class="flex items-center gap-2 text-xs cursor-pointer font-medium">
            <input
              v-model="analysisAckHighRisk"
              type="checkbox"
              data-testid="analysis-high-risk-ack"
              :disabled="analysisSubmitting"
            />
            <span>我已知晓并确认以高权限执行此工单分析</span>
          </label>
        </div>

        <div class="flex justify-end gap-2 mt-4">
          <Button
            type="button"
            variant="default"
            :disabled="analysisSubmitting"
            @click="analysisSheetOpen = false"
          >
            取消
          </Button>
          <Button
            type="submit"
            variant="primary"
            data-testid="confirm-analysis-btn"
            :disabled="analysisSubmitting || !selectedRepoId || !selectedProfileId"
          >
            {{ analysisSubmitting ? '正在启动…' : '开始分析' }}
          </Button>
        </div>
      </form>
    </Sheet>
  </div>
</template>

<style scoped>
.detail {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  /* 详情区自己的宽度（不是窗口宽度）决定工具条怎么收：<560px 时次要操作进「⋯」 */
  container: wi-detail / inline-size;
}
.d-tools {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 49px;
  padding: 10px 20px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
@container wi-detail (max-width: 559px) {
  .wide-only {
    display: none;
  }
}
@container wi-detail (min-width: 560px) {
  .narrow-only {
    display: none;
  }
}
.d-head {
  padding: 18px 20px 0;
  max-width: 860px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
h2 {
  margin: 0;
  font-size: 20px;
  line-height: 1.3;
  font-weight: 650;
  letter-spacing: -0.2px;
  overflow-wrap: anywhere;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 14px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.meta > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.meta svg {
  flex: none;
  color: var(--faint);
}
.num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.type {
  color: var(--accent-ink);
  font-weight: 600;
}
.kd {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.d-route {
  margin: 0 20px;
}
.d-tabs {
  padding: 14px 20px 0;
}
.d-tabs :deep(.tab-panel) {
  margin: 0 -20px;
}
.expired {
  margin: 12px 20px 0;
  max-width: 756px;
}
/* 描述正文：14px、行高 1.7；文字块行宽不超过 68ch（表格、图片、代码块不受限） */
.prose {
  font-size: var(--text-long);
  line-height: 1.7;
}
.prose :deep(.safe-html > :not(table):not(img):not(pre)) {
  max-width: 68ch;
}
.parent,
.link {
  min-height: var(--target-min);
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
  color: var(--link);
  text-align: left;
}
.parent {
  min-width: var(--target-min);
}
.skel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bar {
  display: block;
  height: 10px;
  border-radius: 4px;
  background: var(--skeleton);
}
.bar.tall {
  height: 22px;
}
.field-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}
.b-select {
  width: 100%;
  padding: 6px 8px;
  border-radius: var(--r-ctl, 6px);
  border: 1px solid var(--line);
  background: var(--card-bg, #fff);
  color: var(--ink);
  font: inherit;
  font-size: 13px;
}
.high-risk-box {
  padding: 8px 10px;
  border-radius: 6px;
  background: #fffbeb;
  border: 1px solid #fde68a;
}
</style>
