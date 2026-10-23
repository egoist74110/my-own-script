<script setup lang="ts">
/** 工具栏按钮：无底色，按下态；必须提供 label（渲染为 aria-label）。 */
defineProps<{ label: string; pressed?: boolean; expanded?: boolean }>()
</script>

<template>
  <button
    type="button"
    class="tb"
    :aria-label="label"
    :aria-pressed="pressed"
    :aria-expanded="expanded"
  >
    <slot />
  </button>
</template>

<style scoped>
.tb {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: var(--target-min);
  height: var(--ctl-h);
  padding: 0;
  border: 0;
  border-radius: var(--r-ctl);
  background: transparent;
  color: var(--mute);
  font: inherit;
  cursor: pointer;
}
.tb:hover {
  background: var(--hover);
  color: var(--ink);
}
.tb[aria-pressed='true'] {
  background: var(--toolbar-pressed);
  color: var(--ink);
}
</style>
