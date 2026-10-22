<script setup lang="ts">
// ∞ 主视觉占位：自绘双环 + 双纽线线框（伯努利双纽线参数式，自行计算）。
const A = 120
const pts: string[] = []
for (let i = 0; i <= 120; i++) {
  const t = (i / 120) * Math.PI * 2
  const d = 1 + Math.sin(t) ** 2
  pts.push(`${(A * Math.cos(t)) / d + 150},${(A * Math.sin(t) * Math.cos(t)) / d + 110}`)
}
const path = `M${pts.join(' L')} Z`
</script>

<template>
  <div class="relative mx-auto h-[220px] w-[300px]" data-testid="infinity-placeholder">
    <svg
      class="anim-spin absolute inset-0"
      aria-hidden="true"
      width="300"
      height="220"
      viewBox="0 0 300 220"
      style="color: var(--ink)"
    >
      <circle
        cx="150"
        cy="110"
        r="104"
        fill="none"
        stroke="currentColor"
        stroke-width="1.2"
        stroke-dasharray="210 24 40 380"
      />
    </svg>
    <svg
      class="anim-spin-rev absolute inset-0"
      aria-hidden="true"
      width="300"
      height="220"
      viewBox="0 0 300 220"
      style="color: var(--orange)"
    >
      <circle
        cx="150"
        cy="110"
        r="86"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-dasharray="30 510"
      />
    </svg>
    <svg
      class="absolute inset-0"
      aria-hidden="true"
      width="300"
      height="220"
      viewBox="0 0 300 220"
      style="color: var(--ink)"
    >
      <path :d="path" fill="none" stroke="currentColor" stroke-width="1.5" />
    </svg>
    <span
      class="chip absolute bottom-0 left-1/2 -translate-x-1/2"
      style="background: var(--orange); color: #111214"
      >PLACEHOLDER</span
    >
  </div>
</template>
