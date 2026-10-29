<script setup lang="ts">
import { computed } from 'vue'
import Sheet from '@/components/Sheet.vue'
import Button from '@/components/Button.vue'
import {
  commandBranchIssue,
  commandRouteText,
  commandTargetNames,
  type CommandView,
  type ReleaseView,
  type TaskOperation,
} from './api'

/**
 * 选择运行命令：运行 / 只发布 / 回滚都先选一条命令，再进入预检与确认。
 * 只列启用的命令；不能临时勾目标，要新组合请先在配置里新建命令。
 */
const props = defineProps<{
  open: boolean
  config: ReleaseView | null
  operation: TaskOperation
}>()

const emit = defineEmits<{
  'update:open': [val: boolean]
  pick: [command: CommandView]
}>()

const title = computed(() => {
  const verb =
    props.operation === 'deploy_only' ? '只发布' : props.operation === 'rollback' ? '回滚' : '运行'
  return `选择要${verb}的命令`
})

const commands = computed(() => (props.config?.commands ?? []).filter((c) => c.enabled))
const hiddenCount = computed(() => (props.config?.commands.length ?? 0) - commands.value.length)

function targetsOf(c: CommandView): string[] {
  return props.config ? commandTargetNames(props.config, c) : []
}

/** 不能选的原因；能选返回空串。 */
function blockedReason(c: CommandView): string {
  if (c.active_run_id) return '正在运行，等它结束后再选'
  const issue = props.config ? commandBranchIssue(props.config, c) : 'none'
  if (issue === 'none') return '还没有选分支，先在“运行命令”里编辑它'
  if (issue === 'missing') return '它用的分支已被删除，先在“运行命令”里改选别的分支'
  if (targetsOf(c).length === 0) return '还没有选发布目标，先在“运行命令”里编辑它'
  return ''
}
</script>

<template>
  <Sheet
    :open="open"
    :title="title"
    :description="`“${config?.name ?? ''}”下的命令。每条命令固定了要发布的目标。`"
    @update:open="emit('update:open', $event)"
  >
    <div class="picker" data-testid="command-picker">
      <p v-if="commands.length === 0" class="picker-empty" data-testid="command-picker-empty">
        这个配置还没有可用的运行命令。请先在“运行命令”里新建一条，或启用已有的命令。
      </p>
      <ul v-else class="picker-list">
        <li v-for="c in commands" :key="c.id">
          <button
            type="button"
            class="picker-item"
            :disabled="Boolean(blockedReason(c))"
            :data-testid="`command-pick-${c.id}`"
            @click="emit('pick', c)"
          >
            <span class="pi-name">{{ c.name || c.tg_command }}</span>
            <span class="pi-targets" :data-testid="`command-pick-route-${c.id}`">
              {{ config ? commandRouteText(config, c) : '' }}
            </span>
            <span v-if="c.tg_command" class="pi-tg mono">{{ c.tg_command }}</span>
            <span v-if="blockedReason(c)" class="pi-block">{{ blockedReason(c) }}</span>
          </button>
        </li>
      </ul>
      <p v-if="hiddenCount > 0" class="picker-note">
        另有 {{ hiddenCount }} 条已停用的命令没有列出。
      </p>
    </div>
    <template #actions>
      <Button @click="emit('update:open', false)">取消</Button>
    </template>
  </Sheet>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 55vh;
  overflow-y: auto;
}
.picker-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.picker-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-ctl);
  background: var(--bg-window);
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.picker-item:hover:not(:disabled) {
  background: var(--hover);
}
.picker-item:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.pi-name {
  font-weight: 600;
}
.pi-targets {
  font-size: var(--text-sub);
  color: var(--mute);
  overflow-wrap: anywhere;
}
.pi-tg {
  font-size: 11px;
  color: var(--faint);
}
.pi-block {
  font-size: var(--text-sub);
  color: var(--bn-warn-fg);
}
.picker-empty,
.picker-note {
  margin: 0;
  font-size: var(--text-sub);
  color: var(--mute);
}
.mono {
  font-family: var(--font-mono);
}
</style>
