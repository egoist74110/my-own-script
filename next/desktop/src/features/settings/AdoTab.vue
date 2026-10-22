<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import BlockTag from '@/components/BlockTag.vue'
import InspectorPanel from '@/components/InspectorPanel.vue'
import { useUiStore } from '@/stores/ui'
import LibraryPanel from './LibraryPanel.vue'
import ProjectPanel from './ProjectPanel.vue'
import { settingsContextKey } from './useSettings'

type Sel =
  | { kind: 'library'; id: string }
  | { kind: 'project'; id: string }
  | { kind: 'new-library' }
  | { kind: 'new-project' }

const ctx = inject(settingsContextKey)!
const ui = useUiStore()
const sel = ref<Sel | null>(null)

const libraries = computed(() => ctx.ado.data.value?.libraries ?? [])
const projects = computed(() => ctx.ado.data.value?.projects ?? [])
const active = computed(() => ({
  lib: ctx.ado.data.value?.active_library_id ?? null,
  proj: ctx.ado.data.value?.active_project_id ?? null,
}))
const libName = (id: string) => libraries.value.find((l) => l.id === id)?.name ?? id

const selId = computed(() => (sel.value && 'id' in sel.value ? sel.value.id : null))
const selectedLibrary = computed(() =>
  sel.value?.kind === 'library'
    ? (libraries.value.find((l) => l.id === selId.value) ?? null)
    : null,
)
const selectedProject = computed(() =>
  sel.value?.kind === 'project' ? (projects.value.find((p) => p.id === selId.value) ?? null) : null,
)

function pick(next: Sel) {
  sel.value = next
  ui.inspectorOpen = true
}
const isSel = (kind: Sel['kind'], id: string) => sel.value?.kind === kind && selId.value === id

const PAT: Record<string, string> = {
  present: '已保存',
  missing: '未保存',
  unreadable: '无法读取',
  orphan: '孤立',
  pending_delete: '待删除',
}
const isHttp = (u: string) => u.toLowerCase().startsWith('http:')
</script>

<template>
  <div class="st-body" data-testid="ado-tab">
    <section class="st-section" aria-label="Libraries">
      <div class="st-head">
        <h2>Libraries</h2>
        <BlockTag>{{ libraries.length }}</BlockTag>
        <span class="st-grow"></span>
        <AppButton
          data-testid="library-add"
          :disabled="ctx.busy.value || !ctx.writable.value"
          @click="pick({ kind: 'new-library' })"
        >
          ＋ 新建 library
        </AppButton>
      </div>
      <table class="st-tbl" data-testid="library-table">
        <thead>
          <tr>
            <th scope="col">名称</th>
            <th scope="col">地址</th>
            <th scope="col">PAT</th>
            <th scope="col"><span class="sr-only">标记</span></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="l in libraries"
            :key="l.id"
            tabindex="0"
            :aria-selected="isSel('library', l.id)"
            :data-selected="isSel('library', l.id)"
            :data-testid="`library-row-${l.id}`"
            @click="pick({ kind: 'library', id: l.id })"
            @keydown.enter.self="pick({ kind: 'library', id: l.id })"
          >
            <td>{{ l.name }}</td>
            <td class="st-mono">
              {{ l.base_url }}
              <BlockTag v-if="isHttp(l.base_url)" tone="warn">HTTP 明文</BlockTag>
            </td>
            <td :class="{ 'st-warn': l.credential.state !== 'present' }">
              {{ PAT[l.credential.state] }}
            </td>
            <td><BlockTag v-if="active.lib === l.id" tone="acc">当前</BlockTag></td>
          </tr>
          <tr v-if="!libraries.length">
            <td colspan="4" class="st-note">
              还没有 library。可从「导入」页签导入旧配置，或手动新建。
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="st-section" aria-label="Projects">
      <div class="st-head">
        <h2>Projects</h2>
        <BlockTag>{{ projects.length }}</BlockTag>
        <span class="st-grow"></span>
        <AppButton
          data-testid="project-add"
          :disabled="ctx.busy.value || !ctx.writable.value || !libraries.length"
          @click="pick({ kind: 'new-project' })"
        >
          ＋ 新建 project
        </AppButton>
      </div>
      <table class="st-tbl" data-testid="project-table">
        <thead>
          <tr>
            <th scope="col">Library</th>
            <th scope="col">Collection</th>
            <th scope="col">Project</th>
            <th scope="col"><span class="sr-only">标记</span></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="p in projects"
            :key="p.id"
            tabindex="0"
            :aria-selected="isSel('project', p.id)"
            :data-selected="isSel('project', p.id)"
            :data-testid="`project-row-${p.id}`"
            @click="pick({ kind: 'project', id: p.id })"
            @keydown.enter.self="pick({ kind: 'project', id: p.id })"
          >
            <td>{{ libName(p.library_id) }}</td>
            <td class="st-mono">{{ p.collection }}</td>
            <td class="st-mono">{{ p.project }}</td>
            <td><BlockTag v-if="active.proj === p.id" tone="acc">当前</BlockTag></td>
          </tr>
          <tr v-if="!projects.length">
            <td colspan="4" class="st-note">还没有 project。</td>
          </tr>
        </tbody>
      </table>
    </section>

    <InspectorPanel label="ADO 详情">
      <LibraryPanel
        v-if="sel?.kind === 'new-library' || selectedLibrary"
        :library="selectedLibrary"
        @select="(id: string) => pick({ kind: 'library', id })"
        @deleted="sel = null"
      />
      <ProjectPanel
        v-else-if="sel?.kind === 'new-project' || selectedProject"
        :project="selectedProject"
        @select="(id: string) => pick({ kind: 'project', id })"
        @deleted="sel = null"
      />
      <div v-else class="st-inspector" data-testid="ado-inspector-empty">
        <p class="st-note">
          选择一个 library 或 project 查看详情；PAT 在 library 详情里录入或替换。
        </p>
      </div>
    </InspectorPanel>
  </div>
</template>
