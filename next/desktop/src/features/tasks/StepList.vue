<script setup lang="ts">
import type { StepView } from './api'
import { formatDuration } from './api'

defineProps<{
  steps: StepView[]
}>()

function stepIcon(status: StepView['status']) {
  switch (status) {
    case 'succeeded':
      return { text: '✓', class: 'st-ok' }
    case 'running':
      return { text: '●', class: 'st-run' }
    case 'failed':
      return { text: '✕', class: 'st-fail' }
    case 'unknown':
      return { text: '?', class: 'st-unk' }
    case 'skipped':
      return { text: '—', class: 'st-skip' }
    default:
      return { text: '', class: 'st-wait' }
  }
}

function stepName(step: StepView) {
  switch (step.kind) {
    case 'git':
      return 'Git 同步'
    case 'build':
      return step.target_index !== null ? `目标 ${step.target_index + 1} 构建` : '构建'
    case 'release':
      return step.target_index !== null ? `目标 ${step.target_index + 1} 发布` : '发布'
    case 'rollback':
      return step.target_index !== null ? `目标 ${step.target_index + 1} 回滚` : '回滚'
    default:
      return step.kind
  }
}

function stepDetail(step: StepView): string {
  const cp = (step.checkpoint ?? {}) as Record<string, unknown>
  if (typeof cp.summary === 'string' && cp.summary.trim()) {
    return cp.summary.trim()
  }
  if (step.kind === 'git') {
    const orig = cp.original_branch ? String(cp.original_branch) : ''
    const commit = cp.expected_commit ? String(cp.expected_commit).slice(0, 7) : ''
    if (commit) return `commit ${commit}`
    if (orig) return `分支 ${orig}`
    return '本地更新与推送'
  }
  if (step.kind === 'build') {
    const id = cp.build_id ?? cp.definition_id
    const commit = cp.commit ? String(cp.commit).slice(0, 7) : ''
    const parts: string[] = []
    if (id) parts.push(`#${id}`)
    if (commit) parts.push(commit)
    return parts.length ? parts.join(' · ') : '远端构建中'
  }
  if (step.kind === 'release' || step.kind === 'rollback') {
    const rid = cp.release_id ?? cp.release_definition_id
    if (rid) return `Release-${rid}`
    return '环境部署中'
  }
  return ''
}
</script>

<template>
  <div class="steps-wrapper" aria-label="执行步骤">
    <div v-if="steps.length === 0" class="steps-empty">等待开始…</div>
    <div v-for="s in steps" :key="s.step_no" class="step-row" :data-status="s.status">
      <span class="icon-wrap" :class="stepIcon(s.status).class">
        {{ stepIcon(s.status).text }}
      </span>
      <div class="step-info">
        <span class="step-title">{{ stepName(s) }}</span>
        <span class="step-detail">{{ stepDetail(s) }}</span>
      </div>
      <span class="step-time mono">
        {{ formatDuration(s.started_at, s.finished_at) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.steps-wrapper {
  display: flex;
  flex-direction: column;
  padding: 8px 12px;
  overflow: auto;
}
.steps-empty {
  padding: 16px;
  color: var(--mute);
  font-size: var(--text-sub);
  text-align: center;
}
.step-row {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 7px 0;
  border-bottom: 1px solid var(--line);
}
.step-row:last-child {
  border-bottom: none;
}
.icon-wrap {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex: none;
}
.st-ok {
  background: var(--st-success-dot);
  color: #fff;
}
.st-run {
  background: var(--st-running-dot);
  color: #fff;
  animation: pulse 1.6s ease-out infinite;
}
.st-fail {
  background: var(--st-failed-dot);
  color: #fff;
}
.st-unk {
  background: var(--st-verify-dot);
  color: #fff;
}
.st-skip {
  background: var(--line);
  color: var(--mute);
}
.st-wait {
  background: var(--line);
  color: var(--mute);
}
.step-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.step-title {
  font-weight: 600;
  font-size: var(--text-body);
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.step-detail {
  font-size: var(--text-sub);
  color: var(--mute);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.step-time {
  font-size: var(--text-sub);
  color: var(--mute);
}
.mono {
  font-family: var(--font-mono);
}
@keyframes pulse {
  0% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
  100% {
    opacity: 1;
  }
}
</style>
