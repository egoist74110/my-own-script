<script setup lang="ts">
import { ListChecks } from 'lucide-vue-next'
import EmptyState from '@/components/EmptyState.vue'
</script>

<template>
  <section class="tasks" aria-label="任务">
    <header class="topbar" data-tauri-drag-region>
      <h1>任务</h1>
    </header>
    <EmptyState
      :icon="ListChecks"
      title="任务执行正在接入"
      description="任务的创建与运行由后续切片（S3）提供，接入后会显示在这里。"
      data-testid="tasks-placeholder"
    />
  </section>
</template>

<style scoped>
.tasks {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.topbar {
  flex: none;
  display: flex;
  align-items: center;
  height: var(--topbar-h);
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
}
h1 {
  margin: 0;
  font-size: var(--text-page);
  font-weight: 700;
}
</style>
