<script setup lang="ts">
import Inspector from '@/components/Inspector.vue'
import type { ReleaseView } from './api'

const props = defineProps<{
  config: ReleaseView | null
}>()

/** 使用某个分支的命令。 */
function usersOf(branchId: string) {
  return (props.config?.commands ?? []).filter((c) => c.branch_id === branchId)
}
</script>

<template>
  <Inspector label="发布配置">
    <div v-if="config" class="task-inspector-content" data-testid="task-inspector">
      <!-- Git 段落：本地路径 + 每个分支各自的规则 -->
      <section class="insp-section">
        <h4 class="insp-heading">Git</h4>
        <dl class="insp-dl">
          <dt>本地路径</dt>
          <dd class="mono">{{ config.local_repo_path || '—' }}</dd>
        </dl>
        <div v-if="!config.branches || config.branches.length === 0" class="muted">
          还没有分支。点“编辑配置”添加。
        </div>
        <div v-else class="targets-list">
          <div
            v-for="b in config.branches"
            :key="b.id"
            class="target-card"
            :data-testid="`inspector-branch-${b.id}`"
          >
            <div class="target-card-head">
              <span class="target-name mono">{{ b.build_branch || '未命名' }}</span>
              <span v-if="usersOf(b.id).length" class="target-card-sub">
                {{ usersOf(b.id).length }} 条命令使用
              </span>
            </div>
            <dl class="insp-dl">
              <dt>更新</dt>
              <dd class="mono">{{ b.update_branches?.join(', ') || '—' }}</dd>
              <dt>合并</dt>
              <dd class="mono">
                {{ b.merges?.map((m) => `${m.source} → ${m.target}`).join(', ') || '—' }}
              </dd>
              <dt>推送</dt>
              <dd class="mono">{{ b.push_branches?.join(', ') || '—' }}</dd>
            </dl>
          </div>
        </div>
      </section>

      <!-- 目标段落 -->
      <section class="insp-section">
        <h4 class="insp-heading">目标</h4>
        <div v-if="!config.targets || config.targets.length === 0" class="muted">
          还没有发布目标。点“编辑配置”添加。
        </div>
        <div v-else class="targets-list">
          <div v-for="t in config.targets" :key="t.id" class="target-card">
            <div class="target-card-head">
              <span class="target-name">{{ t.name }}</span>
            </div>
            <div class="target-card-sub">
              构建：{{ t.build_name || (t.build_id ? `#${t.build_id}` : '未指定') }}
            </div>
            <div class="target-card-sub">
              Release：{{ t.release_name || (t.release_id ? `#${t.release_id}` : '未指定') }}
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
          <span>Agent 队列：{{ config.agent_queue_name || config.agent_queue_id || '默认' }}</span>
          <span>失败策略：失败即停，目标按顺序串行</span>
          <span>运行命令：{{ config.commands.length }} 条，每条固定了分支和要发布的目标</span>
        </div>
      </section>
    </div>
    <div v-else class="insp-empty">未选择发布配置</div>
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
.target-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.target-name {
  font-weight: 600;
  color: var(--ink);
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
