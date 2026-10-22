<script setup lang="ts">
import { TabsList, TabsRoot, TabsTrigger } from 'reka-ui'

export interface TabItem {
  value: string
  label: string
  count?: number | string
}

/** 斜切 Tabs（Reka Tabs：方向键切换、roving focus）。内容区由页面按 modelValue 自行渲染。 */
defineProps<{ items: TabItem[]; label: string }>()
const model = defineModel<string>({ required: true })
</script>

<template>
  <TabsRoot v-model="model" class="tabs-root">
    <TabsList :aria-label="label" class="tabs">
      <TabsTrigger v-for="t in items" :key="t.value" :value="t.value" class="tab skew">
        {{ t.label }}
        <span v-if="t.count !== undefined" class="ox count">{{ t.count }}</span>
      </TabsTrigger>
    </TabsList>
  </TabsRoot>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: 2px;
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: var(--target-min);
  padding: 0 14px;
  border: 0;
  background: transparent;
  color: #2a2e36;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.tab:hover {
  background: var(--soft);
}
.tab[data-state='active'] {
  background: var(--ink);
  color: #fff;
}
.count {
  opacity: 0.75;
}
</style>
