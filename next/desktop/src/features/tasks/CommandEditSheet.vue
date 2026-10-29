<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp } from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import Sheet from '@/components/Sheet.vue'
import TextField from '@/components/TextField.vue'
import Switch from '@/components/ui/switch/Switch.vue'
import {
  releaseErrorText,
  type CommandCreate,
  type CommandPatch,
  type CommandView,
  type ReleaseView,
} from './api'

/**
 * 运行命令编辑器：名称、TG 命令与说明、是否启用、用哪个分支（必选），以及要发布的目标（有序、至少一个）。
 * 分支和目标只能从所属配置的目录里选；要新分支或新目标先编辑配置。
 */
const props = defineProps<{
  open: boolean
  config: ReleaseView | null
  /** 编辑时传入现有命令；新建传 null。 */
  command: CommandView | null
  /** 这份表单所依据的配置版本（乐观锁）。 */
  revision: number
  submitting?: boolean
  error?: unknown
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  save: [payload: CommandCreate | CommandPatch]
}>()

const isEdit = computed(() => Boolean(props.command))

const name = ref('')
const tgCommand = ref('')
const tgDesc = ref('')
const enabled = ref(true)
/** 选中的分支 id；空串表示还没选。 */
const branchId = ref('')
/** 已选目标 id，顺序就是执行顺序。 */
const selected = ref<string[]>([])

const branchCatalog = computed(() => props.config?.branches ?? [])

const catalog = computed(() => props.config?.targets ?? [])
const selectedTargets = computed(() =>
  selected.value
    .map((id) => catalog.value.find((t) => t.id === id))
    .filter((t): t is NonNullable<typeof t> => Boolean(t)),
)
const unselectedTargets = computed(() =>
  catalog.value.filter((t) => !selected.value.includes(t.id)),
)

function initForm() {
  const c = props.command
  name.value = c?.name ?? ''
  tgCommand.value = c?.tg_command ?? ''
  tgDesc.value = c?.tg_desc ?? ''
  enabled.value = c?.enabled ?? true
  // 命令原来的分支已被删掉时不保留，让用户重选；新建时只有一个分支就直接选上
  const branchIds = branchCatalog.value.map((b) => b.id)
  branchId.value = c
    ? branchIds.includes(c.branch_id)
      ? c.branch_id
      : ''
    : branchIds.length === 1
      ? branchIds[0]!
      : ''
  const ids = new Set(catalog.value.map((t) => t.id))
  selected.value = (c?.target_ids ?? []).filter((id) => ids.has(id))
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) initForm()
  },
)

function add(id: string) {
  if (!selected.value.includes(id)) selected.value.push(id)
}
function remove(id: string) {
  selected.value = selected.value.filter((x) => x !== id)
}
function move(idx: number, dir: -1 | 1) {
  const to = idx + dir
  if (to < 0 || to >= selected.value.length) return
  const list = [...selected.value]
  const tmp = list[idx]!
  list[idx] = list[to]!
  list[to] = tmp
  selected.value = list
}

const noneSelected = computed(() => selected.value.length === 0)
const noBranch = computed(() => !branchId.value)
const canSave = computed(() => Boolean(name.value.trim()) && !noBranch.value && !noneSelected.value)

function onSubmit() {
  if (props.submitting || !canSave.value) return
  const payload: CommandCreate = {
    name: name.value.trim(),
    tg_command: tgCommand.value.trim(),
    tg_desc: tgDesc.value.trim(),
    enabled: enabled.value,
    branch_id: branchId.value,
    sort_order: props.command?.sort_order ?? props.config?.commands.length ?? 0,
    target_ids: [...selected.value],
    revision: props.revision,
  }
  emit('save', payload)
}
</script>

