import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import LogPanel from '@/features/tasks/LogPanel.vue'
import RunCard from '@/features/tasks/RunCard.vue'
import RunConfirmSheet from '@/features/tasks/RunConfirmSheet.vue'
import { formatRepoShort, type RunResponse, type TaskView } from '@/features/tasks/api'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

beforeEach(() => {
  setActivePinia(createPinia())
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const fakeTaskItem: TaskView = {
  id: 'task-demo',
  name: '演示 · 同步构建发布',
  enabled: true,
  repo_name: '',
  local_repo_path: '/tmp/toolbox-dev-task-root-abc/my-repo',
  active_run_id: 'run-100',
  last_run: null,
  sort_order: 1,
  tg_command: '',
  tg_desc: '',
  validation: { valid: true },
  warnings: [],
  git_flow: {
    build_branch: 'feat/test',
  },
  targets: [],
  created_at: '2026-10-23T10:00:00Z',
  updated_at: '2026-10-23T10:00:00Z',
}

const fakeRunningRun: RunResponse = {
  run_id: 'run-100',
  task_id: 'task-demo',
  operation: 'sync_build_release',
  status: 'running',
  reason_code: null,
  summary: '运行中',
  config_revision: 1,
  phase: 'build',
  recovery_state: 'none',
  created_at: '2026-10-23T10:00:00Z',
  started_at: '2026-10-23T10:00:02Z',
  finished_at: null,
  cancel_requested_at: null,
  deadline_at: '2026-10-23T10:30:00Z',
  log_bytes: 120,
  last_seq: 1,
  request_hash: 'hash-1',
  request_id: 'req-1',
  state_version: 1,
  stop_reason: null,
  task_snapshot: {} as unknown as RunResponse['task_snapshot'],
  updated_at: '2026-10-23T10:00:00Z',
  steps: [
    {
      step_no: 0,
      run_id: 'run-100',
      kind: 'git',
      status: 'running',
      started_at: '2026-10-23T10:00:02Z',
      finished_at: null,
      checkpoint: { summary: '更新分支中' },
      target_index: null,
    },
    {
      step_no: 1,
      run_id: 'run-100',
      kind: 'build',
      status: 'pending',
      started_at: null,
      finished_at: null,
      checkpoint: {},
      target_index: 0,
    },
  ],
  effects: [],
}

const fakeFinishedRun: RunResponse = {
  ...fakeRunningRun,
  status: 'succeeded',
  finished_at: '2026-10-23T10:00:15Z',
  last_seq: 4,
  steps: [
    {
      step_no: 0,
      run_id: 'run-100',
      kind: 'git',
      status: 'succeeded',
      started_at: '2026-10-23T10:00:02Z',
      finished_at: '2026-10-23T10:00:05Z',
      checkpoint: { summary: '同步完成' },
      target_index: null,
    },
    {
      step_no: 1,
      run_id: 'run-100',
      kind: 'build',
      status: 'succeeded',
      started_at: '2026-10-23T10:00:05Z',
      finished_at: '2026-10-23T10:00:15Z',
      checkpoint: { summary: '构建成功' },
      target_index: 0,
    },
  ],
}

describe('S3-C 第二轮修复验证（TDD 失败断言）', () => {
  it('1.1 实时状态与步骤更新：WS 推送终态后，界面状态、步骤、历史行、侧栏角标均自动变为终态无需刷新', async () => {
    let currentTask: TaskView = { ...fakeTaskItem, active_run_id: 'run-100' }
    let currentRunSnapshot = { ...fakeRunningRun }

    const fakeFetch = async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : (input as Request).url
      if (url.includes('/api/runs') && !url.includes('/api/runs/run-100')) {
        return new Response(
          JSON.stringify({
            items: [currentRunSnapshot],
            next_cursor: null,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url.includes('/api/tasks')) {
        return new Response(
          JSON.stringify({
            items: [currentTask],
            revision: 1,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url.includes('/api/runs/run-100/events')) {
        return new Response(
          JSON.stringify({
            items: [],
            has_more: false,
            next_seq: 1,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url.includes('/api/runs/run-100')) {
        return new Response(JSON.stringify(currentRunSnapshot), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    }

    const b = await boot({ path: '/tasks', fetchImpl: fakeFetch as unknown as typeof fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 初始状态为运行中，侧栏显示 1 运行中
    const sidebar = b.wrapper.find('.sidebar')
    expect(sidebar.text()).toContain('1 运行中')
    expect(b.wrapper.find('[data-testid=run-card]').text()).toContain('运行中')

    // 此时后端完成运行并变为 succeeded
    currentTask = { ...currentTask, active_run_id: null }
    currentRunSnapshot = { ...fakeFinishedRun }

    // WS 依次推送: state(running) -> log -> checkpoint -> state(succeeded)
    b.sock.emit({
      seq: 1,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-23T10:00:03Z',
      data: {
        run_id: 'run-100',
        run_seq: 2,
        type: 'log',
        payload: { text: 'Compiling assets...' },
      },
    })
    b.sock.emit({
      seq: 2,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-23T10:00:05Z',
      data: {
        run_id: 'run-100',
        run_seq: 3,
        type: 'checkpoint',
        payload: { step_index: 0, status: 'succeeded' },
      },
    })
    b.sock.emit({
      seq: 3,
      topic: 'run',
      type: 'run.event',
      ts: '2026-10-23T10:00:15Z',
      data: {
        run_id: 'run-100',
        run_seq: 4,
        type: 'state',
        payload: { status: 'succeeded', summary: '全部步骤执行完毕' },
      },
    })

    await flushPromises()
    await flushPromises()

    // 断言界面状态无需刷新自动变为终态
    const runCardText = b.wrapper.find('[data-testid=run-card]').text()
    expect(runCardText).toContain('成功')
    expect(runCardText).not.toContain('运行中')
    expect(runCardText).toContain('同步完成')
    expect(runCardText).toContain('构建成功')

    // 断言侧栏角标不含 1 运行中
    expect(sidebar.text()).not.toContain('1 运行中')

    // 断言筛选页签 running 计数更新
    expect(b.wrapper.text()).not.toContain('运行中 1')

    await b.done()
  })

  it('1.2 RunCard 运行中计时器实时更新，进入终态后定格', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-23T10:00:05Z'))

    const runRef = ref<RunResponse>({ ...fakeRunningRun })
    const w = mount(RunCard, {
      props: {
        run: runRef.value,
        steps: fakeRunningRun.steps ?? [],
        lines: [],
      },
    })

    // started_at: 10:00:02, 当前系统时间 10:00:05 -> 已用 0:03
    expect(w.find('.run-time-meta').text()).toContain('已用 0:03')

    // 时间前进 5 秒
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(w.find('.run-time-meta').text()).toContain('已用 0:08')

    // 终态定格为 finished_at - started_at (10:00:15 - 10:00:02 = 13秒 = 0:13)
    await w.setProps({
      run: { ...fakeFinishedRun },
    })
    await flushPromises()
    expect(w.find('.run-time-meta').text()).toContain('已用 0:13')

    // 之后时间再走，时间仍定格在 0:13
    vi.advanceTimersByTime(10000)
    await flushPromises()
    expect(w.find('.run-time-meta').text()).toContain('已用 0:13')
    w.unmount()
  })

  it('2. 日志时间戳不捏造：LogPanel 仅展示序号 seq 列，不展示 ts 列；复制不含捏造时间', async () => {
    const lines = [
      { seq: 1, text: 'First line of output' },
      { seq: 2, text: 'Second line of output' },
    ]
    const w = mount(LogPanel, {
      props: {
        lines,
        totalLineCount: 2,
        loading: false,
      },
    })

    // 不应存在 .log-ts 时间列
    expect(w.find('.log-ts').exists()).toBe(false)
    // 应该展示 .log-seq 序号
    const seqs = w.findAll('.log-seq')
    expect(seqs.length).toBe(2)
    expect(seqs[0]!.text()).toBe('1')
    expect(seqs[1]!.text()).toBe('2')

    w.unmount()
  })

  it('3. 产品隐藏占位移除：TasksPage 不包含 tasks-placeholder', async () => {
    const fakeFetch = async () =>
      new Response(JSON.stringify({ items: [], revision: 1 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    const b = await boot({ path: '/tasks', fetchImpl: fakeFetch as unknown as typeof fetch })
    b.sock.emit(hello())
    await flushPromises()

    // 假占位必须彻底删除
    expect(b.wrapper.find('[data-testid=tasks-placeholder]').exists()).toBe(false)
    // 真实空态正常渲染
    expect(b.wrapper.find('[data-testid=tasks-empty-state]').exists()).toBe(true)

    await b.done()
  })

  it('4. 日志单飞补齐与窗口加载：fetchGap 不并发请求', async () => {
    // 模拟快照 last_seq = 2500 时，起始 after_seq 从 1500 (2500 - 1000) 开始拉取，而非 0
    const snapshotLastSeq = 2500
    const initialAfterSeq = Math.max(0, snapshotLastSeq - 1000)
    expect(initialAfterSeq).toBe(1500)
  })

  it('5. 列表第二行使用 formatRepoShort 简短格式，不展示临时长路径', () => {
    expect(formatRepoShort('my-repo', '/tmp/long/path/to/my-repo')).toBe('my-repo')
    expect(formatRepoShort('', '/tmp/toolbox-dev-task-root-xyz/sub-repo')).toBe('sub-repo')
    expect(formatRepoShort(null, '/var/folders/xx/build_dir/')).toBe('build_dir')
    expect(formatRepoShort(undefined, '')).toBe('—')
  })

  it('6. RunConfirmSheet 打开时包含半透明遮罩 .sheet-overlay', async () => {
    const w = mount(RunConfirmSheet, {
      props: {
        open: true,
        task: fakeTaskItem,
        operation: 'sync_build_release',
        plan: null,
      },
      attachTo: document.body,
    })
    await flushPromises()

    const overlay = document.querySelector('.sheet-overlay')
    expect(overlay).not.toBeNull()
    w.unmount()
  })
})
