<script setup lang="ts">
import { computed, inject } from 'vue'
import Tag from '@/components/Tag.vue'
import UpdateCard from './UpdateCard.vue'
import { settingsContextKey } from './useSettings'

const ctx = inject(settingsContextKey, null)
const o = computed(() => ctx?.overview.data.value ?? null)
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
          应用不会自动覆盖或重置原文件。请检查数据目录里的 config.json，修好后重启应用。
        </div>
      </section>
      <section class="st-section" aria-label="存储与版本">
        <div class="st-head"><h2>存储与版本</h2></div>
        <dl class="st-kv">
          <dt>数据目录</dt>
          <dd class="st-mono" data-testid="general-data-dir">{{ o.data_dir }}</dd>
          <dt>旧配置目录</dt>
          <dd class="st-mono" data-testid="general-legacy-dir">{{ o.legacy_config_dir }}</dd>
          <dt>应用版本</dt>
          <dd class="st-mono" data-testid="general-app-version">{{ o.app_version }}</dd>
          <dt>数据结构版本</dt>
          <dd class="st-mono" data-testid="general-schema">{{ o.schema_version }}</dd>
          <dt>修订号</dt>
          <dd class="st-mono">{{ o.revision }}</dd>
          <dt>存储状态</dt>
          <dd data-testid="general-store-state">
            <Tag :tone="o.store_state === 'ok' ? 'ok' : 'warn'">{{
              o.store_state === 'ok' ? '正常' : '只读错误'
            }}</Tag>
          </dd>
        </dl>
      </section>

      <!-- 关于与更新卡 -->
      <UpdateCard :busy="ctx?.busy.value" />
    </template>
  </div>
</template>
