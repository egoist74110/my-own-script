// backend store 故障路径（独立编写）：seq 基线、重启回退、畸形告警数据。
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useBackendStore } from '@/stores/backend'
import type { EventEnvelope } from '@/api/events'

const ENV_TS = new Date(0).toISOString()
const ev = (
  seq: number,
  type: string,
  data: Record<string, unknown>,
  topic = 'system',
): EventEnvelope => ({
  seq,
  topic,
  type,
  ts: ENV_TS,
  data,
})
const hello = (seq: number, alert?: Record<string, unknown>, pid = 1) =>
  ev(seq, 'system.hello', { pid, version: 'v', ...(alert ? { alert } : {}) })
const alert = (seq: number, active: boolean, reason: string | null = null) =>
  ev(seq, 'system.alert', { active, reason, changed_at: 'T' })
const ALERT_ON = { active: true, reason: 'disk', changed_at: 'T1' }

describe('backend store 故障路径', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('alert 事件的 seq 必须严格大于 lastSeq；相等或更小的被忽略', () => {
    const s = useBackendStore()
    s.applyEvent(hello(5))
    s.applyEvent(alert(6, true, 'a'))
    expect(s.denied).toBe(1)
    s.applyEvent(alert(6, false)) // 重复 seq
    expect(s.denied).toBe(1)
    s.applyEvent(alert(3, false)) // 乱序旧事件
    expect(s.denied).toBe(1)
    s.applyEvent(alert(7, false))
    expect(s.denied).toBe(0)
  })

  it('服务端重启后 seq 回退：新 hello 重新设定基线，之后的低 seq 告警可被接受', () => {
    const s = useBackendStore()
    s.applyEvent(hello(50))
    s.applyEvent(alert(51, true, 'before restart'))
    expect(s.denied).toBe(1)
    // 重启：seq 从小值重新开始
    s.applyEvent(hello(1, { active: false, reason: null, changed_at: 'T0' }, 999))
    expect(s.lastSeq).toBe(1)
    expect(s.pid).toBe(999)
    expect(s.denied).toBe(0)
    s.applyEvent(alert(2, true, 'after restart'))
    expect(s.denied).toBe(1)
    // 旧进程遗留的 seq 51 已不再有效（低于新基线 2）
    s.applyEvent(alert(1, false))
    expect(s.denied).toBe(1)
  })

  it('重启后 hello 不带 alert 字段：告警态保持不变（不凭空清除）', () => {
    const s = useBackendStore()
    s.applyEvent(hello(1))
    s.applyEvent(alert(2, true, 'x'))
    s.applyEvent(hello(1, undefined, 7))
    expect(s.denied).toBe(1)
    expect(s.pid).toBe(7)
  })

  it('畸形告警数据被忽略：active 非布尔、reason 非字符串/非 null、缺 changed_at', () => {
    const s = useBackendStore()
    s.applyEvent(hello(1))
    s.applyEvent(ev(2, 'system.alert', { active: 'yes', reason: null, changed_at: 'T' }))
    expect(s.denied).toBe(0)
    s.applyEvent(ev(3, 'system.alert', { active: true, reason: 5, changed_at: 'T' }))
    expect(s.denied).toBe(0)
    s.applyEvent(ev(4, 'system.alert', { active: true, reason: null }))
    expect(s.denied).toBe(0)
    s.applyEvent(ev(5, 'system.alert', { active: true, reason: null, changed_at: 'T' }))
    expect(s.denied).toBe(1)
  })

  it('hello 里的 alert 形状错误时不覆盖当前告警态', () => {
    const s = useBackendStore()
    s.applyEvent(hello(1, ALERT_ON))
    expect(s.denied).toBe(1)
    s.applyEvent(hello(2, { active: 'nope' }))
    expect(s.denied).toBe(1)
    expect(s.alert.reason).toBe('disk')
  })

  it('告警 reason 原样保存为字符串（store 层不做 HTML 解释）', () => {
    const s = useBackendStore()
    s.applyEvent(hello(1))
    const payload = '<img src=x onerror=alert(1)>'
    s.applyEvent(alert(2, true, payload))
    expect(s.alert.reason).toBe(payload)
  })

  it('连接状态切换到非 online 时清空心跳延迟；online 时保留', () => {
    const s = useBackendStore()
    s.setConnection('online')
    s.setLatency(12.4)
    expect(s.latencyMs).toBe(12)
    s.setConnection('reconnecting')
    expect(s.latencyMs).toBeNull()
  })
})
