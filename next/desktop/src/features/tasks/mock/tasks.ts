/**
 * 任务页 mock 数据（虚构）。页面只通过 useTasks() 取数；
 * 后续切片把这里换成对 /api/tasks 的 vue-query 调用即可，页面模板不变。
 */
import { ref } from 'vue'
import type { Stage, StageState } from '@/components/StageBar.vue'

export type TaskStatus = 'run' | 'queued' | 'done' | 'failed'
export type TaskResult = 'clear' | 'failed' | 'rollback'

export interface TaskLogLine {
  t: string
  msg: string
  tone?: 'ok' | 'bad'
}

export interface Task {
  id: string
  name: string
  branch: string
  target: string
  stages: Stage[]
  /** 告警态下该行的阶段（仅 errorOnAlert 的任务有）。 */
  alertStages?: Stage[]
  dur: string
  trigger: string
  status: TaskStatus
  result?: TaskResult
  favorite?: boolean
  /** 收到后端告警时，这一行标记为出错行（演示用）。 */
  errorOnAlert?: boolean
  build: string
  agent: string
  policy: string
  progress: number
  logs: TaskLogLine[]
  alertLogs?: TaskLogLine[]
}

const stage = (code: string, state: StageState): Stage => ({ code, state })
const four = (a: StageState, b: StageState, c: StageState, d: StageState): Stage[] => [
  stage('SYNC', a),
  stage('BUILD', b),
  stage('REL', c),
  stage('REL', d),
]

const baseLogs: TaskLogLine[] = [
  { t: '21:44:02', msg: 'git merge dev → main ✓', tone: 'ok' },
  { t: '21:44:20', msg: 'queue build #4127' },
  { t: '21:45:10', msg: 'npm ci ✓ 41s' },
  { t: '21:46:55', msg: 'vite build ✓ 2,184 modules' },
  { t: '21:47:58', msg: 'tests 412 passed', tone: 'ok' },
]

function seed(): Task[] {
  return [
    {
      id: 't1',
      name: 'web-portal 发布',
      branch: 'main @ 8d04e7b',
      target: 'staging-a → staging-b',
      stages: four('done', 'run', 'pending', 'pending'),
      alertStages: four('done', 'done', 'fail', 'pending'),
      dur: '4:12',
      trigger: '手动',
      status: 'run',
      errorOnAlert: true,
      favorite: true,
      build: '#4127 · web-portal-ci',
      agent: 'mac-pool-02',
      policy: '失败即停 · 串行',
      progress: 14,
      logs: [...baseLogs, { t: '21:48:12', msg: 'publish artifact …' }],
      alertLogs: [
        ...baseLogs,
        { t: '21:48:20', msg: 'release R-912 → staging-a' },
        { t: '21:48:31', msg: '✕ environment rejected', tone: 'bad' },
        { t: '21:48:31', msg: '— staging-b skipped (stop on failure)', tone: 'bad' },
      ],
    },
    mk(
      't2',
      'api-gateway 发布',
      'release/2.8',
      'prod',
      four('pending', 'pending', 'pending', 'pending'),
      '排队',
      'TG @owner',
      'queued',
    ),
    mk(
      't3',
      'mobile-bff 发布',
      'dev @ 1c9e',
      'staging',
      four('pending', 'pending', 'pending', 'pending'),
      '排队',
      '定时 22:00',
      'queued',
    ),
    mk(
      't4',
      'admin-console 仅发布',
      'main',
      'prod',
      four('done', 'done', 'done', 'done'),
      '2:08',
      'TG @owner',
      'done',
      'clear',
      true,
    ),
    mk(
      't5',
      'docs-site 发布',
      'main',
      'prod',
      four('done', 'done', 'done', 'done'),
      '1:46',
      '手动',
      'done',
      'clear',
    ),
    mk(
      't6',
      'mobile-bff 发布',
      'dev @ 77ab',
      'staging',
      four('done', 'fail', 'pending', 'pending'),
      '3:51',
      '手动',
      'failed',
      'failed',
    ),
    mk(
      't7',
      'data-sync 回滚',
      'main',
      'prod · offset 1',
      four('done', 'done', 'done', 'done'),
      '1:12',
      'TG @owner',
      'done',
      'rollback',
    ),
  ]
}

function mk(
  id: string,
  name: string,
  branch: string,
  target: string,
  stages: Stage[],
  dur: string,
  trigger: string,
  status: TaskStatus,
  result?: TaskResult,
  favorite?: boolean,
): Task {
  return {
    id,
    name,
    branch,
    target,
    stages,
    dur,
    trigger,
    status,
    result,
    favorite,
    build: `#${4100 + Number(id.slice(1))} · ${name.split(' ')[0]}-ci`,
    agent: 'mac-pool-01',
    policy: '失败即停 · 串行',
    progress: status === 'done' || status === 'failed' ? 20 : 0,
    logs: status === 'queued' ? [{ t: '--:--:--', msg: 'waiting in queue' }] : baseLogs,
  }
}

export interface RecentRun {
  name: string
  meta: string
  result: TaskResult
}

export function useTasks() {
  const tasks = ref<Task[]>(seed())
  let n = 0
  function addTask() {
    n += 1
    tasks.value.push(
      mk(
        `n${n}`,
        `新建任务 ${n}`,
        'main',
        'staging',
        four('pending', 'pending', 'pending', 'pending'),
        '排队',
        '手动',
        'queued',
      ),
    )
  }
  const runs: RecentRun[] = [
    { name: 'admin-console → prod 仅发布', meta: '20:31 · 2:08', result: 'clear' },
    { name: 'web-portal → staging 发布', meta: '19:02 · 7:44', result: 'clear' },
    { name: 'api-gateway → prod 回滚 1 版', meta: '17:15 · 1:12', result: 'rollback' },
    { name: 'mobile-bff → staging 发布', meta: '15:40 · 3:51', result: 'failed' },
  ]
  const kpis = [
    { label: 'Runs/wk', value: '86', delta: '+12' },
    { label: 'Success', value: '97.6%', delta: '评级 S' },
    { label: 'Avg', value: '6:14', delta: '−42s' },
  ]
  const bars = [30, 45, 38, 60, 52, 70, 48, 66, 58, 80, 62, 74, 69, 92]
  return { tasks, addTask, runs, kpis, bars }
}
