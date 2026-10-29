<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Button from '@/components/Button.vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'
import type { DiscoverTargetsResponse } from './discover'
import { parseList, safeStageName, type EditableTarget } from './release-draft'

/**
 * 表单式添加发布目标（编辑器与向导共用）：先选构建定义，再选引用它的 Release 定义，再勾环境，起个名字，点“添加”。
 * - 构建定义列出 ADO 上的全部构建；没有被任何 Release 引用的也列出，但标注并且不可选。
 * - 同一个（构建, Release）可以添加多次（环境不同、名称不同）；只有“构建 + Release + 环境集合完全相同”才算重复。
 * - 环境默认全部不勾，至少勾一个才能添加（真实数据里常含正式环境，绝不默认勾）。
 * - 添加后环境和名称重置，构建/Release 的选择保留，方便连续添加同一配对的不同环境目标；面板不关闭。
 */
const props = defineProps<{
  data: DiscoverTargetsResponse
  /** 当前配置里已有的目标（含刚添加的），用于重名与重复判断。 */
  existing: EditableTarget[]
}>()
const emit = defineEmits<{ add: [target: EditableTarget] }>()

const buildId = ref('')
const releaseId = ref('')
const stages = ref<string[]>([])
const name = ref('')
const nameTouched = ref(false)
let seq = 0

const releasesOf = (bid: string) =>
  props.data.releases.filter((r) => r.build_definition_ids.includes(bid))
const linked = (bid: string) => releasesOf(bid).length > 0

const build = computed(() => props.data.builds.find((b) => b.id === buildId.value) ?? null)
const releases = computed(() => (buildId.value ? releasesOf(buildId.value) : []))
const release = computed(() => releases.value.find((r) => r.id === releaseId.value) ?? null)
const envs = computed(() => release.value?.environments ?? [])
/** 仓库里一个被 Release 引用的构建定义都没有：这时没有任何东西可加。 */
const noneLinked = computed(() => !props.data.builds.some((b) => linked(b.id)))

function onBuild(v: string) {
  buildId.value = v
  stages.value = []
  const rs = releasesOf(v)
  // 只有一个 Release 引用它时自动选中；否则让用户选
  releaseId.value = rs.length === 1 ? rs[0]!.id : ''
}
function onRelease(v: string) {
  releaseId.value = v
  stages.value = []
}
function toggle(id: string, on: boolean) {
  const rest = stages.value.filter((x) => x !== id)
  stages.value = on ? [...rest, id] : rest
}

const chosen = computed(() =>
  envs.value
    .filter((e) => stages.value.includes(e.id))
    .map((e) => ({ id: e.id, name: safeStageName(e.name, e.id) })),
)

const existingNames = computed(() => new Set(props.existing.map((t) => t.name.trim())))
/** 默认名：Release 定义名；同名已存在时加上所选第一个环境名。 */
const defaultName = computed(() => {
  const base = release.value?.name ?? ''
  if (!base) return ''
  if (existingNames.value.has(base) && chosen.value.length > 0)
    return `${base} · ${chosen.value[0]!.name}`
  return base
})
watch(
  defaultName,
  (v) => {
    if (!nameTouched.value) name.value = v
  },
  { immediate: true },
)
function onName(v: string) {
  name.value = v
  nameTouched.value = true
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x))
const identical = computed(() =>
  props.existing.some(
    (t) =>
      t.build_id.trim() === buildId.value &&
      t.release_id.trim() === releaseId.value &&
      sameSet(parseList(t.release_stage_ids), stages.value),
  ),
)
const nameDup = computed(() => existingNames.value.has(name.value.trim()))

const problem = computed(() => {
  if (!buildId.value || !releaseId.value) return null
  if (stages.value.length === 0) return '至少勾选一个环境才能添加'
  if (!name.value.trim()) return '请填写目标名称'
  if (identical.value) return '已存在相同目标（构建定义、Release 定义和环境都一样）'
  if (nameDup.value) return `已有同名目标“${name.value.trim()}”，请换一个名称`
  return null
})
const canAdd = computed(
  () => Boolean(build.value && release.value && stages.value.length > 0) && problem.value === null,
)

