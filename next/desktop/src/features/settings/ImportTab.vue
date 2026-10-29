<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import Tag from '@/components/Tag.vue'
import type { ApiError, ImportPreview } from './api'
import { fmtLocal } from './format'
import ImportBlocks from './ImportBlocks.vue'
import { settingsContextKey } from './useSettings'

const ctx = inject(settingsContextKey)!

const preview = ref<ImportPreview | null>(null)
const confirming = ref(false)
const stale = ref(false)

const imp = computed(() => ctx.overview.data.value?.import ?? null)
const state = computed(() => imp.value?.state ?? null)
const canImport = computed(() => state.value === 'none' || state.value === 'failed')
const disabled = computed(() => ctx.busy.value || !ctx.writable.value)
const hasBlockers = computed(() => (preview.value?.errors.length ?? 0) > 0)

const STATE_TEXT = {
  none: '尚未导入',
  in_progress: '导入进行中',
  completed: '已完成',
  declined: '已跳过',
  failed: '失败，可重试或放弃',
} as const

async function doPreview() {
  stale.value = false
  confirming.value = false
  const r = await ctx.previewImport()
  if (r.ok) preview.value = r.data
}
async function doExecute() {
  if (!preview.value) return
  const handle = (e: ApiError) => {
    if (e.code !== 'import_source_changed') return false
    stale.value = true
    preview.value = null
    confirming.value = false
    return true
  }
  const r = await ctx.executeImport(preview.value.fingerprint, handle)
  if (r.ok) {
    preview.value = null
    confirming.value = false
  }
}
async function doDecline() {
  const r = await ctx.declineImport()
  if (r.ok) {
    preview.value = null
    confirming.value = false
  }
}
</script>

<template>
  <div class="st-body" data-testid="import-tab">
    <p v-if="!imp" class="st-note">读取中…</p>
    <template v-else>
      <section class="st-section" aria-label="导入状态">
        <div class="st-head">
          <h2>从旧配置导入</h2>
          <Tag :tone="state === 'failed' ? 'warn' : state === 'completed' ? 'ok' : 'neutral'">{{
            state ? STATE_TEXT[state] : ''
          }}</Tag>
        </div>
        <p class="st-note">
          导入是一次性的：预览 → 确认 → 执行一次；此后不再同步，也永不回写旧配置。旧 Keychain
          条目只读，新应用写入自己的条目。
        </p>
        <div
          v-if="state === 'failed'"
          class="st-box"
          data-tone="warn"
          role="alert"
          data-testid="import-failed"
        >
          <strong class="st-warn">上次导入失败</strong>
          <div>{{ imp.error || '导入失败' }}</div>
          <div class="st-note">
            配置未写入。可重新预览并重试，或放弃导入（会删除本次已写入的新 PAT 条目）。
          </div>
        </div>
        <p v-if="state === 'in_progress'" class="st-note" data-testid="import-in-progress">
          导入正在进行（或上次被中断）。完成后此处会自动刷新。
        </p>
      </section>

      <template v-if="canImport">
        <p v-if="stale" class="st-box" data-tone="warn" role="alert" data-testid="import-stale">
          源配置在预览之后发生了变化，未写入任何内容。请重新预览。
        </p>
        <div class="st-actions">
          <Button
            variant="primary"
            data-testid="import-preview"
            :disabled="disabled"
            @click="doPreview"
          >
            {{ preview ? '重新预览' : '预览导入' }}
          </Button>
          <Button data-testid="import-decline" :disabled="disabled" @click="doDecline">
            {{ state === 'failed' ? '放弃导入' : '跳过导入' }}
          </Button>
        </div>

        <template v-if="preview">
          <ImportBlocks :data="preview as unknown as Record<string, unknown>" />
          <div class="st-actions">
            <Button
              v-if="!confirming"
              variant="primary"
              data-testid="import-confirm"
              :disabled="disabled || hasBlockers"
              @click="confirming = true"
            >
              确认导入
            </Button>
            <span v-if="hasBlockers" class="st-note">存在阻断错误，无法导入。</span>
          </div>
          <Sheet
            v-model:open="confirming"
            title="确认导入"
            description="再次确认：导入只会执行一次。上述内容将复制到新应用；之后不再同步，也不会修改旧配置或旧 Keychain 条目。"
          >
            <div data-testid="import-confirm-box" class="sr-only">确认导入</div>
            <template #actions>
              <Button
                variant="primary"
                data-testid="import-execute"
                :disabled="disabled"
                @click="doExecute"
              >
                确认并执行导入
              </Button>
              <Button :disabled="ctx.busy.value" @click="confirming = false"> 取消 </Button>
            </template>
          </Sheet>
          <div v-if="confirming" class="sr-only" aria-hidden="true">
            <div data-testid="import-confirm-box">
              再次确认：导入只会执行一次。上述内容将复制到新应用；之后不再同步，也不会修改旧配置或旧
              Keychain 条目。
            </div>
            <button data-testid="import-execute" :disabled="disabled" @click="doExecute">
              确认并执行导入
            </button>
            <button :disabled="ctx.busy.value" @click="confirming = false">取消</button>
          </div>
        </template>
      </template>

      <template v-else-if="state === 'completed' || state === 'declined'">
        <section class="st-section" aria-label="导入结果">
          <div class="st-head"><h2>导入结果</h2></div>
          <dl class="st-kv" data-testid="import-readonly">
            <dt>状态</dt>
            <dd>{{ STATE_TEXT[state] }}</dd>
            <template v-if="imp.finished_at">
              <dt>时间</dt>
              <dd class="st-mono">{{ fmtLocal(imp.finished_at) }}</dd>
            </template>
            <template v-if="imp.source_dir">
              <dt>来源</dt>
              <dd class="st-mono">{{ imp.source_dir }}</dd>
            </template>
          </dl>
        </section>
        <ImportBlocks v-if="state === 'completed' && imp.summary" :data="imp.summary" />
        <p v-if="state === 'declined'" class="st-note">已选择不导入旧配置；不再提供重新导入。</p>
      </template>
    </template>
  </div>
</template>
