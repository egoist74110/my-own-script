// 运行线路图：站点用目标名称、按 ADO 已创建的 Release/构建编号显示真实进度、日志空态三种文案
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import LogPanel from '@/features/tasks/LogPanel.vue'
import StepList from '@/features/tasks/StepList.vue'
import { buildStations, stepName } from '@/features/tasks/route'

type StepView = components['schemas']['StepView']
type EffectView = components['schemas']['EffectView']
type TargetInput = components['schemas']['TargetInput']

const step = (
  no: number,
  kind: string,
  status: StepView['status'],
  extra: Partial<StepView> = {},
): StepView => ({
  step_no: no,
  run_id: 'run-1',
  kind,
  status,
  started_at: status === 'pending' ? null : '2026-10-28T09:21:00Z',
  finished_at: status === 'succeeded' || status === 'failed' ? '2026-10-28T09:21:21Z' : null,
  checkpoint: {},
  target_index: kind === 'git' ? null : 0,
  ...extra,
})
const effect = (
  stepNo: number,
  kind: EffectView['kind'],
  remote: string | null,
  state: EffectView['state'] = 'confirmed',
): EffectView => ({
  confirmed_at: null,
  effect_id: `e-${stepNo}-${kind}`,
  error_category: null,
  intent: { kind } as EffectView['intent'],
  intent_at: '2026-10-28T09:21:00Z',
  intent_key: 'k',
  kind,
  owned: true,
  remote_id: remote,
  run_id: 'run-1',
  state,
  step_no: stepNo,
})
const targets: TargetInput[] = [
  {
    name: '测试',
    enabled: true,
    build_name: 'CG_Vue_Event - 构建',
    release_stage_names: ['新优惠-测试环境', '备用环境'],
  },
]

describe('站点标题用目标名称', () => {
  it('有目标名称：写“测试 · 构建 / 测试 · 发布”，副标题写构建定义名与环境名', () => {
    const st = buildStations(
      [step(1, 'git', 'succeeded'), step(2, 'build', 'succeeded'), step(3, 'release', 'running')],
      'running',
      Date.parse('2026-10-28T09:21:30Z'),
      { targets },
    )
    expect(st.map((s) => s.name)).toEqual(['Git 同步', '测试 · 构建', '测试 · 发布'])
    expect(st[1]!.detail).toBe('构建定义：CG_Vue_Event - 构建')
    expect(st[2]!.detail).toBe('环境：新优惠-测试环境、备用环境')
    expect(st[0]!.detail).toBeUndefined()
  })

  it('取不到名称（没有快照目标或名称为空）才回退“目标 N”', () => {
    expect(stepName({ kind: 'build', target_index: 0 })).toBe('目标 1 构建')
    expect(stepName({ kind: 'release', target_index: 1 }, '  ')).toBe('目标 2 发布')
    const st = buildStations([step(2, 'build', 'succeeded', { target_index: 1 })], 'succeeded', 0, {
      targets,
    })
    expect(st[0]!.name).toBe('目标 2 构建')
    expect(buildStations([step(2, 'build', 'succeeded')], 'succeeded')[0]!.name).toBe('目标 1 构建')
  })
})

describe('Release 已创建但没部署的站点', () => {
  const steps = [
    step(1, 'git', 'succeeded'),
    step(2, 'build', 'succeeded', {
      checkpoint: { build_id: 64778, url: 'https://ado.example/b/64778' },
    }),
    step(3, 'release', 'pending'),
  ]
  const effects = [effect(3, 'release_create', '11987')]

  it('步骤仍是 pending、运行失败：不显示“没有执行”，显示 Release #编号已创建 + 未部署 + 失败原因', () => {
    const st = buildStations(steps, 'failed', 0, { targets, effects, summary: '环境部署被拒绝' })
    const rel = st[2]!
    expect(rel.state).toBe('fail')
    expect(rel.sub).toBe('Release #11987 已创建，未部署：环境部署被拒绝')
    expect(rel.sub).not.toContain('没有执行')
  })

  it('部署中 / 已部署 / 部署失败 / 没创建时的“没有执行”', () => {
    const run = (status: StepView['status'], runStatus: 'running' | 'succeeded' | 'failed') =>
      buildStations([step(3, 'release', status)], runStatus, 0, {
        effects,
        summary: '超时',
      })[0]!.sub
    expect(run('running', 'running')).toContain('已创建，部署中')
    expect(run('succeeded', 'succeeded')).toContain('已创建，已部署')
    expect(run('failed', 'failed')).toBe('Release #11987 已创建，部署失败：超时')
    // 没有任何 release_create：保持原来的语义
    expect(buildStations([step(3, 'release', 'pending')], 'failed')[0]!.sub).toBe('没有执行')
  })

  it('构建站显示 #构建号，并有 ADO 链接（数据里有才有）', () => {
    const st = buildStations(steps, 'failed', 0, { targets, effects })
    expect(st[1]!.link).toBe('https://ado.example/b/64778')
    expect(st[1]!.sub).toContain('#64778')
    const noLink = buildStations([step(2, 'build', 'failed')], 'failed', 0, {
      effects: [effect(2, 'build_create', '64778')],
      summary: '编译错误',
    })[0]!
    expect(noLink.link).toBeUndefined()
    expect(noLink.sub).toBe('#64778，构建失败：编译错误')
  })

  it('StepList 渲染：站名、副标题、Release 编号和链接', () => {
    const w = mount(StepList, {
      props: { steps, runStatus: 'failed', targets, effects, summary: '环境部署被拒绝' },
    })
    expect(w.get('[data-testid="station-name-3"]').text()).toBe('测试 · 发布')
    expect(w.get('[data-testid="station-sub-3"]').text()).toContain('Release #11987 已创建')
    expect(w.get('[data-testid="station-detail-3"]').text()).toContain('新优惠-测试环境')
    expect(w.get('[data-testid="station-link-2"]').attributes('href')).toBe(
      'https://ado.example/b/64778',
    )
  })
})

describe('日志面板空态', () => {
  const line = { seq: 1, text: 'hello' }
  it('运行中且无日志：正在等待执行器输出，并隐藏“共 0 行日志”', () => {
    const w = mount(LogPanel, { props: { lines: [], runStatus: 'running' } })
    expect(w.get('[data-testid="log-empty"]').text()).toBe('正在等待执行器输出…')
    expect(w.text()).not.toContain('行日志')
  })
  it('已结束且无日志：这次运行没有记录日志，提示看步骤详情', () => {
    const w = mount(LogPanel, { props: { lines: [], runStatus: 'failed' } })
    expect(w.get('[data-testid="log-empty"]').text()).toContain('这次运行没有记录日志')
    expect(w.get('[data-testid="log-empty"]').text()).toContain('步骤详情')
    expect(w.text()).not.toContain('共 0 行日志')
  })
  it('有日志：显示行数；读取中仍显示读取提示', () => {
    const w = mount(LogPanel, { props: { lines: [line], runStatus: 'succeeded' } })
    expect(w.text()).toContain('共 1 行日志')
    expect(w.find('[data-testid="log-empty"]').exists()).toBe(false)
    const l = mount(LogPanel, { props: { lines: [], loading: true, runStatus: 'running' } })
    expect(l.text()).toContain('正在读取日志')
  })
})
