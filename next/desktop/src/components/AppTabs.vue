<script setup lang="ts">
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { tabTriggerId } from './tabs'

export interface TabItem {
  value: string
  label: string
  count?: number | string
}

/**
 * 斜切 Tabs（Reka Tabs：方向键切换、roving focus）。
 * 页签与真实内容的可访问关联有三种用法：
 * - 传默认插槽（`#default="{ item }"`）：当前页签的面板（tabpanel）显示插槽内容，其余面板 hidden；
 * - 传 `panelId`（筛选型）：不渲染内部面板，各 trigger 的 `aria-controls` 指向页面上承载列表的
 *   容器；该容器须设 `role="tabpanel"`、`id=panelId`、`aria-labelledby=tabTriggerId(panelId, 当前值)`；
 * - 都不传：沿用旧行为，面板为空且 hidden（仅保证关联 id 有效；页面不应再这样用）。
 */
const props = defineProps<{ items: TabItem[]; label: string; panelId?: string }>()
// 子元素自带的 id / aria-controls 优先于 Reka 生成的值（panelId 用法需要指向页面容器）
const triggerAttrs = (value: string) =>
  props.panelId ? { id: tabTriggerId(props.panelId, value), 'aria-controls': props.panelId } : {}
const model = defineModel<string>({ required: true })
</script>

<template>
  <TabsRoot v-model="model" class="tabs-root">
    <TabsList :aria-label="label" class="tabs">
      <TabsTrigger v-for="t in items" :key="t.value" :value="t.value" as-child>
        <button type="button" class="tab skew" v-bind="triggerAttrs(t.value)">
          {{ t.label }}
          <span v-if="t.count !== undefined" class="ox count">{{ t.count }}</span>
        </button>
      </TabsTrigger>
    </TabsList>
    <template v-if="!panelId">
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
    </template>
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
