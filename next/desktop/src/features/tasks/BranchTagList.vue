<script setup lang="ts">
import { ref } from 'vue'
import { X } from 'lucide-vue-next'
import Button from '@/components/Button.vue'
import TextField from '@/components/TextField.vue'
import BranchPicker from './BranchPicker.vue'
import { parseList } from './release-draft'

/**
 * 标签式分支多选（更新分支、推送分支）：已选分支是带 × 的标签，空时显示“未设置”。
 * “添加分支”展开可搜索的远端分支列表；远端读不到时仍可在“其他分支名”里手输。顺序按添加先后。
 */
const props = defineProps<{
  label: string
  testid: string
  options: string[]
  disabled?: boolean
}>()
const list = defineModel<string[]>({ default: () => [] })

const open = ref(false)
const extra = ref('')

function remove(b: string) {
  list.value = list.value.filter((x) => x !== b)
}
function addExtra() {
  // 手输支持逗号、中文逗号、顿号分隔的多个分支名
  const names = parseList(extra.value).filter((n) => !list.value.includes(n))
  if (names.length) list.value = [...list.value, ...names]
  extra.value = ''
}
</script>

<template>
  <div class="btl" :data-testid="testid">
    <div class="btl-tags">
      <span v-for="b in list" :key="b" class="btl-tag" :data-testid="`${testid}-tag-${b}`">
        <span class="mono">{{ b }}</span>
        <button
          v-if="!disabled"
          type="button"
          class="btl-x"
          :aria-label="`移除 ${b}`"
          :data-testid="`${testid}-remove-${b}`"
          @click="remove(b)"
        >
          <X :size="12" aria-hidden="true" />
        </button>
      </span>
      <span v-if="list.length === 0" class="btl-none" :data-testid="`${testid}-none`">未设置</span>
    </div>
    <template v-if="!disabled">
      <div class="btl-actions">
        <Button type="button" :data-testid="`${testid}-toggle`" @click="open = !open">
          {{ open ? '收起' : '添加分支' }}
        </Button>
      </div>
      <div v-if="open" class="btl-panel">
        <BranchPicker v-if="props.options.length" v-model="list" :branches="props.options" />
        <div class="btl-extra" @keydown.enter.prevent="addExtra">
          <TextField v-model="extra" :label="`${label} 其他分支名`" placeholder="输入其他分支名" />
          <Button
            type="button"
            :data-testid="`${testid}-extra-add`"
            :disabled="!extra.trim()"
            @click="addExtra"
            >添加</Button
          >
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.btl {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.btl-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 22px;
  align-items: center;
}
.btl-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--ctl);
  font-size: var(--text-sub);
  line-height: 20px;
}
.btl-x {
  display: inline-flex;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--mute);
  cursor: pointer;
}
.btl-none {
  font-size: var(--text-sub);
  color: var(--mute);
}
.btl-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  border-radius: var(--r-ctl);
  border: 1px dashed var(--field-line);
}
.btl-extra {
  display: flex;
  gap: 8px;
  align-items: center;
}
.btl-extra > :first-child {
  flex: 1;
  min-width: 0;
}
.mono {
  font-family: var(--font-mono);
}
</style>
