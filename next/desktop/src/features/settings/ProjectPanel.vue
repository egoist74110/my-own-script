<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import Button from '@/components/Button.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import type { Project } from './api'
import { useEditSession } from './editSession'
import { settingsContextKey } from './useSettings'

/** 检查器：project 详情 / 新建（新建时可从远端获取 project 名）。 */
const props = defineProps<{ project: Project | null; startToken?: number }>()
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

/** 编辑会话 + 基线（见 editSession.ts）：每次开始编辑都从当前服务器数据初始化草稿。 */
const edit = useEditSession(ctx, {
  drafts: { library_id: libraryId, collection, project: projectName },
  // 直接查最新的服务器数据（条目已被删除时为 null）
  server: () => {
    const p = ctx.ado.data.value?.projects.find((x) => x.id === props.project?.id)
    return p ? { library_id: p.library_id, collection: p.collection, project: p.project } : null
  },
  defaults: () => ({ library_id: libraries.value[0]?.id ?? '' }),
})

/** setActive 用缓存 revision：若只有本次写入推进了 revision，则基线随之前进。 */
async function activate() {
  const s = edit.current()
  const r = await ctx.setActive(props.project!.library_id, props.project!.id)
  edit.advance(s, r)
}

watch(
  () => `${props.project?.id ?? ''}|${props.startToken ?? 0}`,
  () => {
    edit.begin()
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
  const s = edit.current()
  if (isNew.value) {
    const r = await ctx.createProject(
      libraryId.value,
      collection.value.trim(),
      projectName.value.trim(),
    )
    if (r.ok && r.data.id && s === edit.current()) emit('select', r.data.id)
    return
  }
  const p = props.project!
  const body = edit.changed()
  if (!Object.keys(body).length) return
  const r = await ctx.patchProject(p.id, body, {
    ...edit.revisionOpt(),
    onConflict: () => edit.mergeConflict(s),
  })
  if (r.ok) edit.saved(s, body, r.data.revision)
}

async function fetchRemote() {
  localError.value = null
  if (!libraryId.value || !collection.value.trim()) {
    localError.value = '请先选择 library 并填写 collection'
    return
  }
  const s = edit.current()
  const r = await ctx.remoteProjects(libraryId.value, collection.value.trim())
  if (r.ok && s === edit.current()) remote.value = r.data.map((x) => x.name)
}

async function remove() {
  if (!props.project) return
  const s = edit.current()
  const r = await ctx.deleteProject(props.project.id)
  if (s !== edit.current()) return
  confirmDelete.value = false
  if (r.ok) emit('deleted')
}
</script>

<template>
  <div class="st-inspector" :data-testid="isNew ? 'project-new' : 'project-detail'">
    <div class="st-head">
      <Tag>PROJ</Tag>
      <h2>{{ isNew ? '新建 project' : project!.project }}</h2>
      <Tag v-if="isActive" tone="ok">当前</Tag>
    </div>

    <div class="st-fld">
      <label class="lbl" for="proj-lib">Library</label>
      <select id="proj-lib" v-model="libraryId" class="st-select">
        <option v-for="l in libraries" :key="l.id" :value="l.id">{{ l.name }}</option>
      </select>
    </div>
    <div class="st-fld">
      <span class="lbl" aria-hidden="true">Collection</span>
      <TextField v-model="collection" label="collection" placeholder="DefaultCollection" />
    </div>
    <div class="st-fld">
      <span class="lbl" aria-hidden="true">Project</span>
      <TextField v-model="projectName" label="project 名称" placeholder="项目名" />
    </div>

    <template v-if="isNew">
      <div class="st-actions">
        <Button data-testid="remote-fetch" :disabled="disabled" @click="fetchRemote">
          获取远端项目
        </Button>
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
      <Button variant="primary" data-testid="project-save" :disabled="disabled" @click="save">
        {{ isNew ? '新建' : '保存修改' }}
      </Button>
      <Button
        v-if="!isNew"
        data-testid="project-activate"
        :disabled="disabled || isActive"
        @click="activate"
      >
        设为当前
      </Button>
    </div>

    <template v-if="!isNew">
      <hr class="st-sep" />
      <div v-if="!confirmDelete" class="st-actions">
        <Button
          class="st-btn-danger"
          data-testid="project-delete"
          :disabled="disabled"
          @click="confirmDelete = true"
        >
          删除 project
        </Button>
      </div>
      <div v-else class="st-box" data-tone="warn" role="alertdialog" aria-label="确认删除 project">
        <strong>确认删除「{{ project!.project }}」？</strong>
        <div>被任务引用时无法删除。</div>
        <div class="st-actions">
          <Button
            variant="destructive"
            data-testid="project-delete-confirm"
            :disabled="disabled"
            @click="remove"
          >
            确认删除
          </Button>
          <Button @click="confirmDelete = false">取消</Button>
        </div>
      </div>
    </template>
  </div>
</template>
