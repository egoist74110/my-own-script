<script setup lang="ts">
import { reactiveOmit } from '@vueuse/core'
import { SwitchRoot, SwitchThumb, useForwardPropsEmits } from 'reka-ui'
import type { SwitchRootEmits, SwitchRootProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<SwitchRootProps & { class?: HTMLAttributes['class'] }>()
const emits = defineEmits<SwitchRootEmits>()

const delegatedProps = reactiveOmit(props, 'class')
const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <SwitchRoot
    v-bind="forwarded"
    :class="
      cn(
        'peer inline-flex h-6 w-12 shrink-0 cursor-pointer items-center border border-[var(--ink)] bg-transparent p-0.5 transition-colors outline-none',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-fill)]',
        'data-[state=checked]:bg-[var(--orange)] disabled:cursor-not-allowed disabled:opacity-50',
        props.class,
      )
    "
  >
    <SwitchThumb
      class="pointer-events-none block h-4 w-4 bg-[var(--ink)] transition-transform data-[state=checked]:translate-x-6 data-[state=checked]:bg-[#111214]"
    />
  </SwitchRoot>
</template>
