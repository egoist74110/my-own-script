<script setup lang="ts">
/** 按钮：primary（墨色实底，深色为强调色）/ default / destructive（红字）/ plain；高度 28，圆角 6。 */
withDefaults(
  defineProps<{
    variant?: 'primary' | 'default' | 'destructive' | 'plain'
    type?: 'button' | 'submit'
  }>(),
  { variant: 'default', type: 'button' },
)
</script>

<template>
  <button :type="type" class="b-btn" :data-variant="variant">
    <slot />
  </button>
</template>

<style scoped>
.b-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: var(--ctl-h);
  min-width: var(--target-min);
  padding: 0 12px;
  border: 0;
  border-radius: var(--r-ctl);
  background: var(--ctl);
  color: var(--ink);
  font: inherit;
  font-size: var(--text-body);
  white-space: nowrap;
  cursor: pointer;
}
.b-btn:hover:not(:disabled) {
  filter: brightness(0.97);
}
.b-btn[data-variant='primary'] {
  background: var(--btn-primary-bg);
  color: var(--btn-primary-fg);
  font-weight: 600;
}
.b-btn[data-variant='destructive'] {
  color: var(--danger);
}
.b-btn[data-variant='plain'] {
  background: transparent;
  color: var(--link);
}
.b-btn:disabled {
  color: var(--disabled);
  cursor: not-allowed;
}
.b-btn[data-variant='primary']:disabled {
  background: var(--ctl);
  color: var(--disabled);
}
</style>
