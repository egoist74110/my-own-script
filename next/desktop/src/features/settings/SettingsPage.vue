<script setup lang="ts">
import { computed, nextTick, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Cable,
  Cpu,
  Database,
  Download,
  FolderGit2,
  KeyRound,
  Send,
  Server,
  SlidersHorizontal,
} from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import AdoTab from './AdoTab.vue'
import AiCliTab from './AiCliTab.vue'
import CredentialsTab from './CredentialsTab.vue'
import GeneralTab from './GeneralTab.vue'
import ImportTab from './ImportTab.vue'
import LocalReposTab from './LocalReposTab.vue'
import McpTab from './McpTab.vue'
import ServicesTab from './ServicesTab.vue'
import TelegramTab from './TelegramTab.vue'
import { SETTINGS_VPN_ANCHOR, tabFromParam } from './tabs'
import { settingsContextKey, useSettingsContext } from './useSettings'
import './settings.css'

const ctx = useSettingsContext()
provide(settingsContextKey, ctx)

const route = useRoute()
const router = useRouter()

// 当前分区以 URL 为准（/settings/:tab）；/settings 无参数时用本地默认：先“导入”，
// 导入已处理过则落在 ADO 连接（用户手动选过就不再干预）。
const fallbackTab = ref('import')
let picked = false
const routeTab = computed(() => tabFromParam(route.params.tab))
const tab = computed(() => routeTab.value ?? fallbackTab.value)
function onTab(v: string) {
  picked = true
  fallbackTab.value = v
  const target = `/settings/${v}`
  if (route.path !== target) void router.push(target)
}
watch(
  () => ctx.overview.data.value?.import?.state,
  (s) => {
    if (!picked && !routeTab.value && (s === 'completed' || s === 'declined'))
      fallbackTab.value = 'ado'
  },
  { once: true },
)

// /settings/vpn：服务分区渲染后把 VPN 卡片滚到可见处
watch(
  () => route.params.tab,
  async (p) => {
    if (p !== 'vpn') return
    await nextTick()
    document.getElementById(SETTINGS_VPN_ANCHOR)?.scrollIntoView?.({ block: 'start' })
  },
  { immediate: true, flush: 'post' },
)

const tabs = computed(() => [
  { value: 'import', label: '导入', icon: Download, iconColor: '#0a63d6' },
  {
    value: 'ado',
    label: 'ADO 连接',
    count: ctx.ado.data.value?.libraries.length,
    icon: Database,
    iconColor: '#1f9d45',
  },
  {
    value: 'repos',
    label: '本地仓库',
    count: ctx.ado.data.value?.local_repos.length,
    icon: FolderGit2,
    iconColor: '#8e44c8',
  },
  {
    value: 'credentials',
    label: '凭据',
    count: ctx.credentials.data.value?.length,
    icon: KeyRound,
    iconColor: '#e07b00',
  },
  {
    value: 'telegram',
    label: 'Telegram',
    icon: Send,
    iconColor: '#229ed9',
  },
  {
    value: 'ai',
    label: 'AI CLI',
    count: ctx.ai.data.value?.profiles.length,
    icon: Cpu,
    iconColor: '#c15f3c',
  },
  {
    value: 'mcp',
    label: 'MCP',
    icon: Cable,
    iconColor: '#0a63d6',
  },
  {
    value: 'services',
    label: '服务',
    icon: Server,
    iconColor: '#007aff',
  },
  { value: 'general', label: '通用', icon: SlidersHorizontal, iconColor: '#8e8e93' },
])
const o = computed(() => ctx.overview.data.value ?? null)
const summary = computed(() =>
  o.value ? `修订 ${o.value.revision}，结构 v${o.value.schema_version}` : '读取中',
)

const ASIDE: Record<string, string> = {
  import: '只导入一次：不会持续同步，也不会改动旧配置；旧钥匙串里的条目只读。',
  ado: '连接的 ADO 服务器与项目。PAT 在 library 详情里录入或更换。',
  repos: '任务构建用的本地仓库。路径只保存为文本，不会被读取。',
  credentials: '应用保存的全部凭据一览。',
  telegram: '用 Telegram 远程触发任务：设置机器人、谁能用它，以及运行结果的通知。',
  ai: '管理 AI 命令行工具，以及新会话和工单分析使用的默认权限与模型。',
  mcp: '给 Claude Code、Codex、Antigravity 共用的工具服务：ADO 工单、飞书、Figma。',
  services: '本机的 VPN、code-server 和 cloudflared 隧道。网络地址只读显示。',
  general: '数据目录、旧配置目录和版本信息，均为只读。',
}
const noticeKind = computed(() => {
  const k = ctx.notice.value?.kind
  return k === 'warn' ? 'warn' : k === 'error' ? 'error' : 'info'
})
</script>

