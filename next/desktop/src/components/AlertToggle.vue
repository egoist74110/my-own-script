<script setup lang="ts">
import { inject, ref } from 'vue'
import { Switch } from '@/components/ui/switch'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { useBackendStore } from '@/stores/backend'

const store = useBackendStore()
const runtime = inject(backendRuntimeKey, null)
const error = ref<string | null>(null)
const pending = ref(false)

/** 只向后端请求；告警态由随后收到的 `system.alert` 事件驱动，这里不本地切换。 */
async function request(next: boolean) {
  const api = runtime?.api()
  if (!api) {
    error.value = '后端未连接'
    return
  }
  pending.value = true
  error.value = null
  try {
    const res = await api.POST('/api/system/alert', {
      body: { active: next, reason: next ? 'S0 DEMO ALERT' : null },
    })
    if (res.error !== undefined || !res.response.ok) {
      error.value = `请求失败 (${res.response.status})`
    }
  } catch {
    error.value = '请求失败（网络）'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <span class="toggle" data-testid="alert-toggle">
    <label for="alert-demo" class="lbl">告警演示</label>
    <Switch
      id="alert-demo"
      aria-label="告警演示开关"
      :model-value="store.alert.active"
      class="hit"
      :disabled="pending"
      @update:model-value="(v: boolean) => request(v)"
    />
    <span v-if="error" role="alert" class="err" data-testid="alert-error">{{ error }}</span>
  </span>
</template>

<style scoped>
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
/* 视觉尺寸不变（20px），用伪元素把点击目标扩到 --target-min（32px） */
.hit {
  position: relative;
}
.hit::after {
  content: '';
  position: absolute;
  inset: calc((var(--target-min) - 100%) / -2) 0;
}
.lbl {
  display: inline-flex;
  align-items: center;
  min-height: var(--target-min);
}
.err {
  font-size: 10.5px;
  color: var(--warn-ink);
  font-family: var(--font-mono);
}
</style>