<template>
  <Sheet
    :open="open"
    :title="isEdit ? '编辑运行命令' : '新建运行命令'"
    :description="`属于发布配置“${config?.name ?? ''}”。运行时只发布这里选的目标，不能临时加减。`"
    @update:open="emit('update:open', $event)"
  >
    <div class="cmd-body" data-testid="command-edit-sheet">
      <Banner v-if="error" kind="error" class="mb-2" data-testid="command-edit-error">
        {{ releaseErrorText(error) }}
      </Banner>

      <form class="cmd-form" @submit.prevent="onSubmit">
        <div class="fld">
          <span class="fld-lbl">命令名称</span>
          <TextField
            v-model="name"
            label="命令名称"
            placeholder="例如：同步构建发布测试环境"
            required
          />
        </div>
        <div class="two-cols">
          <div class="fld">
            <span class="fld-lbl">TG 命令</span>
            <TextField
              v-model="tgCommand"
              label="TG 命令"
              placeholder="例如：sync_build_event_test"
            />
          </div>
          <div class="fld">
            <span class="fld-lbl">TG 说明</span>
            <TextField v-model="tgDesc" label="TG 说明" placeholder="在 Telegram 里显示的说明" />
          </div>
        </div>
        <p class="hint">TG 命令留空时，这条命令只能在桌面端运行。</p>

        <div class="switch-row">
          <span class="switch-label">启用这条命令</span>
          <Switch v-model:checked="enabled" aria-label="启用这条命令" />
        </div>

        <h4 class="form-sec-title">分支</h4>
        <p v-if="branchCatalog.length === 0" class="hint" data-testid="command-no-branches">
          这个配置还没有分支。请先关闭这里，编辑配置并添加分支。
        </p>
        <fieldset v-else class="branch-pick" data-testid="command-branch-field">
          <legend class="hint">这条命令运行时用哪个分支的规则同步代码</legend>
          <label v-for="b in branchCatalog" :key="b.id" class="branch-opt">
            <input
              v-model="branchId"
              type="radio"
              name="command-branch"
              :value="b.id"
              :data-testid="`select-branch-${b.id}`"
            />
            <span class="mono">{{ b.build_branch }}</span>
            <span v-if="b.update_branches?.length || b.push_branches?.length" class="hint">
              更新 {{ b.update_branches?.join(', ') || '—' }}，推送
              {{ b.push_branches?.join(', ') || '—' }}
            </span>
          </label>
        </fieldset>
        <p
          v-if="noBranch && branchCatalog.length > 0"
          class="need"
          data-testid="command-branch-required"
          role="alert"
        >
          请选择一个分支，才能保存。
        </p>

        <h4 class="form-sec-title">发布目标</h4>
        <p v-if="catalog.length === 0" class="hint" data-testid="command-no-catalog">
          这个配置还没有发布目标。请先关闭这里，编辑配置并添加目标。
        </p>

        <ol v-if="selectedTargets.length" class="sel-list" aria-label="已选目标，按顺序发布">
          <li
            v-for="(t, i) in selectedTargets"
            :key="t.id"
            class="sel-row"
            :data-testid="`selected-target-${t.id}`"
          >
            <span class="sel-n">{{ i + 1 }}</span>
            <span class="sel-name">{{ t.name }}</span>
            <button
              type="button"
              class="mini-btn"
              :aria-label="`上移 ${t.name}`"
              :disabled="i === 0"
              @click="move(i, -1)"
            >
              <ArrowUp :size="13" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="mini-btn"
              :aria-label="`下移 ${t.name}`"
              :disabled="i === selectedTargets.length - 1"
              @click="move(i, 1)"
            >
              <ArrowDown :size="13" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="mini-btn text"
              :aria-label="`取消选择 ${t.name}`"
              :data-testid="`unselect-target-${t.id}`"
              @click="remove(t.id)"
            >
              取消选择
            </button>
          </li>
        </ol>

        <ul v-if="unselectedTargets.length" class="pool-list" aria-label="可添加的目标">
          <li v-for="t in unselectedTargets" :key="t.id" class="pool-row">
            <span class="sel-name">{{ t.name }}</span>
            <button
              type="button"
              class="mini-btn text"
              :aria-label="`添加 ${t.name}`"
              :data-testid="`select-target-${t.id}`"
              @click="add(t.id)"
            >
              添加
            </button>
          </li>
        </ul>

        <p
          v-if="noneSelected && catalog.length > 0"
          class="need"
          data-testid="command-targets-required"
          role="alert"
        >
          至少选择一个发布目标，才能保存。
        </p>
        <p v-else-if="selectedTargets.length > 1" class="hint">
          运行时按上面的顺序，一个接一个发布。
        </p>
      </form>
    </div>

    <template #actions>
      <Button :disabled="submitting" @click="emit('update:open', false)">取消</Button>
      <Button
        variant="primary"
        data-testid="save-command-btn"
        :disabled="submitting || !canSave"
        @click="onSubmit"
      >
        {{ submitting ? '保存中…' : '保存命令' }}
      </Button>
    </template>
  </Sheet>
</template>

<style scoped>
.cmd-body {
  max-height: 65vh;
  overflow-y: auto;
  padding: 4px 2px;
}
.cmd-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.two-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
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
.branch-pick {
  margin: 0;
  padding: 0;
  border: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.branch-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  cursor: pointer;
}
.mono {
  font-family: var(--font-mono);
}
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 0;
}
.switch-label {
  font-size: var(--text-body);
  color: var(--ink);
  font-weight: 500;
}
.form-sec-title {
  margin: 8px 0 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  border-bottom: 1px solid var(--line);
  padding-bottom: 4px;
}
.hint {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.need {
  margin: 0;
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--bn-warn-fg);
}
.sel-list,
.pool-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sel-row,
.pool-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
}
.pool-row {
  border-style: dashed;
}
.sel-n {
  flex: none;
  width: 18px;
  font-family: var(--font-mono);
  font-size: var(--text-sub);
  color: var(--mute);
}
.sel-name {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.mini-btn {
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
.mini-btn.text {
  padding: 0 8px;
}
.mini-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.mb-2 {
  margin-bottom: 8px;
}
</style>