<template>
  <div class="st">
    <header class="topbar" data-tauri-drag-region>
      <h1>设置</h1>
      <span class="sum" data-testid="settings-summary">{{ summary }}</span>
    </header>

    <div class="banners">
      <Banner
        v-if="o && o.store_state !== 'ok'"
        kind="error"
        role="alert"
        title="存储处于只读错误态，所有写操作已停用"
        data-testid="store-error"
      >
        <span>{{ o.store_error || '未提供原因' }}</span>
        <span class="st-mono">{{ o.data_dir }}</span>
      </Banner>
      <Banner
        v-if="ctx.loadError.value"
        kind="error"
        role="alert"
        :title="ctx.loadError.value"
        data-testid="load-error"
      />
      <Banner
        v-if="ctx.notice.value"
        :kind="noticeKind"
        :role="ctx.notice.value.kind === 'ok' ? 'status' : 'alert'"
        :data-kind="ctx.notice.value.kind"
        data-testid="settings-notice"
      >
        <span>{{ ctx.notice.value.text }}</span>
        <ul v-if="ctx.notice.value.tasks?.length" class="st-list" data-testid="notice-tasks">
          <li v-for="t in ctx.notice.value.tasks" :key="t">{{ t }}</li>
        </ul>
        <ul v-if="ctx.notice.value.warnings?.length" class="st-list" data-testid="notice-warnings">
          <li v-for="w in ctx.notice.value.warnings" :key="w">{{ w }}</li>
        </ul>
        <template #actions>
          <Button type="button" @click="ctx.clearNotice()">关闭提示</Button>
        </template>
      </Banner>
    </div>

    <section aria-label="设置内容" class="panel">
      <SegmentedControl
        :model-value="tab"
        :items="tabs"
        label="设置分区"
        orientation="vertical"
        class="settings-tabs"
        @update:model-value="onTab"
      >
        <template #default="{ item }">
          <div class="st-page">
            <h2 class="st-title">{{ item.label }}</h2>
            <p v-if="ASIDE[item.value]" class="st-intro">{{ ASIDE[item.value] }}</p>
            <ImportTab v-if="item.value === 'import'" />
            <AdoTab v-else-if="item.value === 'ado'" />
            <LocalReposTab v-else-if="item.value === 'repos'" />
            <CredentialsTab v-else-if="item.value === 'credentials'" />
            <TelegramTab v-else-if="item.value === 'telegram'" />
            <AiCliTab v-else-if="item.value === 'ai'" />
            <McpTab v-else-if="item.value === 'mcp'" />
            <ServicesTab v-else-if="item.value === 'services'" />
            <GeneralTab v-else />
          </div>
        </template>
      </SegmentedControl>
    </section>
  </div>
</template>

<style scoped>
.st {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.topbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  height: var(--topbar-h);
  padding: 0 12px 0 16px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--line);
}
h1 {
  margin: 0;
  font-size: var(--text-page);
  font-weight: 700;
}
.sum {
  font-size: var(--text-sub);
  color: var(--mute);
}
.grow {
  flex: 1;
}
.banners {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 12px 0;
}
.banners:empty {
  display: none;
}
.panel {
  flex: 1;
  min-height: 0;
  display: flex;
  margin-top: 8px;
}
.settings-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
}
/* 选择器需高于 SegmentedControl 的竖向规则（.seg-root[data-orientation] .seg）；用子代选择器，避免波及页内嵌套的分段控件 */
.panel .settings-tabs[data-orientation='vertical'] > :deep(.seg) {
  flex: none;
  flex-grow: 0;
  width: 220px;
  box-sizing: border-box;
  padding: 12px 10px;
  align-self: stretch;
  align-content: flex-start;
  border-right: 1px solid var(--line);
  background: var(--bg-inspector);
}
.settings-tabs > :deep(.tab-panel) {
  flex: 1 1 0;
  min-width: 0;
  /* 整页不出横向滚动；宽表格在自己的容器里滚 */
  overflow-x: hidden;
  overflow-y: auto;
  padding: 24px 28px 40px;
  box-sizing: border-box;
  background: var(--bg-settings);
}
.settings-tabs > :deep(.tab-panel[hidden]) {
  display: none;
}
</style>
