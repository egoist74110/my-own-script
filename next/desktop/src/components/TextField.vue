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
  <label class="text-input field">
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
.field {
  display: flex;
  align-items: center;
  min-height: var(--ctl-h);
  padding: 0 8px;
  border-radius: var(--r-ctl);
  background: var(--bg-window);
  box-shadow: inset 0 0 0 1px var(--field-line);
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
input::placeholder,
textarea::placeholder {
  color: var(--mute);
}
textarea {
  resize: none;
  line-height: 1.6;
  padding: 4px 0;
}
.field:focus-within {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
}
input:focus-visible,
textarea:focus-visible {
  outline: none;
}
</style>
