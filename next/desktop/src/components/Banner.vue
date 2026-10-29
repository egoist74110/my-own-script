<script setup lang="ts">
import { computed, useAttrs } from 'vue'

/**
 * 提示横幅（info/warn/error）：贴在所属区域内，不遮挡、不拦截。
 * warn/error 默认 role=alert，info 默认 role=status；可由调用方覆盖。
 */
const props = withDefaults(defineProps<{ kind?: 'info' | 'warn' | 'error'; title?: string }>(), {
  kind: 'info',
  title: undefined,
})
const attrs = useAttrs()
const role = computed(
  () => (attrs.role as string | undefined) ?? (props.kind === 'info' ? 'status' : 'alert'),
)
defineOptions({ inheritAttrs: false })
</script>

<template>
  <div class="banner" v-bind="{ ...attrs, role }" :data-tone="kind">
    <div class="body">
      <strong v-if="title" class="title">{{ title }}</strong>
      <slot />
    </div>
    <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: var(--text-body);
  background: var(--bn-bg);
  color: var(--bn-fg);
  box-shadow: inset 0 0 0 1px var(--bn-line);
}
.banner[data-tone='info'] {
  --bn-bg: var(--bn-info-bg);
  --bn-line: var(--bn-info-line);
  --bn-fg: var(--bn-info-fg);
  --bn-title: var(--bn-info-fg);
}
.banner[data-tone='warn'] {
  --bn-bg: var(--bn-warn-bg);
  --bn-line: var(--bn-warn-line);
  --bn-fg: var(--bn-warn-fg);
  --bn-title: var(--bn-warn-fg);
}
.banner[data-tone='error'] {
  --bn-bg: var(--bn-error-bg);
  --bn-line: var(--bn-error-line);
  --bn-fg: var(--bn-error-fg);
  --bn-title: var(--bn-error-title);
}
.body {
  flex: 1 1 200px;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  overflow-wrap: anywhere;
}
/* 列表/段落等块级内容独占一行，不与前面的说明文字并排。 */
.body > :slotted(:is(ul, ol, p, div, dl)) {
  flex-basis: 100%;
}
.title {
  color: var(--bn-title);
  font-weight: 600;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
</style>
