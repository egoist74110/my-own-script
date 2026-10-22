<script setup lang="ts">
/** 32x32 图标按钮；必须提供 label（渲染为 aria-label）。 */
defineProps<{ label: string; pressed?: boolean; expanded?: boolean }>()
</script>

<template>
  <button
    type="button"
    class="icon-btn"
    :aria-label="label"
    :aria-pressed="pressed"
    :aria-expanded="expanded"
  >
    <slot />
  </button>
</template>

<style scoped>
.icon-btn {
  display: grid;
  place-items: center;
  width: var(--target-min);
  height: var(--target-min);
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--mute);
  cursor: pointer;
}
.icon-btn:hover {
  background: rgba(20, 22, 26, 0.07);
  color: var(--ink);
}
</style>
