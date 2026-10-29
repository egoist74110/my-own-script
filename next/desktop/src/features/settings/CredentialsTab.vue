<script setup lang="ts">
import { computed, inject } from 'vue'
import Button from '@/components/Button.vue'
import Tag from '@/components/Tag.vue'
import type { CredentialStatus } from './api'
import { fmtLocal } from './format'
import { settingsContextKey } from './useSettings'

const ctx = inject(settingsContextKey)!
const rows = computed(() => ctx.credentials.data.value ?? [])

const KIND: Record<string, string> = { ado_pat: 'ADO PAT' }
const SOURCE: Record<CredentialStatus['source'], string> = {
  imported: '从旧版导入',
  manual: '手动录入',
  unknown: '未知',
}
const STATE: Record<CredentialStatus['state'], string> = {
  present: '正常',
  missing: '未保存',
  unreadable: '无法读取',
  orphan: '孤立',
  pending_delete: '待删除',
}
const presentText = (c: CredentialStatus) =>
  c.state === 'unreadable' || c.present === null ? '未知' : c.present ? '是' : '否'
const cleanable = (c: CredentialStatus) => c.state === 'orphan' || c.state === 'pending_delete'
</script>

<template>
  <div class="st-body" data-testid="credentials-tab">
    <section class="st-section" aria-label="凭据状态">
      <div class="st-head">
        <h2>凭据状态</h2>
        <Tag>{{ rows.length }}</Tag>
      </div>
      <p class="st-note">
        这里只显示凭据是否存在、从哪来，不显示内容。ADO 的 PAT 在「ADO 连接」里录入或更换。
      </p>
      <div class="st-tw">
        <table class="st-tbl" data-testid="credentials-table">
          <thead>
            <tr>
              <th scope="col">凭据</th>
              <th scope="col">用于</th>
              <th scope="col">存在</th>
              <th scope="col">来源</th>
              <th scope="col">状态</th>
              <th scope="col">更新于</th>
              <th scope="col"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in rows" :key="c.account" :data-testid="`cred-${c.account}`">
              <td>{{ KIND[c.kind] ?? c.kind }}</td>
              <td>{{ c.ref_name ?? c.ref }}</td>
              <td>{{ presentText(c) }}</td>
              <td>{{ SOURCE[c.source] }}</td>
              <td :class="{ 'st-warn': c.state !== 'present' }">{{ STATE[c.state] }}</td>
              <td class="st-mono">{{ fmtLocal(c.updated_at) }}</td>
              <td>
                <Button
                  v-if="cleanable(c)"
                  :disabled="ctx.busy.value || !ctx.writable.value"
                  @click="ctx.deleteCredential(c.account)"
                >
                  清理
                </Button>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="7" class="st-note">还没有保存任何凭据。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
