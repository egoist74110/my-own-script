<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import BlockTag from '@/components/BlockTag.vue'
import TextInput from '@/components/TextInput.vue'
import {
  CATEGORY_TEXT,
  originOf,
  type ApiError,
  type ConnectionResult,
  type LibraryView,
} from './api'
import { settingsContextKey } from './useSettings'

/**
 * 检查器：library 详情 / 新建。PAT 只存在于本组件的 `pat` 局部状态：
 * 每次携带 PAT 的请求结束后（无论成败）立即清空；输入框从不预填。
 */
const props = defineProps<{ library: LibraryView | null }>()
const emit = defineEmits<{ select: [id: string]; deleted: [] }>()
const ctx = inject(settingsContextKey)!

const name = ref('')
const baseUrl = ref('')
const pat = ref('')
const collection = ref('')
const result = ref<ConnectionResult | null>(null)
const confirmDelete = ref(false)
const originChange = ref<string | null>(null)
const localError = ref<string | null>(null)

const isNew = computed(() => props.library === null)
const projects = computed(() =>
  (ctx.ado.data.value?.projects ?? []).filter((p) => p.library_id === props.library?.id),
)
const disabled = computed(() => ctx.busy.value || !ctx.writable.value)

watch(
  () => props.library?.id ?? null,
  () => {
    name.value = props.library?.name ?? ''
    baseUrl.value = props.library?.base_url ?? ''
    pat.value = ''
    collection.value = projects.value[0]?.collection ?? ''
    result.value = null
    confirmDelete.value = false
    originChange.value = null
    localError.value = null
  },
  { immediate: true },
)

