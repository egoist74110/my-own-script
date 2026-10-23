<script setup lang="ts">
import { computed, provide, ref, watch } from 'vue'
import { Database, Download, FolderGit2, KeyRound, SlidersHorizontal } from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import SegmentedControl from '@/components/SegmentedControl.vue'
import AdoTab from './AdoTab.vue'
import CredentialsTab from './CredentialsTab.vue'
import GeneralTab from './GeneralTab.vue'
import ImportTab from './ImportTab.vue'
import LocalReposTab from './LocalReposTab.vue'
import { settingsContextKey, useSettingsContext } from './useSettings'
import './settings.css'

const ctx = useSettingsContext()
provide(settingsContextKey, ctx)

const tab = ref('import')
let picked = false
function onTab(v: string) {
  picked = true
  tab.value = v
}
// 首次载入：已处理过导入（完成/跳过）时直接落在 ADO 连接；用户手动切过页签则不再干预
watch(
  () => ctx.overview.data.value?.import.state,
  (s) => {
    if (!picked && (s === 'completed' || s === 'declined')) tab.value = 'ado'
  },
  { once: true },
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
  { value: 'general', label: '常规', icon: SlidersHorizontal, iconColor: '#8e8e93' },
])
const o = computed(() => ctx.overview.data.value ?? null)
const summary = computed(() =>
  o.value ? `revision ${o.value.revision} · schema v${o.value.schema_version}` : '读取中',
)

const ASIDE: Record<string, string> = {
  import: '导入只发生一次：不同步、不回写旧配置；旧 Keychain 条目只读。',
  credentials: '凭据值永远不会显示在界面上，这里只有存在与否、来源和状态。',
  general: '数据目录、旧配置目录与版本信息均为只读。',
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
          <p v-if="ASIDE[item.value]" class="st-note intro">{{ ASIDE[item.value] }}</p>
          <ImportTab v-if="item.value === 'import'" />
          <AdoTab v-else-if="item.value === 'ado'" />
          <LocalReposTab v-else-if="item.value === 'repos'" />
          <CredentialsTab v-else-if="item.value === 'credentials'" />
          <GeneralTab v-else />
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
/* 选择器需高于 SegmentedControl 的竖向规则（.seg-root[data-orientation] .seg） */
.panel .settings-tabs[data-orientation='vertical'] :deep(.seg) {
  flex: none;
  flex-grow: 0;
  width: 220px;
  box-sizing: border-box;
  padding: 12px 10px;
  align-self: stretch;
  align-content: flex-start;
  border-right: 1px solid var(--line);
  background: var(--bg-window);
}
.settings-tabs :deep(.tab-panel) {
  flex: 1 1 0;
  min-width: 0;
  overflow: auto;
  background: var(--bg-settings);
}
.settings-tabs :deep(.tab-panel[hidden]) {
  display: none;
}
.intro {
  padding: 16px 28px 0;
}
</style>
