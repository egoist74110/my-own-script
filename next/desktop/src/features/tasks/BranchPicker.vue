<script setup lang="ts">
import { computed, ref } from 'vue'
import Tag from '@/components/Tag.vue'
import TextField from '@/components/TextField.vue'

/**
 * 远端分支多选：带搜索过滤，默认分支排在前面并打标。
 * disabled 里的分支已经在配置里，显示为已添加、不能再选。
 */
const props = defineProps<{
  branches: string[]
  defaultBranch?: string | null
  disabled?: string[]
}>()
const selected = defineModel<string[]>({ default: () => [] })

const keyword = ref('')
const shown = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  return k ? props.branches.filter((b) => b.toLowerCase().includes(k)) : props.branches
})

function isDisabled(b: string): boolean {
  return (props.disabled ?? []).includes(b)
}
function toggle(b: string, on: boolean) {
  if (isDisabled(b)) return
  const rest = selected.value.filter((x) => x !== b)
  selected.value = on ? [...rest, b] : rest
}
</script>

<template>
  <div class="bp" data-testid="branch-picker">
    <TextField v-model="keyword" label="搜索分支" placeholder="搜索分支" />
    <p class="bp-count">
      共 {{ branches.length }} 个分支，已选 {{ selected.length }} 个
      <template v-if="keyword.trim()">，当前筛出 {{ shown.length }} 个</template>
    </p>
    <ul class="bp-list">
      <li v-for="b in shown" :key="b">
        <label class="bp-row" :class="{ off: isDisabled(b) }">
          <input
            type="checkbox"
            :checked="isDisabled(b) || selected.includes(b)"
            :disabled="isDisabled(b)"
            :data-testid="`branch-pick-${b}`"
            @change="toggle(b, ($event.target as HTMLInputElement).checked)"
          />
          <span class="bp-name mono">{{ b }}</span>
          <Tag v-if="b === defaultBranch">默认分支</Tag>
          <Tag v-if="isDisabled(b)">已添加</Tag>
        </label>
      </li>
      <li v-if="shown.length === 0" class="bp-none">没有匹配的分支。</li>
    </ul>
  </div>
</template>

<style scoped>
.bp {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bp-count {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.bp-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
}
.bp-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  cursor: pointer;
}
.bp-row:hover {
  background: var(--hover);
}
.bp-row.off {
  color: var(--mute);
  cursor: default;
}
.bp-name {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.bp-none {
  padding: 8px;
  font-size: var(--text-sub);
  color: var(--mute);
}
.mono {
  font-family: var(--font-mono);
}
</style>
