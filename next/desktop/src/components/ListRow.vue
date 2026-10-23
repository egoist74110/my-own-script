<script setup lang="ts">
/**
 * 两行列表行：标题 13/600 + 右侧日期；默认插槽为次行。圆点颜色由 dot 给出（CSS 颜色值）。
 * 状态：悬停 / 选中且列表聚焦（强调底）/ 选中未聚焦（灰底）。聚焦与否由容器 `.b-list:focus-within`
 * 区分（见 design/ui.css），所以一组行必须放在带 `b-list` 类的容器里。
 */
defineProps<{ title: string; meta?: string; dot?: string; selected?: boolean }>()
</script>

<template>
  <button
    type="button"
    class="b-row"
    :aria-current="selected ? 'true' : undefined"
    :data-selected="selected ? 'true' : 'false'"
  >
    <span v-if="dot" class="b-row-dot" :style="{ background: dot }" aria-hidden="true"></span>
    <span class="b-row-l1">
      <span class="b-row-title">{{ title }}</span>
      <span v-if="meta" class="b-row-meta">{{ meta }}</span>
    </span>
    <span class="b-row-l2"><slot /></span>
  </button>
</template>
