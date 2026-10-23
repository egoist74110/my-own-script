// 主控 S4 联调发现：选中已结束的 run 时①回放的每个 checkpoint 都立即触发一次快照 GET；
// ②快照在途时 WS 回放已推进水位，快照返回后水位被重置，HTTP 回放把日志再追加一遍。
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import type { BackendRuntime } from '@/app/backend-runtime'
import type { ApiClient } from '@/api/client'
import type { RunEventData } from '@/features/tasks/api'
import { useRunLogs } from '@/features/tasks/useRunLogs'

const RUN = 'run-finished'

function events(): RunEventData[] {
  const items: unknown[] = []
  for (let seq = 1; seq <= 30; seq++) {
    items.push(
      seq % 3 === 0
        ? { run_id: RUN, run_seq: seq, type: 'checkpoint', payload: { kind: 'git' } }
        : { run_id: RUN, run_seq: seq, type: 'log', payload: { text: `line ${seq}` } },
    )
  }
  return items as RunEventData[]
}

async function load({ replayOverWs }: { replayOverWs: boolean }) {
  const calls: string[] = []
  let listener: ((e: unknown) => void) | null = null
  const client = {
    GET: vi.fn(async (path: string) => {
      calls.push(path)
      if (path === '/api/runs/{run_id}') {
        if (replayOverWs) {
          for (const data of events()) {
            listener?.({ type: 'run.event', topic: 'run', data, seq: data.run_seq, ts: '' })
          }
        }
        return {
          data: {
            run_id: RUN,
            task_id: 'task-1',
            operation: 'sync_build_release',
            status: 'succeeded',
            steps: [],
            last_seq: 30,
          },
          response: new Response(),
        }
      }
      return {
        data: { items: events(), next_seq: 30, has_more: false },
        response: new Response(),
      }
    }),
  } as unknown as ApiClient
  const runtime = {
    api: () => null,
    start: () => {},
    stop: () => {},
    send: () => true,
    subscribeRun: () => true,
    unsubscribeRun: () => true,
    onEvent: (l: (e: unknown) => void) => {
      listener = l
      return () => {
        listener = null
      }
    },
  } as unknown as BackendRuntime

  let state!: ReturnType<typeof useRunLogs>
  const wrapper = mount(
    defineComponent({
      setup() {
        state = useRunLogs(ref(RUN), runtime, ref(true), () => client)
        return () => null
      },
    }),
  )
  await flushPromises()
  await new Promise((r) => setTimeout(r, 200))
  await flushPromises()
  const seqs = state.lines.value.map((l) => l.seq)
  wrapper.unmount()
  return { snapshots: calls.filter((p) => p === '/api/runs/{run_id}').length, seqs }
}

it('回放已结束 run 的大量 checkpoint 不会造成快照请求突发，且日志行不重复', async () => {
  const { snapshots, seqs } = await load({ replayOverWs: false })
  expect(snapshots).toBeLessThanOrEqual(2)
  expect(seqs.length).toBe(20)
  expect(new Set(seqs).size).toBe(20)
})

it('WS 回放在快照请求期间先到达时，HTTP 回放不会把日志再追加一遍', async () => {
  const { snapshots, seqs } = await load({ replayOverWs: true })
  expect(snapshots).toBeLessThanOrEqual(2)
  expect(seqs.length).toBe(20)
  expect(new Set(seqs).size).toBe(20)
})
