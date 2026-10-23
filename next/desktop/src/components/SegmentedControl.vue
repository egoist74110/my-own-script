<script setup lang="ts">
import type { Component } from 'vue'
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { tabTriggerId } from './tabs'

export interface SegmentItem {
  value: string
  label: string
  count?: number | string
  /** 竖向列表用：彩色小图标（lucide 组件）与其颜色。 */
  icon?: Component
  iconColor?: string
}
/**
 * 分段控件（Reka Tabs：方向键切换、roving focus）。横向为分段/页签条，竖向为设置分区列表。
 * 页签与真实内容的可访问关联有三种用法：
 * - 传默认插槽（`#default="{ item }"`）：当前页签的面板（tabpanel）显示插槽内容，其余面板 hidden；
 * - 传 `panelId`（筛选型）：不渲染内部面板，各 trigger 的 `aria-controls` 指向页面上承载列表的
 *   容器；该容器须设 `role="tabpanel"`、`id=panelId`、`aria-labelledby=tabTriggerId(panelId, 当前值)`；
 * - 都不传：面板为空且 hidden（仅保证关联 id 有效；页面不应再这样用）。
 */
const props = withDefaults(
  defineProps<{
    items: SegmentItem[]
    label: string
    panelId?: string
    orientation?: 'horizontal' | 'vertical'
    /** 横向时让各段等宽铺满。 */
    fill?: boolean
  }>(),
  { orientation: 'horizontal', panelId: undefined },
)
// 子元素自带的 id / aria-controls 优先于 Reka 生成的值（panelId 用法需要指向页面容器）
const triggerAttrs = (value: string) =>
  props.panelId ? { id: tabTriggerId(props.panelId, value), 'aria-controls': props.panelId } : {}
const model = defineModel<string>({ required: true })
</script>

<template>
  <TabsRoot
    v-model="model"
    :orientation="orientation"
    class="seg-root"
    :data-orientation="orientation"
  >
    <TabsList :aria-label="label" class="seg" :data-fill="fill ? 'true' : undefined">
      <TabsTrigger v-for="t in items" :key="t.value" :value="t.value" as-child>
        <button type="button" class="seg-btn" v-bind="triggerAttrs(t.value)">
          <component
            :is="t.icon"
            v-if="t.icon"
            :size="15"
            class="ico"
            :style="t.iconColor ? { color: t.iconColor } : undefined"
            aria-hidden="true"
          />
          <span class="txt">{{ t.label }}</span>
          <span v-if="t.count !== undefined" class="count">{{ ' ' + t.count }}</span>
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
.seg {
  display: flex;
  gap: 2px;
  padding: 2px;
  background: var(--ctl);
  border-radius: var(--r-row);
  width: max-content;
  max-width: 100%;
}
.seg[data-fill='true'] {
  width: 100%;
}
.seg[data-fill='true'] .seg-btn {
  flex: 1;
}
.seg-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 24px;
  min-width: var(--target-min);
  padding: 0 10px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--ink);
  font: inherit;
  font-size: 12.5px;
  white-space: nowrap;
  cursor: pointer;
}
.seg-btn:hover {
  background: color-mix(in srgb, var(--ink) 6%, transparent);
}
.seg-btn[data-state='active'] {
  background: var(--ctl-selected);
  font-weight: 600;
  box-shadow:
    0 0 0 0.5px rgba(0, 0, 0, 0.12),
    0 1px 2px rgba(0, 0, 0, 0.08);
}
.count {
  color: var(--mute-tint);
  font-size: 11.5px;
  font-weight: 400;
}
.tab-panel[hidden] {
  display: none;
}

/* 竖向：设置分区列表 */
.seg-root[data-orientation='vertical'] .seg {
  flex-direction: column;
  gap: 1px;
  padding: 0;
  width: auto;
  background: transparent;
  border-radius: 0;
}
.seg-root[data-orientation='vertical'] .seg-btn {
  justify-content: flex-start;
  gap: 8px;
  min-height: var(--ctl-h);
  padding: 0 8px;
  border-radius: var(--r-ctl);
  font-size: var(--text-body);
}
.seg-root[data-orientation='vertical'] .txt {
  flex: 1;
  text-align: left;
}
.seg-root[data-orientation='vertical'] .seg-btn[data-state='active'] {
  background: var(--sidebar-sel);
  box-shadow: none;
}
.seg-root[data-orientation='vertical'] .seg-btn[data-state='active'] .count {
  color: var(--ink);
}
</style>
