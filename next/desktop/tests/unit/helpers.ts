import type { EventEnvelope, SocketLike } from '@/api/events'

export class FakeSocket implements SocketLike {
  static instances: FakeSocket[] = []
  onopen: SocketLike['onopen'] = null
  onmessage: SocketLike['onmessage'] = null
  onclose: SocketLike['onclose'] = null
  onerror: SocketLike['onerror'] = null
  sent: string[] = []
  closed = false

  constructor(public url: string) {
    FakeSocket.instances.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.closed = true
  }
  open() {
    this.onopen?.({})
  }
  emit(env: EventEnvelope) {
    this.onmessage?.({ data: JSON.stringify(env) })
  }
  drop(code = 1006) {
    this.onclose?.({ code })
  }
  static reset() {
    FakeSocket.instances = []
  }
  static last(): FakeSocket {
    const s = FakeSocket.instances[FakeSocket.instances.length - 1]
    if (!s) throw new Error('no socket')
    return s
  }
}

let seq = 0
export function resetSeq(n = 0) {
  seq = n
}

export function env(
  type: string,
  data: Record<string, unknown>,
  extra: Partial<EventEnvelope> = {},
): EventEnvelope {
  return {
    seq: ++seq,
    topic: 'system',
    type,
    ts: new Date().toISOString(),
    data,
    ...extra,
  }
}

export const quiet = { active: false, reason: null, changed_at: '2026-10-22T10:00:00Z' }
export const hello = (pid = 4242, alert: Record<string, unknown> = quiet) =>
  env('system.hello', { pid, version: '0.0.0-test', alert })
export const alertEvent = (active: boolean, reason: string | null = null) =>
  env('system.alert', { active, reason, changed_at: '2026-10-22T10:01:00Z' })