function add() {
  if (!canAdd.value) return
  const b = build.value!
  const r = release.value!
  emit('add', {
    id: null,
    key: `added-${seq++}`,
    name: name.value.trim(),
    enabled: true,
    build_kind: b.kind,
    build_id: b.id,
    build_name: b.name,
    release_id: r.id,
    release_name: r.name,
    release_stage_ids: chosen.value.map((c) => c.id).join(', '),
    release_stage_names: chosen.value.map((c) => c.name).join(', '),
  })
  // 重置环境和名称；构建/Release 保留
  stages.value = []
  nameTouched.value = false
  name.value = defaultName.value
}
</script>

<template>
  <div class="ta" data-testid="target-adder">
    <p v-if="noneLinked" class="ta-hint" data-testid="adder-none">
      这个仓库在 ADO 上没有关联 Release 的构建定义，没有可以添加的目标。
    </p>
    <template v-else>
      <div class="ta-fld">
        <label class="ta-lbl" for="adder-build">构建定义</label>
        <select
          id="adder-build"
          class="ta-sel"
          :value="buildId"
          data-testid="adder-build"
          @change="onBuild(($event.target as HTMLSelectElement).value)"
        >
          <option value="" disabled>请选择构建定义</option>
          <option v-for="b in data.builds" :key="b.id" :value="b.id" :disabled="!linked(b.id)">
            {{ b.name }}（{{ b.kind === 'pipeline' ? 'Pipeline' : 'Build' }}）{{
              linked(b.id) ? '' : '：没有关联的 Release，无法发布'
            }}
          </option>
        </select>
      </div>
      <div class="ta-fld">
        <label class="ta-lbl" for="adder-release">Release 定义</label>
        <select
          id="adder-release"
          class="ta-sel"
          :value="releaseId"
          :disabled="!buildId"
          data-testid="adder-release"
          @change="onRelease(($event.target as HTMLSelectElement).value)"
        >
          <option value="" disabled>
            {{ buildId ? '请选择 Release 定义' : '先选构建定义' }}
          </option>
          <option v-for="r in releases" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
      </div>
      <template v-if="release">
        <p class="ta-lbl">要发布到的环境（默认都不勾，至少勾一个；请留意正式环境）</p>
        <div class="ta-envs">
          <label v-for="e in envs" :key="e.id" class="ta-env">
            <input
              type="checkbox"
              :checked="stages.includes(e.id)"
              :data-testid="`adder-env-${e.id}`"
              @change="toggle(e.id, ($event.target as HTMLInputElement).checked)"
            />
            <span>{{ e.name }}</span>
          </label>
          <span v-if="envs.length === 0" class="ta-hint">这个 Release 定义没有环境。</span>
        </div>
        <div class="ta-fld">
          <span class="ta-lbl">目标名称</span>
          <TextField
            :model-value="name"
            label="新目标名称"
            placeholder="目标名称"
            data-testid="adder-name"
            @update:model-value="onName"
          />
        </div>
        <p v-if="problem" class="ta-need" role="alert" data-testid="adder-problem">{{ problem }}</p>
        <div class="ta-actions">
          <Button variant="primary" data-testid="adder-add-btn" :disabled="!canAdd" @click="add">
            添加这个目标
          </Button>
          <Tag v-if="stages.length > 0" tone="ok">已选 {{ stages.length }} 个环境</Tag>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.ta {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ta-fld {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ta-lbl {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.ta-hint {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.ta-need {
  margin: 0;
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--bn-warn-fg);
}
.ta-sel {
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--ink);
  padding: 0 8px;
  font: inherit;
}
.ta-envs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}
.ta-env {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.ta-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
