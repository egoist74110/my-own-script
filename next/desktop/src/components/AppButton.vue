<script setup lang="ts">
/** 按钮：primary 黑底 / accent 青柠底 / ghost；高度 >= 32px；6px 切角。 */
withDefaults(
  defineProps<{ variant?: 'primary' | 'accent' | 'ghost'; type?: 'button' | 'submit' }>(),
  { variant: 'primary', type: 'button' },
)
</script>

<template>
  <button :type="type" class="app-btn cut-xs" :data-variant="variant">
    <slot />
  </button>
</template>

<style scoped>
.app-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: var(--target-min);
  padding: 0 12px;
  border: 0;
  cursor: pointer;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
}
.app-btn[data-variant='primary'] {
  background: var(--ink);
  color: #fff;
}
.app-btn[data-variant='accent'] {
  background: var(--acc);
  color: var(--ink);
}
.app-btn[data-variant='ghost'] {
  background: var(--soft);
  color: var(--ink);
}
.app-btn:hover {
  filter: brightness(1.08);
}
.app-btn[data-variant='ghost']:hover {
  background: rgba(20, 22, 26, 0.1);
  filter: none;
}
</style>
