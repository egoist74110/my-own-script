<script setup lang="ts">
import Inspector from '@/components/Inspector.vue'
import type { TaskView } from './api'

defineProps<{
  task: TaskView | null
}>()
</script>

<template>
  <Inspector label="任务配置">
    <div v-if="task" class="task-inspector-content" data-testid="task-inspector">
      <!-- Git 段落 -->
      <section class="insp-section">
        <h4 class="insp-heading">Git</h4>
        <dl class="insp-dl">
          <dt>本地路径</dt>
          <dd class="mono">{{ task.local_repo_path || '—' }}</dd>
          <dt>构建分支</dt>
          <dd class="mono">{{ task.git_flow?.build_branch || '—' }}</dd>
          <dt>更新</dt>
          <dd class="mono">
            {{ task.git_flow?.update_branches?.join(', ') || '—' }}
          </dd>
          <dt>合并</dt>
          <dd class="mono">
            {{ task.git_flow?.merges?.map((m) => `${m.source} → ${m.target}`).join(', ') || '—' }}
          </dd>
          <dt>推送</dt>
          <dd class="mono">
            {{ task.git_flow?.push_branches?.join(', ') || '—' }}
          </dd>
        </dl>
      </section>

      <!-- 目标段落 -->
      <section class="insp-section">
        <h4 class="insp-heading">目标</h4>
        <div v-if="!task.targets || task.targets.length === 0" class="muted">暂无配置发布目标</div>
        <div v-else class="targets-list">
          <div
            v-for="(t, idx) in task.targets"
            :key="idx"
            class="target-card"
            :data-enabled="t.enabled ? 'true' : 'false'"
          >
            <div class="target-card-head">
              <span class="target-name">{{ t.name }}</span>
              <span v-if="!t.enabled" class="target-disabled-tag">已停用</span>
            </div>
            <div class="target-card-sub">
              构建：{{ t.build_name || (t.build_id ? `#${t.build_id}` : '未指定') }} · Release：{{
                t.release_name || (t.release_id ? `#${t.release_id}` : '未指定')
              }}
            </div>
            <div v-if="t.release_stage_names?.length" class="target-card-stages">
              环境：{{ t.release_stage_names.join(' → ') }}
            </div>
          </div>
        </div>
      </section>

      <!-- 执行策略与 Telegram -->
      <section class="insp-section">
        <h4 class="insp-heading">执行策略</h4>
        <div class="insp-meta">
          <span>Agent 队列：{{ task.agent_queue_name || task.agent_queue_id || '默认' }}</span>
          <span>失败策略：失败即停 · 目标串行</span>
          <span v-if="task.tg_command">Telegram：{{ task.tg_command }}</span>
        </div>
      </section>
    </div>
    <div v-else class="insp-empty">未选择任务</div>
  </Inspector>
</template>

<style scoped>
.task-inspector-content {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-size: var(--text-sub);
}
.insp-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.insp-heading {
  margin: 0;
  font-size: var(--text-body);
  font-weight: 700;
  color: var(--ink);
}
.insp-dl {
  margin: 0;
  display: grid;
  grid-template-columns: 60px minmax(0, 1fr);
  gap: 6px 10px;
}
dt {
  color: var(--mute);
}
dd {
  margin: 0;
  color: var(--ink);
  word-break: break-all;
}
.targets-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.target-card {
  padding: 8px 10px;
  border-radius: var(--r-ctl);
  background: var(--bg-card);
  border: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.target-card[data-enabled='false'] {
  opacity: 0.6;
}
.target-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.target-name {
  font-weight: 600;
  color: var(--ink);
}
.target-disabled-tag {
  font-size: 10px;
  color: var(--mute);
}
.target-card-sub,
.target-card-stages {
  font-size: 11px;
  color: var(--mute);
}
.insp-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--mute);
  font-size: 12px;
}
.insp-empty {
  padding: 24px;
  text-align: center;
  color: var(--mute);
}
.mono {
  font-family: var(--font-mono);
}
.muted {
  color: var(--mute);
}
</style>
