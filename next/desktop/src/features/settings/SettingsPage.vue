<script setup lang="ts">
import { computed, provide, ref, watch } from 'vue'
import AppTabs from '@/components/AppTabs.vue'
import BlockTag from '@/components/BlockTag.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import InspectorPanel from '@/components/InspectorPanel.vue'
import AdoTab from './AdoTab.vue'
import CredentialsTab from './CredentialsTab.vue'
import GeneralTab from './GeneralTab.vue'
import ImportTab from './ImportTab.vue'
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
  { value: 'import', label: '导入' },
  { value: 'ado', label: 'ADO 连接', count: ctx.ado.data.value?.libraries.length },
  { value: 'credentials', label: '凭据', count: ctx.credentials.data.value?.length },
  { value: 'general', label: '常规' },
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
</script>

<template>
  <GlassPanel class="toolbar">
    <div class="title">
      <BlockTag>08</BlockTag>
      <h1>设置</h1>
      <span class="lbl" data-testid="settings-summary">{{ summary }}</span>
    </div>
  </GlassPanel>

  <section
    v-if="o && o.store_state !== 'ok'"
    class="store-error"
    role="alert"
    data-testid="store-error"
  >
    <strong>存储处于只读错误态，所有写操作已停用</strong>
    <span>{{ o.store_error || '未提供原因' }}</span>
    <span class="st-mono">{{ o.data_dir }}</span>
  </section>
  <section v-if="ctx.loadError.value" class="store-error" role="alert" data-testid="load-error">
    <strong>{{ ctx.loadError.value }}</strong>
  </section>
  <section
    v-if="ctx.notice.value"
    class="notice"
    :data-kind="ctx.notice.value.kind"
    :role="ctx.notice.value.kind === 'ok' ? 'status' : 'alert'"
    data-testid="settings-notice"
  >
    <span>{{ ctx.notice.value.text }}</span>
    <ul v-if="ctx.notice.value.tasks?.length" class="st-list" data-testid="notice-tasks">
      <li v-for="t in ctx.notice.value.tasks" :key="t">{{ t }}</li>
    </ul>
    <ul v-if="ctx.notice.value.warnings?.length" class="st-list" data-testid="notice-warnings">
      <li v-for="w in ctx.notice.value.warnings" :key="w">{{ w }}</li>
    </ul>
    <button type="button" class="close" @click="ctx.clearNotice()">关闭提示</button>
  </section>

  <GlassPanel as="section" aria-label="设置内容" class="panel">
    <AppTabs
      :model-value="tab"
      :items="tabs"
      label="设置分区"
      class="settings-tabs"
      @update:model-value="onTab"
    >
      <template #default="{ item }">
        <ImportTab v-if="item.value === 'import'" />
        <AdoTab v-else-if="item.value === 'ado'" />
        <CredentialsTab v-else-if="item.value === 'credentials'" />
        <GeneralTab v-else />
      </template>
    </AppTabs>
  </GlassPanel>

  <InspectorPanel v-if="tab !== 'ado'" label="说明">
    <div class="st-inspector">
      <p class="st-note">{{ ASIDE[tab] }}</p>
    </div>
  </InspectorPanel>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  padding: 8px 14px;
  min-height: 52px;
}
.title {
  display: flex;
  align-items: center;
  gap: 10px;
}
h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}
.panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.settings-tabs {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.settings-tabs :deep(.tab-panel) {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.settings-tabs :deep(.tabs) {
  padding: 8px 14px 0;
  border-bottom: 1px solid var(--line);
}
.store-error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--ink);
  color: #f2f0eb;
  font-size: 12.5px;
}
.notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  font-size: 12.5px;
  background: rgba(255, 255, 255, 0.8);
  box-shadow: inset 3px 0 0 var(--ink);
}
.notice[data-kind='warn'],
.notice[data-kind='error'] {
  background: rgba(255, 106, 0, 0.12);
  box-shadow: inset 3px 0 0 var(--warn);
}
.notice .close {
  margin-left: auto;
  min-height: var(--target-min);
  padding: 0 10px;
  border: 0;
  background: var(--soft);
  font: inherit;
  cursor: pointer;
}
</style>
