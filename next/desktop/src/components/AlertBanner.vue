<script setup lang="ts">
import { computed } from 'vue'

/** 主区顶部黑色告警横幅。不遮罩、不拦截点击。 */
const props = defineProps<{ reason: string | null }>()
const text = computed(() => props.reason?.trim() || '后端报告告警（未提供原因）')
</script>

<template>
  <div role="alert" class="banner cut anim-slidein" data-testid="alert-banner">
    <span class="stripe" aria-hidden="true"></span>
    <span class="tag ox">WARNING</span>
    <span class="reason" data-testid="alert-reason">{{ text }}</span>
    <span class="grow"></span>
    <slot />
  </div>
</template>

<style scoped>
.banner {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  padding: 10px 14px 10px 22px;
  background: var(--ink);
  color: #f2f0eb;
  overflow: hidden;
}
.stripe {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  background-image: repeating-linear-gradient(-45deg, #ff6a00 0 6px, #14161a 6px 12px);
}
.tag {
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 2px;
  color: #ff6a00;
}
.reason {
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.grow {
  flex: 1;
}
</style>
