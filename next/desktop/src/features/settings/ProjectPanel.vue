<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import BlockTag from '@/components/BlockTag.vue'
import TextInput from '@/components/TextInput.vue'
import type { Project } from './api'
import { settingsContextKey } from './useSettings'

/** 检查器：project 详情 / 新建（新建时可从远端获取 project 名）。 */
const props = defineProps<{ project: Project | null }>()
const emit = defineEmits<{ select: [id: string]; deleted: [] }>()
const ctx = inject(settingsContextKey)!

const libraryId = ref('')
const collection = ref('')
const projectName = ref('')
const remote = ref<string[] | null>(null)
const confirmDelete = ref(false)
const localError = ref<string | null>(null)

const isNew = computed(() => props.project === null)
const libraries = computed(() => ctx.ado.data.value?.libraries ?? [])
const disabled = computed(() => ctx.busy.value || !ctx.writable.value)
const isActive = computed(
  () =>
    !!props.project &&
    ctx.ado.data.value?.active_project_id === props.project.id &&
    ctx.ado.data.value?.active_library_id === props.project.library_id,
)

/** 编辑会话：每次开始编辑（选中条目变化或新建）递增；写响应只在会话未变时作用于组件状态（CR-S1B-005）。 */
let session = 0

/** 编辑基线：开始编辑（选中/新建）时的字段值与当时的 revision；外部变更不改它。 */
type Fields = { library_id: string; collection: string; project: string }
let baseline: Fields & { revision: number | null } = {
  library_id: '',
  collection: '',
  project: '',
  revision: null,
}
function captureBaseline() {
  baseline = {
    library_id: props.project?.library_id ?? '',
    collection: props.project?.collection ?? '',
    project: props.project?.project ?? '',
    revision: ctx.ado.data.value?.revision ?? null,
  }
}

/** revision_conflict 后：用户改过的字段保留，未改字段换成服务器新值，基线整体更新。 */
function mergeConflict(s: number): boolean {
  if (s !== session) return false
  const fresh = ctx.ado.data.value
  const p = fresh?.projects.find((x) => x.id === props.project?.id)
  if (!fresh || !p) return false
  if (libraryId.value === baseline.library_id) libraryId.value = p.library_id
  if (collection.value.trim() === baseline.collection) collection.value = p.collection
  if (projectName.value.trim() === baseline.project) projectName.value = p.project
  baseline = {
    library_id: p.library_id,
    collection: p.collection,
    project: p.project,
    revision: fresh.revision,
  }
  return true
}

/** setActive 用缓存 revision：若只有本次写入推进了 revision，则基线随之前进。 */
async function activate() {
  const s = session
  const r = await ctx.setActive(props.project!.library_id, props.project!.id)
  const d = r.ok ? (r.data as { revision?: number }) : undefined
  if (
    s === session &&
    r.ok &&
    r.rev !== null &&
    r.rev === baseline.revision &&
    typeof d?.revision === 'number'
  )
    baseline.revision = d.revision
}

watch(
  () => props.project?.id ?? null,
  () => {
    session++
    captureBaseline()
    libraryId.value = props.project?.library_id ?? libraries.value[0]?.id ?? ''
    collection.value = props.project?.collection ?? ''
    projectName.value = props.project?.project ?? ''
    remote.value = null
    confirmDelete.value = false
    localError.value = null
  },
  { immediate: true, flush: 'sync' },
)

function validate(): string | null {
  if (!libraryId.value) return '请选择 library'
  for (const v of [collection.value.trim(), projectName.value.trim()]) {
    if (v.length < 1 || v.length > 256) return 'collection / project 需为 1–256 个字符'
    if (
      /[/\\]/.test(v) ||
      Array.from(v).some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)
    )
      return 'collection / project 不能含 / \\ 或控制字符'
  }
  return null
}

