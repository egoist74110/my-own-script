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

watch(
  () => props.project?.id ?? null,
  () => {
    libraryId.value = props.project?.library_id ?? libraries.value[0]?.id ?? ''
    collection.value = props.project?.collection ?? ''
    projectName.value = props.project?.project ?? ''
    remote.value = null
    confirmDelete.value = false
    localError.value = null
  },
  { immediate: true },
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
  if (isNew.value) {
    const r = await ctx.createProject(
      libraryId.value,
      collection.value.trim(),
      projectName.value.trim(),
    )
    if (r.ok && r.data.id) emit('select', r.data.id)
    return
  }
  const p = props.project!
  const body: { library_id?: string; collection?: string; project?: string } = {}
  if (libraryId.value !== p.library_id) body.library_id = libraryId.value
  if (collection.value.trim() !== p.collection) body.collection = collection.value.trim()
  if (projectName.value.trim() !== p.project) body.project = projectName.value.trim()
  if (Object.keys(body).length) await ctx.patchProject(p.id, body)
}

async function fetchRemote() {
  localError.value = null
  if (!libraryId.value || !collection.value.trim()) {
    localError.value = '请先选择 library 并填写 collection'
    return
  }
  const r = await ctx.remoteProjects(libraryId.value, collection.value.trim())
  if (r.ok) remote.value = r.data.map((x) => x.name)
}

async function remove() {
  if (!props.project) return
  const r = await ctx.deleteProject(props.project.id)
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
        @click="ctx.setActive(project!.library_id, project!.id)"
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
