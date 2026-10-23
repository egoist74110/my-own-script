<script setup lang="ts">
import { computed } from 'vue'
import Tag from '@/components/Tag.vue'

/** 导入预览 / 已完成摘要的分块展示。数据来自后端（形状宽松），逐字段防御式读取；不含任何凭据值。 */
const props = defineProps<{ data: Record<string, unknown> }>()

type Row = Record<string, unknown>
const rows = (v: unknown): Row[] =>
  Array.isArray(v) ? v.filter((x): x is Row => typeof x === 'object' && x !== null) : []
const strs = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
const text = (v: unknown): string =>
  typeof v === 'string' || typeof v === 'number' ? String(v) : '—'

const files = computed(() => rows(props.data.files))
const libraries = computed(() => rows(props.data.libraries))
const projects = computed(() => rows(props.data.projects))
const warnings = computed(() => strs(props.data.warnings))
const errors = computed(() => strs(props.data.errors))
const preserved = computed(() => strs(props.data.preserved_sections))
const libName = (id: unknown) => {
  const l = libraries.value.find((x) => x.id === id)
  return l ? text(l.name) : text(id)
}

const FILE_STATE: Record<string, string> = { present: '存在', missing: '缺失', error: '解析错误' }
const PAT_STATE: Record<string, string> = {
  found: '已找到',
  missing: '未找到',
  unreadable: '无法读取',
}
const RULE: Record<string, string> = {
  migrated_from_flows: '由旧 flows 生成任务',
  kept_tasks: '保留旧 tasks（含空列表，不从 flows 补回）',
  empty: '无任务',
}
const isHttp = (u: unknown) => typeof u === 'string' && u.startsWith('http:')
</script>

<template>
  <div class="blocks">
    <section
      v-if="errors.length"
      class="st-box"
      data-tone="warn"
      role="alert"
      data-testid="import-errors"
    >
      <strong class="st-warn">阻断错误（修复源配置后重新预览）</strong>
      <ul class="st-list">
        <li v-for="e in errors" :key="e">{{ e }}</li>
      </ul>
    </section>

    <section class="st-section" aria-label="源文件">
      <div class="st-head"><h2>源文件</h2></div>
      <p v-if="data.source_dir" class="st-mono" data-testid="import-source-dir">
        {{ text(data.source_dir) }}
      </p>
      <table v-if="files.length" class="st-tbl">
        <thead>
          <tr>
            <th scope="col">文件</th>
            <th scope="col">状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in files" :key="text(f.name)">
            <td class="st-mono">{{ text(f.name) }}</td>
            <td :class="{ 'st-warn': f.state === 'error' }">
              {{ FILE_STATE[text(f.state)] ?? text(f.state) }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="st-section" aria-label="将导入的 libraries">
      <div class="st-head">
        <h2>Libraries</h2>
        <Tag>{{ libraries.length }}</Tag>
      </div>
      <table v-if="libraries.length" class="st-tbl" data-testid="import-libraries">
        <thead>
          <tr>
            <th scope="col">名称</th>
            <th scope="col">地址</th>
            <th scope="col">旧 Keychain 中的 PAT</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in libraries" :key="text(l.id)">
            <td>{{ text(l.name) }}</td>
            <td class="st-mono">
              {{ text(l.base_url) }}
              <Tag v-if="isHttp(l.base_url)" tone="warn">HTTP 明文</Tag>
            </td>
            <td :class="{ 'st-warn': l.pat_status === 'unreadable' }">
              {{ PAT_STATE[text(l.pat_status)] ?? (l.pat_status ? text(l.pat_status) : '—') }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="st-note">无</p>
    </section>

    <section class="st-section" aria-label="将导入的 projects">
      <div class="st-head">
        <h2>Projects</h2>
        <Tag>{{ projects.length }}</Tag>
      </div>
      <table v-if="projects.length" class="st-tbl" data-testid="import-projects">
        <thead>
          <tr>
            <th scope="col">Library</th>
            <th scope="col">Collection</th>
            <th scope="col">Project</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in projects" :key="text(p.id)">
            <td>{{ libName(p.library_id) }}</td>
            <td class="st-mono">{{ text(p.collection) }}</td>
            <td class="st-mono">{{ text(p.project) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="st-note">无</p>
    </section>

    <section class="st-section" aria-label="任务与保留段">
      <div class="st-head"><h2>任务</h2></div>
      <dl class="st-kv">
        <dt class="lbl">规则</dt>
        <dd data-testid="import-tasks-rule">
          {{ RULE[text(data.tasks_rule)] ?? text(data.tasks_rule) }}
        </dd>
        <dt class="lbl">任务数</dt>
        <dd data-testid="import-task-count">{{ text(data.task_count) }}</dd>
        <dt class="lbl">原样保留</dt>
        <dd>
          <span class="st-tags">
            <Tag v-for="s in preserved" :key="s">{{ s }}</Tag>
            <span v-if="!preserved.length">—</span>
          </span>
        </dd>
      </dl>
    </section>

    <section v-if="warnings.length" class="st-box" data-tone="warn" data-testid="import-warnings">
      <strong class="st-warn">警告</strong>
      <ul class="st-list">
        <li v-for="w in warnings" :key="w">{{ w }}</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.blocks {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
