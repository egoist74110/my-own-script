<script setup lang="ts">
interface NavItem {
  code: string
  label: string
  en: string
  /** 可用路由；未实现的能力为 null，并标注计划切片号。 */
  to: string | null
  slice: string | null
}

const items: NavItem[] = [
  { code: '01', label: '总览', en: 'OVERVIEW', to: '/', slice: null },
  { code: '02', label: '工单', en: 'WORK ITEMS', to: null, slice: 'S2' },
  { code: '03', label: '任务', en: 'TASKS', to: null, slice: 'S3' },
  { code: '04', label: 'AI 会话', en: 'SESSIONS', to: null, slice: 'S5' },
  { code: '05', label: 'MCP', en: '', to: null, slice: 'S6' },
  { code: '06', label: 'VPN', en: '', to: null, slice: 'S8' },
  { code: '07', label: '服务', en: 'SERVICES', to: null, slice: 'S7' },
  { code: '08', label: '设置', en: 'SETTINGS', to: null, slice: 'S1' },
]
</script>

<template>
  <nav aria-label="分区" class="flex flex-col gap-0.5">
    <template v-for="n in items" :key="n.code">
      <RouterLink
        v-if="n.to"
        :to="n.to"
        class="nav-item nav-item--on"
        active-class=""
        exact-active-class=""
        aria-current="page"
      >
        <span class="mono nav-code">{{ n.code }}</span
        >{{ n.label }} {{ n.en }}
        <span
          class="ml-auto h-3 w-[26px]"
          style="background: var(--accent-fill)"
          aria-hidden="true"
        ></span>
      </RouterLink>
      <span v-else class="nav-item nav-item--off" aria-disabled="true" :data-slice="n.slice">
        <span class="mono nav-code">{{ n.code }}</span
        >{{ n.label }} {{ n.en }}
        <span class="mono ml-auto border border-[var(--mute)] px-1.5 text-[10px]">{{
          n.slice
        }}</span>
      </span>
    </template>
  </nav>
</template>

<style scoped>
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 40px;
  padding: 0 10px;
  text-decoration: none;
  font-size: 15px;
  letter-spacing: 0.6px;
}
.nav-item--on {
  background: var(--ink);
  color: var(--inv);
  font-weight: 700;
}
.nav-item--off {
  color: var(--mute);
  font-weight: 500;
  cursor: not-allowed;
}
.nav-code {
  font-size: 11px;
  opacity: 0.7;
}
</style>
