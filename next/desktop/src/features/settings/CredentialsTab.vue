<script setup lang="ts">
import { computed, inject } from 'vue'
import Button from '@/components/Button.vue'
import Tag from '@/components/Tag.vue'
import type { CredentialStatus } from './api'
import { settingsContextKey } from './useSettings'

const ctx = inject(settingsContextKey)!
const rows = computed(() => ctx.credentials.data.value ?? [])

const KIND: Record<string, string> = { ado_pat: 'ADO PAT' }
const SOURCE: Record<CredentialStatus['source'], string> = {
  imported: '导入',
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
        这里只显示凭据是否存在与来源，永远不显示凭据的值。录入或替换 PAT 在「ADO 连接」页签。
      </p>
      <table class="st-tbl" data-testid="credentials-table">
        <thead>
          <tr>
            <th scope="col">类型</th>
            <th scope="col">所属</th>
            <th scope="col">存在</th>
            <th scope="col">来源</th>
            <th scope="col">状态</th>
            <th scope="col">更新时间</th>
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
            <td class="st-mono">{{ c.updated_at ?? '—' }}</td>
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
            <td colspan="7" class="st-note">暂无凭据条目</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
