<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import BlockTag from '@/components/BlockTag.vue'
import TextInput from '@/components/TextInput.vue'
import {
  CATEGORY_TEXT,
  originOf,
  patError,
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
/** 待确认的 origin 变更：冻结的完整请求体与目标 origin（确认只提交它，期间名称/地址输入禁用）。 */
const pending = ref<{
  body: { name?: string; base_url?: string }
  origin: string
  /** 冻结时的目标条目 id 与编辑会话：确认只发往它，会话变了就不可确认。 */
  id: string
  session: number
} | null>(null)
const localError = ref<string | null>(null)

const isNew = computed(() => props.library === null)
const projects = computed(() =>
  (ctx.ado.data.value?.projects ?? []).filter((p) => p.library_id === props.library?.id),
)
const disabled = computed(() => ctx.busy.value || !ctx.writable.value)

/**
 * 编辑会话：每次开始编辑（选中条目变化或新建）递增。写请求发出时捕获当时的会话，
 * 响应及回调只在会话仍是当前会话时作用于组件状态，否则丢弃（CR-S1B-005）。
 */
let session = 0

/** 编辑基线：开始编辑（选中/新建）时的字段值与当时的 revision；外部变更不改它。 */
let baseline: { name: string; base_url: string; revision: number | null } = {
  name: '',
  base_url: '',
  revision: null,
}
function captureBaseline() {
  baseline = {
    name: props.library?.name ?? '',
    base_url: props.library?.base_url ?? '',
    revision: ctx.ado.data.value?.revision ?? null,
  }
}
const baseOpts = (s: number) => ({
  ...(baseline.revision !== null ? { revision: baseline.revision } : {}),
  onConflict: () => mergeConflict(s),
})

/** revision_conflict 后：用户改过的字段保留，未改字段换成服务器新值，基线整体更新。 */
function mergeConflict(s: number): boolean {
  if (s !== session) return false
  pending.value = null
  const fresh = ctx.ado.data.value
  const lib = fresh?.libraries.find((l) => l.id === props.library?.id)
  if (!fresh || !lib) return false
  if (name.value.trim() === baseline.name) name.value = lib.name
  if (baseUrl.value.trim() === baseline.base_url) baseUrl.value = lib.base_url
  baseline = { name: lib.name, base_url: lib.base_url, revision: fresh.revision }
  return true
}

function applySaved(s: number, body: { name?: string; base_url?: string }, revision: number) {
  if (s !== session) return
  baseline = { ...baseline, ...body, revision }
  pending.value = null
}

/** PAT 类写操作用缓存 revision：若只有本次写入推进了 revision，则基线随之前进。 */
function advanceBaseline(s: number, r: { ok: boolean; rev: number | null; data?: unknown }) {
  if (s !== session) return
  const d = r.data as { revision?: number } | undefined
  if (r.ok && r.rev !== null && r.rev === baseline.revision && typeof d?.revision === 'number')
    baseline.revision = d.revision
}

watch(
  () => props.library?.id ?? null,
  () => {
    session++
    captureBaseline()
    name.value = props.library?.name ?? ''
    baseUrl.value = props.library?.base_url ?? ''
    pat.value = ''
    collection.value = projects.value[0]?.collection ?? ''
    result.value = null
    confirmDelete.value = false
    pending.value = null
    localError.value = null
  },
  { immediate: true, flush: 'sync' },
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
  if (value) {
    localError.value = patError(value)
    if (localError.value) return
  }
  const s = session
  let sent = false
  try {
    const r = await ctx.createLibrary(name.value.trim(), baseUrl.value.trim(), value || null)
    sent = r.sent
    if (r.ok && r.data.id && s === session) emit('select', r.data.id)
  } finally {
    // 会话已变时切换已清空 PAT，此处不得清掉新会话里用户输入的内容
    if (sent && s === session) pat.value = ''
  }
}

function changed() {
  const body: { name?: string; base_url?: string } = {}
  if (name.value.trim() !== baseline.name) body.name = name.value.trim()
  if (baseUrl.value.trim() !== baseline.base_url) body.base_url = baseUrl.value.trim()
  return body
}

async function save() {
  localError.value = validate()
  if (localError.value || !props.library) return
  const body = changed()
  if (!Object.keys(body).length) return
  const s = session
  const id = props.library.id
  const origin = originOf(body.base_url ?? baseline.base_url) ?? ''
  const r = await ctx.patchLibrary(
    id,
    body,
    (e: ApiError) => {
      if (e.code !== 'pat_origin_change' || s !== session) return false
      pending.value = { body: { ...body }, origin, id, session: s }
      return true
    },
    baseOpts(s),
  )
  if (r.ok) applySaved(s, body, r.data.revision)
}

async function resolveOrigin(mode: 'keep' | 'replace') {
  const frozen = pending.value
  if (!props.library || !frozen || frozen.session !== session) return
  const s = frozen.session
  const value = pat.value
  if (mode === 'replace') {
    localError.value = !value ? '请输入新的 PAT' : patError(value)
    if (localError.value) return
  }
  localError.value = null
  let sent = false
  try {
    const r = await ctx.patchLibrary(
      frozen.id,
      { ...frozen.body, ...(mode === 'keep' ? { keep_pat: true } : { pat: value }) },
      undefined,
      baseOpts(s),
    )
    sent = r.sent
    if (r.ok) applySaved(s, frozen.body, r.data.revision)
  } finally {
    if (sent && s === session) pat.value = ''
  }
}

async function savePat() {
  if (!props.library || !pat.value) return
  const value = pat.value
  localError.value = patError(value)
  if (localError.value) return
  const s = session
  let sent = false
  try {
    const r = await ctx.putPat(props.library.id, value)
    sent = r.sent
    advanceBaseline(s, r)
  } finally {
    if (sent && s === session) pat.value = ''
  }
}

async function removePat() {
  if (!props.library) return
  const s = session
  advanceBaseline(s, await ctx.deletePat(props.library.id))
}

async function test() {
  if (!props.library) return
  const value = pat.value
  if (value) {
    localError.value = patError(value)
    if (localError.value) return
  }
  result.value = null
  const s = session
  let sent = false
  try {
    const r = await ctx.testConnection(props.library.id, collection.value.trim(), value || null)
    sent = r.sent
    if (r.ok && s === session) result.value = r.data
  } finally {
    if (sent && s === session) pat.value = ''
  }
}

async function remove() {
  if (!props.library) return
  const s = session
  const r = await ctx.deleteLibrary(props.library.id)
  if (s !== session) return
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
      <TextInput
        v-model="name"
        label="library 名称"
        placeholder="例如：公司 ADO"
        :disabled="!!pending"
      />
    </div>
    <div class="st-fld">
      <span class="lbl" aria-hidden="true">地址</span>
      <TextInput
        v-model="baseUrl"
        label="library 地址"
        placeholder="https://ado.example.com/tfs"
        :disabled="!!pending"
      />
      <BlockTag v-if="isHttp" tone="warn" data-testid="http-warning"
        >HTTP 明文：PAT 将以明文传输</BlockTag
      >
    </div>

    <p v-if="localError" class="st-warn" role="alert" data-testid="library-local-error">
      {{ localError }}
    </p>

    <div
      v-if="pending"
      class="st-box"
      data-tone="warn"
      role="alert"
      data-testid="pat-origin-change"
    >
      <strong class="st-warn">PAT 将发往新地址</strong>
      <div class="st-mono">{{ pending.origin }}</div>
      <div>
        地址的 origin 变了。请明确选择：保留已存 PAT（发往新地址），或输入新 PAT
        替换。确认期间名称与地址已锁定。
      </div>
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
        <AppButton variant="ghost" data-testid="origin-cancel" @click="pending = null">
          取消修改地址
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
        <AppButton data-testid="library-save" :disabled="disabled || !!pending" @click="save"
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
          @click="removePat"
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