async function save() {
  localError.value = validate()
  if (localError.value) return
  const s = session
  if (isNew.value) {
    const r = await ctx.createProject(
      libraryId.value,
      collection.value.trim(),
      projectName.value.trim(),
    )
    if (r.ok && r.data.id && s === session) emit('select', r.data.id)
    return
  }
  const p = props.project!
  const body: { library_id?: string; collection?: string; project?: string } = {}
  if (libraryId.value !== baseline.library_id) body.library_id = libraryId.value
  if (collection.value.trim() !== baseline.collection) body.collection = collection.value.trim()
  if (projectName.value.trim() !== baseline.project) body.project = projectName.value.trim()
  if (!Object.keys(body).length) return
  const r = await ctx.patchProject(p.id, body, {
    ...(baseline.revision !== null ? { revision: baseline.revision } : {}),
    onConflict: () => mergeConflict(s),
  })
  if (r.ok && s === session) baseline = { ...baseline, ...body, revision: r.data.revision }
}

async function fetchRemote() {
  localError.value = null
  if (!libraryId.value || !collection.value.trim()) {
    localError.value = '请先选择 library 并填写 collection'
    return
  }
  const s = session
  const r = await ctx.remoteProjects(libraryId.value, collection.value.trim())
  if (r.ok && s === session) remote.value = r.data.map((x) => x.name)
}

async function remove() {
  if (!props.project) return
  const s = session
  const r = await ctx.deleteProject(props.project.id)
  if (s !== session) return
  confirmDelete.value = false
  if (r.ok) emit('deleted')
}
</script>

<template>
  <div class="st-inspector" :data-testid="isNew ? 'project-new' : 'project-detail'">
    <div class="st-head">
      <BlockTag>PROJ</BlockTag>
      <h2>{{ isNew ? '新建 project' : project!.project }}</h2>
      <BlockTag v-if="isActive" tone="acc">当前</BlockTag>
    </div>

    <div class="st-fld">
      <label class="lbl" for="proj-lib">Library</label>
      <select id="proj-lib" v-model="libraryId" class="st-select">
        <option v-for="l in libraries" :key="l.id" :value="l.id">{{ l.name }}</option>
      </select>
    </div>
    <div class="st-fld">
      <span class="lbl" aria-hidden="true">Collection</span>
      <TextInput v-model="collection" label="collection" placeholder="DefaultCollection" />
    </div>
    <div class="st-fld">
      <span class="lbl" aria-hidden="true">Project</span>
      <TextInput v-model="projectName" label="project 名称" placeholder="项目名" />
    </div>

    <template v-if="isNew">
      <div class="st-actions">
        <AppButton
          variant="ghost"
          data-testid="remote-fetch"
          :disabled="disabled"
          @click="fetchRemote"
        >
          获取远端项目
        </AppButton>
      </div>
      <ul v-if="remote" class="st-list" data-testid="remote-list" aria-label="远端项目">
        <li v-for="n in remote" :key="n">
          <button type="button" class="st-mono" @click="projectName = n">{{ n }}</button>
        </li>
        <li v-if="!remote.length" class="st-note">远端没有项目</li>
      </ul>
    </template>

    <p v-if="localError" class="st-warn" role="alert" data-testid="project-local-error">
      {{ localError }}
    </p>

    <div class="st-actions">
      <AppButton data-testid="project-save" :disabled="disabled" @click="save">
        {{ isNew ? '新建' : '保存修改' }}
      </AppButton>
      <AppButton
        v-if="!isNew"
        variant="ghost"
        data-testid="project-activate"
        :disabled="disabled || isActive"
        @click="activate"
      >
        设为当前
      </AppButton>
    </div>

    <template v-if="!isNew">
      <hr class="st-sep" />
      <div v-if="!confirmDelete" class="st-actions">
        <AppButton
          variant="ghost"
          class="st-btn-danger"
          data-testid="project-delete"
          :disabled="disabled"
          @click="confirmDelete = true"
        >
          删除 project
        </AppButton>
      </div>
      <div v-else class="st-box" data-tone="warn" role="alertdialog" aria-label="确认删除 project">
        <strong>确认删除「{{ project!.project }}」？</strong>
        <div>被任务引用时无法删除。</div>
        <div class="st-actions">
          <AppButton
            variant="primary"
            data-testid="project-delete-confirm"
            :disabled="disabled"
            @click="remove"
          >
            确认删除
          </AppButton>
          <AppButton variant="ghost" @click="confirmDelete = false">取消</AppButton>
        </div>
      </div>
    </template>
  </div>
</template>
