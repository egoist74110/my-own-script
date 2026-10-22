<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import BlockTag from '@/components/BlockTag.vue'
import TextInput from '@/components/TextInput.vue'
import type { LocalRepoView } from './api'
import { useEditSession } from './editSession'
import { settingsContextKey } from './useSettings'

/** 检查器：本地仓库详情 / 新建。路径只是文本输入；校验错误文案固定，不回显输入。 */
const props = defineProps<{ repo: LocalRepoView | null; startToken?: number }>()
const emit = defineEmits<{ select: [id: string]; deleted: [] }>()
const ctx = inject(settingsContextKey)!

const name = ref('')
const path = ref('')
const confirmDelete = ref(false)
const localError = ref<string | null>(null)

const MAX_PATH = 1024
const isNew = computed(() => props.repo === null)
const disabled = computed(() => ctx.busy.value || !ctx.writable.value)

const edit = useEditSession(ctx, {
  drafts: { name, path },
  // 直接查最新的服务器数据（条目已被删除时为 null）
  server: () => {
    const r = ctx.ado.data.value?.local_repos.find((x) => x.id === props.repo?.id)
    return r ? { name: r.name, path: r.path } : null
  },
})

watch(
  () => `${props.repo?.id ?? ''}|${props.startToken ?? 0}`,
  () => {
    edit.begin()
    confirmDelete.value = false
    localError.value = null
  },
  { immediate: true, flush: 'sync' },
)

/** 只校验要提交的字段：存量不合规的另一字段不阻止只改这一项（后端 PATCH 也只校验提交的字段）。 */
function validateRepo(n: string | undefined, p: string | undefined): string | null {
  if (n !== undefined && (n.length < 1 || n.length > 100)) return '名称需为 1–100 个字符'
  if (p === undefined) return null
  if (p.length < 1 || p.length > MAX_PATH) return `路径需为 1–${MAX_PATH} 个字符`
  if (!/^(\/|[A-Za-z]:[\\/]|\\\\)/.test(p)) return '路径必须是绝对路径'
  if (Array.from(p).some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127))
    return '路径不能含控制字符'
  if (p.split(/[\\/]/).includes('..')) return '路径不能含 .. 段'
  return null
}

async function save() {
  const s = edit.current()
  if (isNew.value) {
    localError.value = validateRepo(name.value.trim(), path.value.trim())
    if (localError.value) return
    const r = await ctx.createLocalRepo(name.value.trim(), path.value.trim())
    if (r.ok && r.data.id && s === edit.current()) emit('select', r.data.id)
    return
  }
  const body = edit.changed()
  localError.value = validateRepo(body.name, body.path)
  if (localError.value) return
  if (!Object.keys(body).length) return
  const r = await ctx.patchLocalRepo(props.repo!.id, body, {
    ...edit.revisionOpt(),
    onConflict: () => edit.mergeConflict(s),
  })
  if (r.ok) edit.saved(s, body, r.data.revision)
}

async function remove() {
  if (!props.repo) return
  const s = edit.current()
  const r = await ctx.deleteLocalRepo(props.repo.id)
  if (s !== edit.current()) return
  confirmDelete.value = false
  if (r.ok) emit('deleted')
}
</script>

<template>
  <div class="st-inspector" :data-testid="isNew ? 'repo-new' : 'repo-detail'">
    <div class="st-head">
      <BlockTag>REPO</BlockTag>
      <h2>{{ isNew ? '新建本地仓库' : repo!.name }}</h2>
    </div>

    <div class="st-fld">
      <span class="lbl" aria-hidden="true">名称</span>
      <TextInput v-model="name" label="仓库名称" placeholder="例如：主仓库" />
    </div>
    <div class="st-fld">
      <span class="lbl" aria-hidden="true">路径</span>
      <TextInput v-model="path" label="仓库路径" placeholder="/Users/me/code/repo" />
      <p class="st-note">只保存路径文本，不会读取目录内容。</p>
    </div>

    <ul
      v-if="repo && repo.warnings?.length"
      class="st-list st-warn"
      data-testid="repo-warnings"
      aria-label="存量条目警告"
    >
      <li v-for="w in repo.warnings" :key="w">{{ w }}</li>
    </ul>

    <p v-if="localError" class="st-warn" role="alert" data-testid="repo-local-error">
      {{ localError }}
    </p>

    <div class="st-actions">
      <AppButton data-testid="repo-save" :disabled="disabled" @click="save">
        {{ isNew ? '新建' : '保存修改' }}
      </AppButton>
    </div>

    <template v-if="!isNew">
      <hr class="st-sep" />
      <div v-if="!confirmDelete" class="st-actions">
        <AppButton
          variant="ghost"
          class="st-btn-danger"
          data-testid="repo-delete"
          :disabled="disabled"
          @click="confirmDelete = true"
        >
          删除仓库
        </AppButton>
      </div>
      <div v-else class="st-box" data-tone="warn" role="alertdialog" aria-label="确认删除本地仓库">
        <strong>确认删除「{{ repo!.name }}」？</strong>
        <div>只删除这条记录，不会动磁盘上的目录。</div>
        <div class="st-actions">
          <AppButton
            variant="primary"
            data-testid="repo-delete-confirm"
            :disabled="disabled"
            @click="remove"
          >
            确认删除
          </AppButton>
          <AppButton variant="ghost" data-testid="repo-delete-cancel" @click="confirmDelete = false"
            >取消</AppButton
          >
        </div>
      </div>
    </template>
  </div>
</template>
