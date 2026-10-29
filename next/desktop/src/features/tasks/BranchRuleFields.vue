<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown, ArrowRight, ArrowUp } from 'lucide-vue-next'
import Button from '@/components/Button.vue'
import TextField from '@/components/TextField.vue'
import BranchTagList from './BranchTagList.vue'
import { parseList, type EditableBranch } from './release-draft'

/**
 * 一个分支的 Git 规则：更新分支、合并规则、推送分支，都用选择器（选项来自远端分支），不手写。
 * 执行顺序：更新 → 按顺序合并 → 推送 → 构建。合并规则一行一条“源分支 → 目标分支”，可增删、上下移。
 * 编辑器与向导共用；labelPrefix 决定读屏标签，testidPrefix 决定 data-testid。
 * disabled（没有本地仓库路径）时只读显示已有值，不给编辑控件。
 */
const props = defineProps<{
  labelPrefix: string
  testidPrefix: string
  /** 是否显示“构建分支”输入（向导里分支名来自勾选，不再让人改）。 */
  showName?: boolean
  /** 远端分支（选项）；还没读到时为空，退回手输。 */
  options?: string[]
  loading?: boolean
  disabled?: boolean
}>()
const branch = defineModel<EditableBranch>({ required: true })

const tp = computed(() => props.testidPrefix)
const opts = computed(() => props.options ?? [])

const updateList = computed({
  get: () => parseList(branch.value.update_branches),
  set: (v: string[]) => (branch.value.update_branches = v.join(', ')),
})
const pushList = computed({
  get: () => parseList(branch.value.push_branches),
  set: (v: string[]) => (branch.value.push_branches = v.join(', ')),
})

interface Row {
  src: string
  dst: string
}
const rows = computed<Row[]>(() =>
  parseList(branch.value.merges).map((it) => {
    const [src = '', dst = ''] = it.split(/[:：]/).map((x) => x.trim())
    return { src, dst }
  }),
)
function setRows(rs: Row[]) {
  // 没填完整的行写成“源:”或“:目标”，会被保存校验拦住并在行内提示
  branch.value.merges = rs.map((r) => `${r.src}:${r.dst}`).join(', ')
}
function patchRow(i: number, patch: Partial<Row>) {
  setRows(rows.value.map((r, k) => (k === i ? { ...r, ...patch } : r)))
}
function addRow() {
  setRows([...rows.value, { src: '', dst: '' }])
}
function removeRow(i: number) {
  setRows(rows.value.filter((_r, k) => k !== i))
}
function moveRow(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= rows.value.length) return
  const list = [...rows.value]
  const tmp = list[i]!
  list[i] = list[j]!
  list[j] = tmp
  setRows(list)
}
function rowError(r: Row): string | null {
  if (!r.src || !r.dst) return '请选择源分支和目标分支'
  if (r.src === r.dst) return '源分支和目标分支不能相同'
  return null
}
/** 下拉选项：远端分支 + 当前值（远端没有的旧值也保留）。 */
function optionsFor(cur: string): string[] {
  const all = [...opts.value]
  if (cur && !all.includes(cur)) all.unshift(cur)
  return all
}
const rowDisplay = (r: Row) => `${r.src || '未选'} → ${r.dst || '未选'}`
</script>

