<script setup lang="ts">
/** 骨架行（读取中）：不用转圈。容器自身是装饰性的，调用方负责 aria-busy。 */
withDefaults(defineProps<{ rows?: number }>(), { rows: 8 })
const WIDTHS = ['62%', '48%', '70%', '55%', '66%', '42%', '58%', '52%']
</script>

<template>
  <div class="skeleton" aria-hidden="true">
    <div v-for="n in rows" :key="n" class="sk-row">
      <div class="l1">
        <span class="bar" :style="{ width: WIDTHS[(n - 1) % WIDTHS.length] }"></span>
        <span class="bar" style="width: 36px"></span>
      </div>
      <span class="bar thin" style="width: 40%"></span>
    </div>
  </div>
</template>

<style scoped>
.skeleton {
  padding: 0 8px;
}
.sk-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px 12px 26px;
  border-bottom: 1px solid var(--line);
}
.l1 {
  display: flex;
  justify-content: space-between;
}
.bar {
  display: block;
  height: 10px;
  border-radius: 4px;
  background: var(--skeleton);
}
.bar.thin {
  height: 8px;
}
</style>
