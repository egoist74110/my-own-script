<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import TextField from '@/components/TextField.vue'
import { canPickFolder, pickFolder } from '@/components/pick-folder'
import { discoverErrorText, useDiscoverRepo } from './discover'
import { QUERY_DEFAULTS, useTasksApi } from './queries'
import { unwrap } from './api'

/**
 * 本地仓库路径：选择文件夹（Tauri 里是系统选择器，其余环境隐藏按钮）、从设置里已登记的本地仓库选、或直接输入。
 * 任何方式选了路径都先调 discover/repo 校验：文件夹对应的仓库与本配置不一致就提示并不采用。
 * 路径为空时，用名称与本配置仓库同名的已登记本地仓库做自动匹配，校验一致后给“填入”按钮（不自动写入）。
 */
const props = defineProps<{
  /** 本配置关联的 ADO 仓库（空表示还没关联，不校验一致性）。 */
  repoId: string
  repoName: string
}>()
const path = defineModel<string>({ default: '' })

const { api, online } = useTasksApi()
const adoQ = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: ['settings', 'ado'],
  enabled: online,
  queryFn: ({ signal }) => unwrap(api().GET('/api/ado', { signal })),
})
const repos = computed(() => (adoQ.data.value?.local_repos ?? []).filter((r) => r.exists))

const draft = ref(path.value)
watch(path, (v) => (draft.value = v))

const checking = useDiscoverRepo()
const rejected = ref<string | null>(null)
const warned = ref<string | null>(null)

/** 校验并采用一个候选路径；不一致或出错则不采用。 */
async function adopt(candidate: string) {
  const p = candidate.trim()
  rejected.value = null
  warned.value = null
  if (!p) {
    path.value = ''
    return
  }
  try {
    const res = await checking.mutateAsync(p)
    if (props.repoId && res.repo_id && res.repo_id !== props.repoId) {
      rejected.value = `这个文件夹是 ${res.repo_name || res.repo_id} 仓库，不是本配置的 ${props.repoName || props.repoId}，没有采用。`
      draft.value = path.value
      return
    }
    if (props.repoId && !res.repo_id)
      warned.value = '没法确认这个文件夹对应的 ADO 仓库（未匹配到项目），已采用，请自行确认选对了。'
    path.value = res.local_repo_path || p
  } catch (e) {
    rejected.value = `${discoverErrorText(e)} 没有采用这个路径。`
    draft.value = path.value
  }
}

async function chooseFolder() {
  const p = await pickFolder()
  if (p) {
    draft.value = p
    await adopt(p)
  }
}
function onRegistered(e: Event) {
  const v = (e.target as HTMLSelectElement).value
  ;(e.target as HTMLSelectElement).value = ''
  if (v) {
    draft.value = v
    void adopt(v)
  }
}

// 自动匹配：路径为空、本配置有关联仓库、已登记里有同名本地仓库 → 校验 repo_id 一致后给“填入”按钮
const candidate = computed(() => {
  if (path.value.trim() || !props.repoId || !props.repoName.trim()) return null
  const n = props.repoName.trim().toLowerCase()
  return repos.value.find((r) => r.name.trim().toLowerCase() === n) ?? null
})
const matchQ = useQuery({
  ...QUERY_DEFAULTS,
  queryKey: computed(() => ['release-discover', 'match', candidate.value?.path ?? '']),
  enabled: computed(() => online.value && Boolean(candidate.value)),
  queryFn: ({ signal }) =>
    unwrap(
      api().POST('/api/release-configs/discover/repo', {
        signal,
        body: { local_repo_path: candidate.value!.path },
      }),
    ),
})
const suggestion = computed(() => {
  const r = matchQ.data.value
  if (!candidate.value || !r || r.repo_id !== props.repoId) return null
  return r.local_repo_path || candidate.value.path
})

const input = ref<HTMLElement | null>(null)
function focus() {
  const el = input.value?.querySelector('input')
  input.value?.scrollIntoView?.({ block: 'center' })
  el?.focus()
}
defineExpose({ focus })
</script>

<template>
  <div ref="input" class="lpf" data-testid="local-path-field">
    <div class="lpf-row">
      <TextField
        v-model="draft"
        label="本地仓库路径"
        placeholder="未设置"
        data-testid="local-path-input"
        @change="adopt(draft)"
      />
      <Button
        v-if="canPickFolder()"
        type="button"
        data-testid="pick-folder-btn"
        :disabled="checking.isPending.value"
        @click="chooseFolder"
      >
        选择文件夹…
      </Button>
    </div>
    <select
      v-if="repos.length"
      class="lpf-sel"
      aria-label="从已登记的本地仓库选择"
      data-testid="registered-repo-select"
      value=""
      @change="onRegistered"
    >
      <option value="">从已登记的本地仓库选择…</option>
      <option v-for="r in repos" :key="r.id" :value="r.path">{{ r.name }}（{{ r.path }}）</option>
    </select>
    <p v-if="checking.isPending.value" class="lpf-hint" role="status">正在校验这个文件夹…</p>
    <Banner v-if="rejected" kind="warn" data-testid="local-path-rejected">{{ rejected }}</Banner>
    <p v-if="warned" class="lpf-hint" data-testid="local-path-warned">{{ warned }}</p>
    <Banner v-if="suggestion" kind="info" data-testid="local-path-suggestion">
      检测到本地仓库 {{ suggestion }}，与本配置的仓库一致。
      <template #actions>
        <Button data-testid="path-autofill-btn" @click="adopt(suggestion)">填入</Button>
      </template>
    </Banner>
  </div>
</template>

<style scoped>
.lpf {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.lpf-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.lpf-row > :first-child {
  flex: 1;
  min-width: 0;
}
.lpf-sel {
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--ink);
  padding: 0 8px;
  font: inherit;
}
.lpf-hint {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
</style>
