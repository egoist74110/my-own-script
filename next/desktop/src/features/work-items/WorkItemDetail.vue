<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
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
import ChildrenPane from './ChildrenPane.vue'
import CommentsPane from './CommentsPane.vue'
import ErrorNotice from './ErrorNotice.vue'
import HistoryPane from './HistoryPane.vue'
import { badShape, unwrap, type HtmlField, type WorkItemDetail } from './api'
import { formatDate, kindColor } from './format'
import { QUERY_DEFAULTS, WI_KEY, projectKey, useWiApi } from './queries'
import './panes.css'

/**
 * 工单详情。本组件由页面以 `${projectId}:${id}` 作 key：切换工单/项目或离开页面即卸载，
 * 页面级媒体缓存随之 clear()（中止请求 + revokeObjectURL 全部 blob）。
 */
const props = defineProps<{ projectId: string; id: number }>()
const emit = defineEmits<{ select: [id: number]; loaded: [detail: WorkItemDetail | null] }>()
const { api, maybeApi, online, qc } = useWiApi()

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

const metaLine = computed(() => {
  const x = d.value
  if (!x) return ''
  const rev = x.rev === null || x.rev === undefined ? null : `r${x.rev}`
  return [
    x.assigned_to ?? '未指派',
    `创建 ${formatDate(x.created_date)}`,
    `更新 ${formatDate(x.changed_date)}`,
    rev,
  ]
    .filter(Boolean)
    .join(' · ')
})

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
      <header class="d-head">
        <div class="d-line">
          <span class="type" :data-type="d.type ?? ''"
            ><span class="kd" :style="{ background: kindColor(d.type) }" aria-hidden="true"></span
            >{{ d.type ?? '—' }}</span
          >
          <span class="mono idn">#{{ d.id }}</span>
          <template v-if="d.parent_id">
            <span aria-hidden="true">·</span>
            <span class="parent-wrap"
              >父项
              <button
                type="button"
                class="parent"
                data-testid="open-parent"
                @click="emit('select', d.parent_id!)"
              >
                #{{ d.parent_id }}
              </button></span
            >
          </template>

          <span class="grow"></span>
          <div class="wi-ai-btn-group">
            <Button
              size="sm"
              variant="default"
              data-testid="copy-prompt-btn"
              @click="handleCopyPrompt"
            >
              复制提示词
            </Button>
            <Button
              size="sm"
              variant="primary"
              data-testid="ai-analysis-btn"
              :disabled="!canAnalyze"
              :title="canAnalyze ? '' : '需配置本地仓库且有可用 AI CLI'"
              @click="analysisSheetOpen = true"
            >
              AI 分析
            </Button>
          </div>
        </div>
        <h2>{{ d.title }}</h2>
        <div class="meta">{{ metaLine }}</div>

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
          <div v-if="item.value === 'desc'" class="wi-pane" data-testid="wi-body">
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
}
.d-head {
  padding: 22px 32px 0;
  max-width: 820px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.d-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.type {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--accent-ink);
  font-weight: 600;
}
.kd {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
h2 {
  margin: 2px 0 0;
  font-size: var(--text-title);
  line-height: 1.3;
  font-weight: 700;
  letter-spacing: -0.2px;
  overflow-wrap: anywhere;
}
.meta {
  font-size: 12.5px;
  color: var(--mute);
}
.d-tabs {
  padding: 14px 32px 0;
}
.d-tabs :deep(.tab-panel) {
  margin: 0 -32px;
}
.expired {
  margin: 12px 32px 0;
  max-width: 756px;
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
.grow {
  flex: 1;
}
.wi-ai-btn-group {
  display: flex;
  gap: 6px;
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