<template>
  <div class="brf">
    <div v-if="showName" class="fld">
      <span class="fld-lbl">构建分支</span>
      <TextField v-model="branch.build_branch" :label="`${labelPrefix} 构建分支`" required />
    </div>

    <p class="order" :data-testid="`${tp}-order`">执行顺序：更新 → 按顺序合并 → 推送 → 构建</p>
    <p v-if="loading" class="hint" role="status">正在读取远端分支…</p>

    <div class="fld">
      <span class="fld-lbl">更新分支（先把这些分支拉到最新）</span>
      <BranchTagList
        v-model="updateList"
        :label="`${labelPrefix} 更新分支`"
        :testid="`${tp}-update`"
        :options="opts"
        :disabled="disabled"
      />
    </div>

    <div class="fld">
      <span class="fld-lbl">合并规则（按顺序执行：把源分支合并进目标分支）</span>
      <ul class="rows" :data-testid="`${tp}-merges`">
        <li v-for="(r, i) in rows" :key="i" class="row" :data-testid="`${tp}-merge-row-${i}`">
          <template v-if="disabled">
            <span class="mono">{{ rowDisplay(r) }}</span>
          </template>
          <template v-else>
            <span class="row-n">{{ i + 1 }}</span>
            <select
              v-if="opts.length"
              class="sel"
              :aria-label="`${labelPrefix} 合并 ${i + 1} 源分支`"
              :value="r.src"
              :data-testid="`${tp}-merge-src-${i}`"
              @change="patchRow(i, { src: ($event.target as HTMLSelectElement).value })"
            >
              <option value="" disabled>选择源分支</option>
              <option v-for="o in optionsFor(r.src)" :key="o" :value="o">{{ o }}</option>
            </select>
            <TextField
              v-else
              :model-value="r.src"
              :label="`${labelPrefix} 合并 ${i + 1} 源分支`"
              placeholder="源分支名"
              @update:model-value="patchRow(i, { src: $event.trim() })"
            />
            <ArrowRight :size="14" aria-hidden="true" />
            <select
              v-if="opts.length"
              class="sel"
              :aria-label="`${labelPrefix} 合并 ${i + 1} 目标分支`"
              :value="r.dst"
              :data-testid="`${tp}-merge-dst-${i}`"
              @change="patchRow(i, { dst: ($event.target as HTMLSelectElement).value })"
            >
              <option value="" disabled>选择目标分支</option>
              <option v-for="o in optionsFor(r.dst)" :key="o" :value="o">{{ o }}</option>
            </select>
            <TextField
              v-else
              :model-value="r.dst"
              :label="`${labelPrefix} 合并 ${i + 1} 目标分支`"
              placeholder="目标分支名"
              @update:model-value="patchRow(i, { dst: $event.trim() })"
            />
            <button
              type="button"
              class="mini"
              aria-label="上移"
              :disabled="i === 0"
              :data-testid="`${tp}-merge-up-${i}`"
              @click="moveRow(i, -1)"
            >
              <ArrowUp :size="13" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="mini"
              aria-label="下移"
              :disabled="i === rows.length - 1"
              :data-testid="`${tp}-merge-down-${i}`"
              @click="moveRow(i, 1)"
            >
              <ArrowDown :size="13" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="mini txt"
              :data-testid="`${tp}-merge-del-${i}`"
              @click="removeRow(i)"
            >
              删除
            </button>
          </template>
          <p
            v-if="!disabled && rowError(r)"
            class="need"
            role="alert"
            :data-testid="`${tp}-merge-err-${i}`"
          >
            {{ rowError(r) }}
          </p>
        </li>
        <li v-if="rows.length === 0" class="none" :data-testid="`${tp}-merge-none`">未设置</li>
      </ul>
      <div v-if="!disabled">
        <Button type="button" :data-testid="`${tp}-merge-add`" @click="addRow">添加合并规则</Button>
      </div>
    </div>

    <div class="fld">
      <span class="fld-lbl">推送分支（构建前推到远端）</span>
      <BranchTagList
        v-model="pushList"
        :label="`${labelPrefix} 推送分支`"
        :testid="`${tp}-push`"
        :options="opts"
        :disabled="disabled"
      />
    </div>
  </div>
</template>

<style scoped>
.brf {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.fld {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fld-lbl {
  font-size: var(--text-sub);
  color: var(--mute);
}
.order,
.hint {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.order {
  font-weight: 600;
}
.need {
  margin: 0;
  flex-basis: 100%;
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--bn-warn-fg);
}
.rows {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.row-n {
  flex: none;
  width: 16px;
  font-family: var(--font-mono);
  font-size: var(--text-sub);
  color: var(--mute);
}
.sel {
  flex: 1;
  min-width: 0;
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--ink);
  padding: 0 8px;
  font: inherit;
}
.row > :deep(.text-input) {
  flex: 1;
  min-width: 0;
}
.mini {
  flex: none;
  min-width: 26px;
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: var(--r-ctl);
  background: var(--ctl);
  color: var(--ink);
  font: inherit;
  font-size: var(--text-sub);
  cursor: pointer;
}
.mini.txt {
  padding: 0 8px;
  color: var(--danger);
}
.mini:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.none {
  font-size: var(--text-sub);
  color: var(--mute);
}
.mono {
  font-family: var(--font-mono);
}
</style>
