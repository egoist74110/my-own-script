<script setup lang="ts">
/** 玻璃面板。cut：lg = 12px 切角（面板），sm = 6px（小件），none = 直角。 */
withDefaults(defineProps<{ as?: string; cut?: 'lg' | 'sm' | 'none' }>(), {
  as: 'div',
  cut: 'lg',
})
</script>

<template>
  <component
    :is="as"
    class="glass"
    :class="cut === 'lg' ? 'cut' : cut === 'sm' ? 'cut-xs' : ''"
    :data-cut="cut"
  >
    <slot />
  </component>
</template>
