<script setup lang="ts">
import { useClock } from '@/lib/clock'

const props = defineProps<{ now?: () => Date }>()
const clock = useClock(props.now)
</script>

<template>
  <div class="flex flex-col items-end gap-1.5" data-testid="clock">
    <div class="flex items-start gap-1.5">
      <span class="text-[76px] leading-none font-light tracking-[-2px]" data-testid="clock-hm">{{
        clock.hm
      }}</span>
      <span class="mono mt-2 text-xs text-[var(--mute)]" data-testid="clock-sec">{{
        clock.seconds
      }}</span>
    </div>
    <span class="text-[13px] font-semibold tracking-[2.4px]" data-testid="clock-date">{{
      clock.date
    }}</span>
    <span class="text-[10px] tracking-[1px] text-[var(--mute)]">
      <span class="sq" style="width: 4px; height: 4px"></span> LOCAL · 127.0.0.1 · TOKEN SESSION
    </span>
  </div>
</template>
