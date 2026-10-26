<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, provide } from 'vue'
import Banner from '@/components/Banner.vue'
import McpAdoCard from './McpAdoCard.vue'
import McpFigmaCard from './McpFigmaCard.vue'
import McpLarkCard from './McpLarkCard.vue'
import { settingsContextKey } from './useSettings'
import { mcpContextKey, useMcp } from './useMcp'

const ctx = inject(settingsContextKey)!
const mcp = useMcp()
provide(mcpContextKey, mcp)

onMounted(() => {
  ctx.mcpTabActive.value = true
  ctx.aiTabActive.value = true
})

onUnmounted(() => {
  ctx.mcpTabActive.value = false
  ctx.aiTabActive.value = false
})

const snapshot = computed(() => mcp.snapshot.value)
const ado = computed(
  () =>
    snapshot.value?.ado ?? {
      allow_create_work_item: false,
      attachment_cache_mb: 500,
      attachment_max_mb: 25,
      query_max_items: 200,
    },
)
const lark = computed(() => snapshot.value?.lark)
const figma = computed(() => snapshot.value?.figma)
const runtime = computed(() => snapshot.value?.runtime)
const aiMcpSource = computed(() => ctx.ai.data.value?.analysis?.mcp_source ?? 'legacy')
</script>

<template>
  <div class="st-body" data-testid="mcp-tab">
    <Banner v-if="mcp.error.value" kind="error" data-testid="mcp-global-error">
      {{ mcp.error.value }}
    </Banner>

    <!-- 卡片 1: ADO 工单 MCP -->
    <McpAdoCard
      :ado="ado"
      :ai-mcp-source="aiMcpSource"
      :busy="ctx.busy.value"
      :writable="ctx.writable.value"
    />

    <!-- 卡片 2: 飞书 / Lark MCP -->
    <McpLarkCard
      :lark="lark"
      :runtime="runtime"
      :managed-node-version="snapshot?.managed_node_version"
      :node-min-version="snapshot?.node_min_version"
      :busy="ctx.busy.value"
      :writable="ctx.writable.value"
    />

    <!-- 卡片 3: Figma MCP -->
    <McpFigmaCard :figma="figma" :busy="ctx.busy.value" :writable="ctx.writable.value" />
  </div>
</template>
