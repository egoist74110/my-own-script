<script setup lang="ts">
/** 输入框；label 作为不可见标签供读屏。 */
withDefaults(
  defineProps<{
    label: string
    placeholder?: string
    multiline?: boolean
    type?: 'text' | 'password'
    autocomplete?: string
    disabled?: boolean
  }>(),
  { placeholder: undefined, type: 'text', autocomplete: undefined },
)
const model = defineModel<string>({ default: '' })
</script>

<template>
  <label class="text-input cut-xs">
    <span class="sr-only">{{ label }}</span>
    <textarea v-if="multiline" v-model="model" rows="2" :placeholder="placeholder"></textarea>
    <input
      v-else
      v-model="model"
      :type="type"
      :placeholder="placeholder"
      :autocomplete="autocomplete"
      :disabled="disabled"
      :spellcheck="type === 'password' ? false : undefined"
    />
  </label>
</template>

<style scoped>
.text-input {
  display: flex;
  align-items: center;
  min-height: var(--target-min);
  padding: 0 10px;
  background: rgba(255, 255, 255, 0.75);
  box-shadow: inset 0 0 0 1px var(--line);
}
input,
textarea {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: 0;
  outline: none;
  font: inherit;
  color: var(--ink);
}
textarea {
  resize: none;
  line-height: 1.6;
  padding: 6px 0;
}
.text-input:focus-within {
  outline: 2px solid var(--warn);
  outline-offset: -2px;
}
</style>
