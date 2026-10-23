<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import Button from '@/components/Button.vue'
import Tag from '@/components/Tag.vue'
import { useUiStore } from '@/stores/ui'
import LocalRepoPanel from './LocalRepoPanel.vue'
import { settingsContextKey } from './useSettings'

type Sel = { kind: 'repo'; id: string } | { kind: 'new' }

const ctx = inject(settingsContextKey)!
const ui = useUiStore()
const sel = ref<Sel | null>(null)
/** 每次点「新建」递增：再次点新建也开始新的编辑会话。 */
const startToken = ref(0)

const repos = computed(() => ctx.ado.data.value?.local_repos ?? [])
const selected = computed(() => {
  const cur = sel.value
  return cur?.kind === 'repo' ? (repos.value.find((r) => r.id === cur.id) ?? null) : null
})
function pick(next: Sel) {
  if (next.kind === 'new') startToken.value++
  sel.value = next
  ui.inspectorOpen = true
}
const isSel = (id: string) => {
  const cur = sel.value
  return cur?.kind === 'repo' && cur.id === id
}
</script>

<template>
  <div class="st-body" data-testid="repos-tab">
    <section class="st-section" aria-label="本地仓库">
      <div class="st-head">
        <h2>本地仓库</h2>
        <Tag>{{ repos.length }}</Tag>
        <span class="st-grow"></span>
        <Button
          variant="primary"
          data-testid="repo-add"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="pick({ kind: 'new' })"
        >
          ＋ 新建仓库
        </Button>
      </div>
      <table class="st-tbl" data-testid="repo-table">
        <thead>
          <tr>
            <th scope="col">名称</th>
            <th scope="col">路径</th>
            <th scope="col">状态</th>
            <th scope="col">警告</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in repos"
            :key="r.id"
            tabindex="0"
            :aria-selected="isSel(r.id)"
            :data-selected="isSel(r.id)"
            :data-testid="`repo-row-${r.id}`"
            @click="pick({ kind: 'repo', id: r.id })"
            @keydown.enter.self="pick({ kind: 'repo', id: r.id })"
          >
            <td>{{ r.name }}</td>
            <td class="st-mono">{{ r.path }}</td>
            <td :class="{ 'st-warn': !r.exists }" :data-testid="`repo-exists-${r.id}`">
              {{ r.exists ? '存在' : '目录不存在' }}
            </td>
            <td class="st-warn" :data-testid="`repo-warn-${r.id}`">
              {{ (r.warnings ?? []).join('；') }}
            </td>
          </tr>
          <tr v-if="!repos.length">
            <td colspan="4" class="st-note">还没有本地仓库。</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="st-section st-editor" aria-label="本地仓库详情">
      <LocalRepoPanel
        v-if="sel?.kind === 'new' || selected"
        :repo="selected"
        :start-token="startToken"
        @select="(id: string) => pick({ kind: 'repo', id })"
        @deleted="sel = null"
      />
      <div v-else class="st-inspector" data-testid="repo-inspector-empty">
        <p class="st-note">选择一个本地仓库查看详情，或新建。路径只保存为文本，不会被读取。</p>
      </div>
    </section>
  </div>
</template>
