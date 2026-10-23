<script setup lang="ts">
import type { Component } from 'vue'

/** 空状态：图标 + 标题 + 一句说明 + 动作（actions 插槽）。 */
defineProps<{ title: string; description?: string; icon?: Component; tone?: 'default' | 'error' }>()
</script>

<template>
  <div class="empty" :data-tone="tone ?? 'default'">
    <component
      :is="icon"
      v-if="icon"
      :size="40"
      :stroke-width="1.4"
      class="ico"
      aria-hidden="true"
    />
    <h2>{{ title }}</h2>
    <p v-if="description">{{ description }}</p>
    <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 32px;
  text-align: center;
}
.ico {
  color: var(--disabled);
}
.empty[data-tone='error'] .ico {
  color: var(--st-stopping-dot);
}
h2 {
  margin: 4px 0 0;
  font-size: var(--text-page);
  font-weight: 600;
}
p {
  margin: 0;
  color: var(--mute);
  max-width: 36ch;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}
</style>
