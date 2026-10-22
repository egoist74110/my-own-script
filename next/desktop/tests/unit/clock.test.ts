import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ClockBlock from '@/components/ClockBlock.vue'
import { formatClock, useClock } from '@/lib/clock'

describe('时钟', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('格式：HH:MM、秒、THU · 22 OCT 2026', () => {
    const p = formatClock(new Date(2026, 9, 22, 21, 48, 9))
    expect(p).toEqual({ hm: '21:48', seconds: '09', date: 'THU · 22 OCT 2026' })
    expect(formatClock(new Date(2026, 0, 5, 0, 3, 0)).hm).toBe('00:03')
    expect(formatClock(new Date(2026, 0, 5)).date).toBe('MON · 05 JAN 2026')
  })

  it('每秒更新', async () => {
    let t = new Date(2026, 9, 22, 21, 48, 9).getTime()
    const mounted = mount(ClockBlock, { props: { now: () => new Date(t) } })
    expect(mounted.get('[data-testid=clock-sec]').text()).toBe('09')
    t += 1000
    await vi.advanceTimersByTimeAsync(1000)
    expect(mounted.get('[data-testid=clock-sec]').text()).toBe('10')
    mounted.unmount()
  })

  it('卸载清定时器', () => {
    const base = vi.getTimerCount()
    const mounted = mount(ClockBlock)
    expect(vi.getTimerCount()).toBe(base + 1)
    mounted.unmount()
    expect(vi.getTimerCount()).toBe(base)
  })

  it('作用域销毁清定时器', () => {
    const base = vi.getTimerCount()
    const scope = effectScope()
    scope.run(() => useClock())
    expect(vi.getTimerCount()).toBe(base + 1)
    scope.stop()
    expect(vi.getTimerCount()).toBe(base)
  })
})
