<script setup lang="ts">
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'

/** 确认单：Reka Dialog，从顶栏下落；焦点陷阱，Esc 关闭。动作放 actions 插槽。 */
defineProps<{ title: string; description?: string; wide?: boolean }>()
const open = defineModel<boolean>('open', { default: false })
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="sheet-overlay" />
      <DialogContent class="sheet" :data-wide="wide ? 'true' : undefined" data-testid="sheet">
        <DialogTitle class="sheet-title">{{ title }}</DialogTitle>
        <DialogDescription v-if="description" class="sheet-desc">{{
          description
        }}</DialogDescription>
        <DialogDescription v-else class="sr-only">{{ title }}</DialogDescription>
        <div class="sheet-body"><slot /></div>
        <div v-if="$slots.actions" class="sheet-actions"><slot name="actions" /></div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style>
.sheet-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(0, 0, 0, 0.16);
}
.sheet {
  position: fixed;
  z-index: 41;
  top: var(--topbar-h);
  left: 50%;
  translate: -50% 0;
  width: min(440px, calc(100vw - 32px));
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 16px 12px;
  border-radius: 0 0 var(--r-group) var(--r-group);
  background: var(--bg-window);
  color: var(--ink);
  box-shadow:
    0 0 0 0.5px var(--line),
    0 12px 32px rgba(0, 0, 0, 0.22);
}
.sheet[data-wide='true'] {
  width: min(680px, calc(100vw - 32px));
}
.sheet[data-state='open'] {
  animation: sheet-in 0.18s ease-out both;
}
.sheet[data-state='closed'] {
  animation: sheet-out 0.14s ease-in both;
}
.sheet-title {
  margin: 0;
  font-size: var(--text-page);
  font-weight: 700;
}
.sheet-desc {
  margin: 0;
  color: var(--mute);
}
.sheet-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
</style>
