<script setup lang="ts">
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'

export interface TabItem {
  value: string
  label: string
  count?: number | string
}

/**
 * 斜切 Tabs（Reka Tabs：方向键切换、roving focus）。
 * 每个页签都有对应的 tabpanel（aria-controls / aria-labelledby 互相关联）：
 * - 传默认插槽（`#default="{ item }"`）时，当前页签的面板显示插槽内容，其余面板 hidden；
 * - 不传插槽时面板为空且始终 hidden（内容由页面按 modelValue 自行渲染），关联 id 依然有效。
 */
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
    <TabsContent
      v-for="t in items"
      :key="t.value"
      :value="t.value"
      force-mount
      :hidden="!$slots.default || model !== t.value"
      :tabindex="$slots.default ? 0 : -1"
      class="tab-panel"
      data-testid="tab-panel"
    >
      <slot v-if="model === t.value" :item="t" />
    </TabsContent>
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
.tab-panel[hidden] {
  display: none;
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
