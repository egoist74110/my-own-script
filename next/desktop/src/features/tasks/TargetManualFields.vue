<script setup lang="ts">
import TextField from '@/components/TextField.vue'
import type { EditableTarget } from './release-draft'

/** 手填一个发布目标的 ADO 字段（构建类型、构建定义、Release 定义、环境）。只放在“高级”折叠区里。 */
defineProps<{ showName?: boolean }>()
const target = defineModel<EditableTarget>({ required: true })
</script>

<template>
  <div class="tmf">
    <div class="two-cols">
      <div v-if="showName" class="fld">
        <span class="fld-lbl">目标名称</span>
        <TextField v-model="target.name" label="目标名称" placeholder="staging-a" required />
      </div>
      <div class="fld">
        <label class="fld-lbl" :for="`tgt-kind-${target.key}`">构建类型</label>
        <select :id="`tgt-kind-${target.key}`" v-model="target.build_kind" class="sel-ctl">
          <option value="build">Build</option>
          <option value="pipeline">Pipeline</option>
        </select>
      </div>
    </div>
    <div class="two-cols">
      <div class="fld">
        <span class="fld-lbl">构建定义 ID</span>
        <TextField v-model="target.build_id" label="构建定义 ID" placeholder="例如：12" />
      </div>
      <div class="fld">
        <span class="fld-lbl">构建定义名</span>
        <TextField v-model="target.build_name" label="构建定义名" placeholder="可选显示名" />
      </div>
    </div>
    <div class="two-cols">
      <div class="fld">
        <span class="fld-lbl">Release 定义 ID</span>
        <TextField v-model="target.release_id" label="Release 定义 ID" placeholder="例如：7" />
      </div>
      <div class="fld">
        <span class="fld-lbl">Release 定义名</span>
        <TextField v-model="target.release_name" label="Release 定义名" placeholder="可选显示名" />
      </div>
    </div>
    <div class="two-cols">
      <div class="fld">
        <span class="fld-lbl">环境 ID（逗号分隔）</span>
        <TextField v-model="target.release_stage_ids" label="环境 ID" placeholder="1, 2" />
      </div>
      <div class="fld">
        <span class="fld-lbl">环境名（逗号分隔）</span>
        <TextField v-model="target.release_stage_names" label="环境名" placeholder="QA, Staging" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.tmf {
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
.sel-ctl {
  height: var(--ctl-h);
  border-radius: var(--r-ctl);
  border: 1px solid var(--line);
  background: var(--bg-window);
  color: var(--ink);
  padding: 0 8px;
  font: inherit;
}
</style>