function validate(): string | null {
  const n = name.value.trim()
  if (n.length < 1 || n.length > 100) return '名称需为 1–100 个字符'
  const o = originOf(baseUrl.value.trim())
  if (!o || !/^https?:\/\//i.test(baseUrl.value.trim())) return '地址必须是 http/https URL'
  return null
}
const isHttp = computed(() => baseUrl.value.trim().toLowerCase().startsWith('http:'))

async function create() {
  localError.value = validate()
  if (localError.value) return
  const value = pat.value
  try {
    const r = await ctx.createLibrary(name.value.trim(), baseUrl.value.trim(), value || null)
    if (r.ok && r.data.id) emit('select', r.data.id)
  } finally {
    pat.value = ''
  }
}

function changed() {
  const body: { name?: string; base_url?: string } = {}
  if (name.value.trim() !== props.library!.name) body.name = name.value.trim()
  if (baseUrl.value.trim() !== props.library!.base_url) body.base_url = baseUrl.value.trim()
  return body
}

async function save() {
  localError.value = validate()
  if (localError.value || !props.library) return
  const body = changed()
  if (!Object.keys(body).length) return
  const r = await ctx.patchLibrary(props.library.id, body, (e: ApiError) => {
    if (e.code !== 'pat_origin_change') return false
    originChange.value = originOf(baseUrl.value.trim())
    return true
  })
  if (r.ok) originChange.value = null
}

async function resolveOrigin(mode: 'keep' | 'replace') {
  if (!props.library) return
  const value = pat.value
  if (mode === 'replace' && !value) {
    localError.value = '请输入新的 PAT'
    return
  }
  localError.value = null
  try {
    const r = await ctx.patchLibrary(props.library.id, {
      ...changed(),
      ...(mode === 'keep' ? { keep_pat: true } : { pat: value }),
    })
    if (r.ok) originChange.value = null
  } finally {
    pat.value = ''
  }
}

async function savePat() {
  if (!props.library || !pat.value) return
  const value = pat.value
  try {
    await ctx.putPat(props.library.id, value)
  } finally {
    pat.value = ''
  }
}

async function test() {
  if (!props.library) return
  const value = pat.value
  result.value = null
  try {
    const r = await ctx.testConnection(props.library.id, collection.value.trim(), value || null)
    if (r.ok) result.value = r.data
  } finally {
    pat.value = ''
  }
}

async function remove() {
  if (!props.library) return
  const r = await ctx.deleteLibrary(props.library.id)
  confirmDelete.value = false
  if (r.ok) emit('deleted')
}

const patText = computed(() => {
  const c = props.library?.credential
  if (!c) return ''
  if (c.state === 'unreadable') return '无法读取 Keychain'
  return c.present ? '已保存' : '未保存'
})
const SOURCE = { imported: '导入', manual: '手动录入', unknown: '未知' } as const
</script>

<template>
  <div class="st-inspector" :data-testid="isNew ? 'library-new' : 'library-detail'">
    <div class="st-head">
      <BlockTag>LIB</BlockTag>
      <h2>{{ isNew ? '新建 library' : library!.name }}</h2>
    </div>

    <div class="st-fld">
      <span class="lbl" aria-hidden="true">名称</span>
      <TextInput v-model="name" label="library 名称" placeholder="例如：公司 ADO" />
    </div>
    <div class="st-fld">
      <span class="lbl" aria-hidden="true">地址</span>
      <TextInput v-model="baseUrl" label="library 地址" placeholder="https://ado.example.com/tfs" />
      <BlockTag v-if="isHttp" tone="warn" data-testid="http-warning"
        >HTTP 明文：PAT 将以明文传输</BlockTag
      >
    </div>

    <p v-if="localError" class="st-warn" role="alert" data-testid="library-local-error">
      {{ localError }}
    </p>

    <div
      v-if="originChange"
      class="st-box"
      data-tone="warn"
      role="alert"
      data-testid="pat-origin-change"
    >
      <strong class="st-warn">PAT 将发往新地址</strong>
      <div class="st-mono">{{ originChange }}</div>
      <div>地址的 origin 变了。请明确选择：保留已存 PAT（发往新地址），或输入新 PAT 替换。</div>
      <div class="st-actions">
        <AppButton
          variant="ghost"
          data-testid="origin-keep"
          :disabled="disabled"
          @click="resolveOrigin('keep')"
        >
          保留已存 PAT
        </AppButton>
        <AppButton
          variant="accent"
          data-testid="origin-replace"
          :disabled="disabled"
          @click="resolveOrigin('replace')"
        >
          用输入框中的 PAT 替换
        </AppButton>
      </div>
    </div>

    <div class="st-fld">
      <span class="lbl" aria-hidden="true">{{ isNew ? 'PAT（可选）' : 'PAT（只写）' }}</span>
      <TextInput
        v-model="pat"
        type="password"
        autocomplete="off"
        label="PAT"
        placeholder="粘贴新的 PAT；不会回显"
        :disabled="disabled"
      />
    </div>

    <template v-if="isNew">
      <div class="st-actions">
        <AppButton data-testid="library-create" :disabled="disabled" @click="create">
          新建
        </AppButton>
      </div>
    </template>
    <template v-else>
      <dl class="st-kv">
        <dt class="lbl">PAT 状态</dt>
        <dd data-testid="library-pat-status">
          {{ patText }}
          <template v-if="library!.credential.present !== false">
            · {{ SOURCE[library!.credential.source] }}
          </template>
        </dd>
      </dl>
      <div class="st-actions">
        <AppButton data-testid="library-save" :disabled="disabled" @click="save"
          >保存修改</AppButton
        >
        <AppButton
          variant="ghost"
          data-testid="pat-save"
          :disabled="disabled || !pat"
          @click="savePat"
        >
          {{ library!.credential.present ? '替换 PAT' : '保存 PAT' }}
        </AppButton>
        <AppButton
          v-if="library!.credential.present"
          variant="ghost"
          data-testid="pat-delete"
          :disabled="disabled"
          @click="ctx.deletePat(library!.id)"
        >
          删除 PAT
        </AppButton>
      </div>

      <hr class="st-sep" />
      <div class="st-fld">
        <span class="lbl" aria-hidden="true">测试连接 · collection</span>
        <TextInput v-model="collection" label="测试用 collection" placeholder="DefaultCollection" />
      </div>
      <p v-if="pat" class="st-note">将使用输入框里的 PAT 测试（不保存）。</p>
      <div class="st-actions">
        <AppButton
          variant="ghost"
          data-testid="library-test"
          :disabled="disabled || !collection.trim()"
          @click="test"
        >
          测试连接
        </AppButton>
      </div>
      <div
        v-if="result"
        class="st-box"
        :data-tone="result.ok ? undefined : 'warn'"
        role="status"
        data-testid="test-result"
        :data-category="result.category"
      >
        <strong :class="result.ok ? 'st-ok' : 'st-warn'">{{
          CATEGORY_TEXT[result.category]
        }}</strong>
        <span v-if="result.http_status" class="st-mono"> · HTTP {{ result.http_status }}</span>
        <div v-if="result.message">{{ result.message }}</div>
      </div>

      <hr class="st-sep" />
      <div v-if="!confirmDelete" class="st-actions">
        <AppButton
          variant="ghost"
          class="st-btn-danger"
          data-testid="library-delete"
          :disabled="disabled"
          @click="confirmDelete = true"
        >
          删除 library
        </AppButton>
      </div>
      <div v-else class="st-box" data-tone="warn" role="alertdialog" aria-label="确认删除 library">
        <strong>确认删除「{{ library!.name }}」？</strong>
        <div>
          将同时删除其下 {{ projects.length }} 个 project 与已存 PAT。被任务引用时无法删除。
        </div>
        <div class="st-actions">
          <AppButton
            variant="primary"
            data-testid="library-delete-confirm"
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
