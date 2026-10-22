<script setup lang="ts">
import { computed, inject } from 'vue'
import BlockTag from '@/components/BlockTag.vue'
import { settingsContextKey } from './useSettings'

const ctx = inject(settingsContextKey)!
const o = computed(() => ctx.overview.data.value ?? null)
</script>

<template>
  <div class="st-body" data-testid="general-tab">
    <p v-if="!o" class="st-note">读取中…</p>
    <template v-else>
      <section
        v-if="o.store_state !== 'ok'"
        class="st-box"
        data-tone="warn"
        role="alert"
        data-testid="general-store-error"
      >
        <strong class="st-warn">存储处于只读错误态</strong>
        <div>{{ o.store_error || '未提供原因' }}</div>
        <div class="st-note">
          不会自动覆盖或重置原文件；请检查数据目录中的 config.json 后重启应用。
        </div>
      </section>
      <dl class="st-kv">
        <dt class="lbl">数据目录</dt>
        <dd class="st-mono" data-testid="general-data-dir">{{ o.data_dir }}</dd>
        <dt class="lbl">旧配置目录</dt>
        <dd class="st-mono" data-testid="general-legacy-dir">{{ o.legacy_config_dir }}</dd>
        <dt class="lbl">应用版本</dt>
        <dd class="st-mono" data-testid="general-app-version">{{ o.app_version }}</dd>
        <dt class="lbl">Schema 版本</dt>
        <dd class="st-mono" data-testid="general-schema">{{ o.schema_version }}</dd>
        <dt class="lbl">Revision</dt>
        <dd class="st-mono">{{ o.revision }}</dd>
        <dt class="lbl">存储状态</dt>
        <dd data-testid="general-store-state">
          <BlockTag :tone="o.store_state === 'ok' ? 'acc' : 'warn'">{{
            o.store_state === 'ok' ? '正常' : '只读错误'
          }}</BlockTag>
        </dd>
      </dl>
    </template>
  </div>
</template>
