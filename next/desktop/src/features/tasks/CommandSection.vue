<script setup lang="ts">
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from 'lucide-vue-next'
import Banner from '@/components/Banner.vue'
import Button from '@/components/Button.vue'
import StatusPill from '@/components/StatusPill.vue'
import Tag from '@/components/Tag.vue'
import {
  commandRouteText,
  formatRelativeTime,
  mapStatusToPill,
  releaseErrorText,
  type CommandView,
  type ReleaseView,
} from './api'

/**
 * 「运行命令」区：这个配置下预先建好的命令（名称、TG 命令、所选目标、最近一次结果）。
 * 在这里新建、编辑、删除、排序；运行时不能临时改目标。
 */
defineProps<{
  config: ReleaseView
  /** 命令写操作失败时的错误，显示在区块内。 */
  error?: unknown
  busy?: boolean
}>()

const emit = defineEmits<{
  create: []
  edit: [command: CommandView]
  delete: [command: CommandView]
  move: [command: CommandView, direction: -1 | 1]
}>()

function lastText(c: CommandView): string {
  if (c.active_run_id) return '正在运行'
  return c.last_run ? formatRelativeTime(c.last_run.created_at) : '从未运行'
}
</script>

<template>
  <section class="cmd-sec" aria-label="运行命令" data-testid="command-section">
    <div class="cmd-head">
      <h2 class="sec-title">运行命令</h2>
      <Button variant="default" data-testid="new-command-btn" @click="emit('create')">
        <Plus :size="13" aria-hidden="true" />
        新建命令
      </Button>
    </div>
    <Banner v-if="error" kind="error" class="cmd-error" data-testid="command-error">
      {{ releaseErrorText(error) }}
    </Banner>

    <p v-if="config.commands.length === 0" class="cmd-empty" data-testid="command-empty">
      还没有运行命令。新建一条，选好要发布的目标，之后就能点“运行”。
    </p>
    <ul v-else class="cmd-list">
      <li
        v-for="(c, i) in config.commands"
        :key="c.id"
        class="cmd-row"
        :data-testid="`command-row-${c.id}`"
      >
        <div class="cmd-main">
          <div class="cmd-l1">
            <span class="cmd-name">{{ c.name || c.tg_command }}</span>
            <Tag v-if="!c.enabled">已停用</Tag>
          </div>
          <div class="cmd-l2">
            <span :data-testid="`command-route-${c.id}`">{{ commandRouteText(config, c) }}</span>
          </div>
          <div class="cmd-l3">
            <span v-if="c.tg_command" class="mono">{{ c.tg_command }}</span>
            <span v-if="c.tg_desc">{{ c.tg_desc }}</span>
          </div>
        </div>
        <div class="cmd-last">
          <StatusPill
            v-if="c.active_run_id || c.last_run"
            :state="mapStatusToPill(true, c.active_run_id ? 'running' : c.last_run?.status)"
          />
          <span class="when">{{ lastText(c) }}</span>
        </div>
        <div class="cmd-actions">
          <button
            type="button"
            class="icon-btn"
            :aria-label="`上移 ${c.name}`"
            :disabled="busy || i === 0"
            :data-testid="`command-up-${c.id}`"
            @click="emit('move', c, -1)"
          >
            <ArrowUp :size="14" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="icon-btn"
            :aria-label="`下移 ${c.name}`"
            :disabled="busy || i === config.commands.length - 1"
            :data-testid="`command-down-${c.id}`"
            @click="emit('move', c, 1)"
          >
            <ArrowDown :size="14" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="icon-btn"
            :aria-label="`编辑 ${c.name}`"
            :data-testid="`command-edit-${c.id}`"
            @click="emit('edit', c)"
          >
            <Pencil :size="14" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="icon-btn danger"
            :aria-label="`删除 ${c.name}`"
            :data-testid="`command-delete-${c.id}`"
            @click="emit('delete', c)"
          >
            <Trash2 :size="14" aria-hidden="true" />
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.cmd-sec {
  margin-top: 24px;
  min-width: 0;
}
.cmd-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.sec-title {
  margin: 0;
  font-size: var(--text-sub);
  font-weight: 600;
  color: var(--mute);
}
.cmd-error {
  margin-bottom: 8px;
}
.cmd-empty {
  margin: 0;
  padding: 12px 0;
  color: var(--mute);
  font-size: var(--text-sub);
}
.cmd-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
}
.cmd-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 10px;
  border-radius: var(--r-row);
  min-width: 0;
}
.cmd-row:hover {
  background: var(--hover);
}
.cmd-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.cmd-l1 {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cmd-name {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.cmd-l2 {
  font-size: var(--text-sub);
  color: var(--mute);
  overflow-wrap: anywhere;
}
.cmd-l3 {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--faint);
}
.cmd-last {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sub);
  color: var(--mute);
  white-space: nowrap;
}
.cmd-actions {
  flex: none;
  display: flex;
  gap: 2px;
}
.icon-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: var(--r-ctl);
  background: transparent;
  color: var(--mute);
  cursor: pointer;
}
.icon-btn:hover:not(:disabled) {
  background: var(--ctl);
  color: var(--ink);
}
.icon-btn.danger:hover:not(:disabled) {
  color: var(--st-failed-dot);
}
.icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.mono {
  font-family: var(--font-mono);
}
@container detail (max-width: 559px) {
  .cmd-row {
    flex-wrap: wrap;
  }
  .cmd-last {
    order: 3;
  }
}
</style>
