<script setup lang="ts">
/** 纯色面（无玻璃、无切角）。surface 决定底色令牌。 */
withDefaults(
  defineProps<{
    as?: string
    surface?: 'window' | 'sidebar' | 'list' | 'inspector' | 'group' | 'settings'
  }>(),
  { as: 'div', surface: 'window' },
)
</script>

<template>
  <component :is="as" class="pane" :data-surface="surface">
    <slot />
  </component>
</template>

<style scoped>
.pane {
  background: var(--bg-window);
  min-width: 0;
}
.pane[data-surface='sidebar'] {
  background: var(--bg-sidebar);
}
.pane[data-surface='list'] {
  background: var(--bg-list);
}
.pane[data-surface='inspector'] {
  background: var(--bg-inspector);
}
.pane[data-surface='settings'] {
  background: var(--bg-settings);
}
.pane[data-surface='group'] {
  background: var(--bg-group);
  border-radius: var(--r-group);
  box-shadow: 0 0 0 0.5px var(--line);
}
</style>
