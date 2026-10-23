// S5-D 独立测试（测试员）：设置页「AI CLI」分区的内置配置保护、冲突、升级任务、高权限提示与后端数据容错。
// 设置上下文以替身注入（不走真实 HTTP）；事件通过 runtime.onEvent 手工投递。
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { backendRuntimeKey } from '@/app/backend-runtime'
import type { EventEnvelope } from '@/api/events'
import AiCliTab from '@/features/settings/AiCliTab.vue'
import { settingsContextKey } from '@/features/settings/useSettings'

type Listener = (e: EventEnvelope) => void

function profile(over: Record<string, unknown> = {}) {
  return {
    id: 'custom_1',
    name: '自定义 CLI',
    cli: 'other',
    command: 'my-cli --run',
    upgrade_command: 'my-cli --upgrade',
    builtin: false,
    warnings: [],
    resolved: { ok: true, path_hint: 'my-cli', version: '1.0' },
    ...over,
  }
}

function aiView(over: Record<string, unknown> = {}) {
  return {
    revision: 7,
    profiles: [
      profile({
        id: 'claude_code',
        name: 'Claude Code',
        cli: 'claude',
        command: 'claude',
        builtin: true,
        upgrade_command: 'claude update',
      }),
      profile({
        id: 'codex',
        name: 'Codex',
        cli: 'codex',
        command: 'codex',
        builtin: true,
        upgrade_command: 'codex upgrade',
      }),
      profile({
        id: 'gemini',
        name: 'Antigravity',
        cli: 'agy',
        command: 'agy',
        builtin: true,
        upgrade_command: '',
      }),
      profile(),
    ],
    selected_profile_id: 'claude_code',
    defaults: {
      claude: { permission: 'auto', effort: null, model: null },
      codex: { sandbox: 'workspace-write', effort: 'medium', model: null },
      agy: { mode: 'sandbox', model: null },
    },
    analysis: {
      claude: { permission: 'plan' },
      codex: { sandbox: 'read-only' },
      agy: { mode: 'sandbox' },
    },
    model_presets: { claude: [], codex: [], agy: [] },
    store_state: 'ready',
    warnings: [],
    limits: {},
    ...over,
  }
}

const mounted: Array<{ unmount: () => void }> = []
afterEach(() => {
  for (const m of mounted.splice(0)) m.unmount()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

function makeCtx(view: unknown, fns: Record<string, unknown> = {}) {
  return {
    ai: { data: ref(view), isLoading: ref(false), isError: ref(false), error: ref(null) },
    aiTabActive: ref(false),
    busy: ref(false),
    writable: ref(true),
    checkAiProfile: vi.fn(async () => ({ ok: true, output: 'ok', exit_code: 0 })),
    createAiProfile: vi.fn(async () => undefined),
    patchAiProfile: vi.fn(async () => undefined),
    deleteAiProfile: vi.fn(async () => undefined),
    upgradeAiProfile: vi.fn(async () => ({ job_id: 'aij_1' })),
    cancelAiJob: vi.fn(async () => ({ job_id: 'aij_1' })),
    patchAiSettings: vi.fn(async () => undefined),
    ...fns,
  }
}

function setup(view: unknown, fns: Record<string, unknown> = {}) {
  const listeners: Listener[] = []
  const ctx = makeCtx(view, fns)
  const runtime = {
    api: () => null,
    getConnection: () => ({ port: 1, token: 'FAKE-TOKEN-settings' }),
    start() {},
    stop() {},
    send: () => false,
    subscribeRun: () => false,
    unsubscribeRun: () => false,
    onEvent: (l: Listener) => {
      listeners.push(l)
      return () => {}
    },
  }
  const w = mount(AiCliTab, {
    global: {
      provide: {
        [settingsContextKey as symbol]: ctx as never,
        [backendRuntimeKey as symbol]: runtime as never,
      },
    },
    attachTo: document.body,
  })
  mounted.push(w)
  const emit = (type: string, data: object) => {
    for (const l of listeners) {
      l({ seq: 1, topic: 'ai', type, ts: '2026-10-23T10:00:00Z', data } as unknown as EventEnvelope)
    }
  }
  return { w, ctx, emit }
}

const q = (sel: string) => document.querySelector(sel) as HTMLElement | null

describe('S5-D 独立：内置配置保护', () => {
  it('内置配置的删除按钮不可用（三种内置 id 均然）', async () => {
    setup(aiView())
    await flushPromises()
    for (const id of ['claude_code', 'codex', 'gemini']) {
      const btn = q(`[data-testid="delete-profile-btn-${id}"]`) as HTMLButtonElement | null
      expect(btn, id).not.toBeNull()
      expect(btn!.disabled, id).toBe(true)
    }
    expect((q('[data-testid="delete-profile-btn-custom_1"]') as HTMLButtonElement).disabled).toBe(
      false,
    )
  })
})

describe('S5-D 独立：revision 冲突与未提交输入', () => {
  it('删除时 revision 冲突：提示刷新、确认框保持打开', async () => {
    const { w, ctx } = setup(aiView(), {
      deleteAiProfile: vi.fn(
        async (_id: string, _h: unknown, opts: { onConflict: () => boolean }) => {
          opts.onConflict()
        },
      ),
    })
    await flushPromises()
    ;(q('[data-testid="delete-profile-btn-custom_1"]') as HTMLButtonElement).click()
    await flushPromises()
    ;(q('[data-testid="confirm-delete-profile-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(ctx.deleteAiProfile).toHaveBeenCalledTimes(1)
    expect(document.body.textContent).toContain('配置已被修改，请刷新后重试')
    expect(q('[data-testid="confirm-delete-profile-btn"]')).not.toBeNull()
    expect(w.exists()).toBe(true)
  })

  it('保存配置遇到 revision 冲突：表单输入保留，错误可见，不关闭表单', async () => {
    const { ctx } = setup(aiView(), {
      createAiProfile: vi.fn(
        async (_body: unknown, _h: unknown, opts: { onConflict: () => boolean }) => {
          opts.onConflict()
        },
      ),
    })
    await flushPromises()
    ;(q('[data-testid="add-profile-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    const name = q('[data-testid="profile-name-input"] input') as HTMLInputElement
    const cmd = q('[data-testid="profile-cmd-input"] input') as HTMLInputElement
    name.value = '我的新配置'
    name.dispatchEvent(new Event('input'))
    cmd.value = 'my-new --run'
    cmd.dispatchEvent(new Event('input'))
    await flushPromises()
    ;(q('[data-testid="save-profile-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(ctx.createAiProfile).toHaveBeenCalledTimes(1)
    expect(q('[data-testid="profile-form"]')).not.toBeNull()
    expect((q('[data-testid="profile-name-input"] input') as HTMLInputElement).value).toBe(
      '我的新配置',
    )
    expect((q('[data-testid="profile-cmd-input"] input') as HTMLInputElement).value).toBe(
      'my-new --run',
    )
    expect(document.body.textContent).toContain('配置已被修改，请重试')
  })

  it('模型名不合规时不发送保存请求（客户端先拦截）', async () => {
    const { ctx } = setup(aiView())
    await flushPromises()
    const input = q('#claude-model-input input') as HTMLInputElement | null
    expect(input).not.toBeNull()
    if (input) {
      input.value = 'bad model;rm -rf'
      input.dispatchEvent(new Event('input'))
    }
    await flushPromises()
    ;(q('[data-testid="save-ai-settings-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(ctx.patchAiSettings).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('默认模型名不合规')
  })
})

describe('S5-D 独立：升级任务', () => {
  it('升级需先经确认：点击升级按钮不发请求，确认后才发送一次', async () => {
    const { ctx } = setup(aiView())
    await flushPromises()
    ;(q('[data-testid="upgrade-profile-btn-custom_1"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(ctx.upgradeAiProfile).not.toHaveBeenCalled()
    ;(q('[data-testid="confirm-upgrade-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(ctx.upgradeAiProfile).toHaveBeenCalledTimes(1)
  })

  it('确认按钮被快速连点两次：只发出一次升级请求', async () => {
    let release!: (v: unknown) => void
    const { ctx } = setup(aiView(), {
      upgradeAiProfile: vi.fn(() => new Promise((r) => (release = r))),
    })
    await flushPromises()
    ;(q('[data-testid="upgrade-profile-btn-custom_1"]') as HTMLButtonElement).click()
    await flushPromises()
    const btn = q('[data-testid="confirm-upgrade-btn"]') as HTMLButtonElement
    btn.click()
    btn.click()
    await flushPromises()
    expect(ctx.upgradeAiProfile).toHaveBeenCalledTimes(1)
    release({ job_id: 'aij_1' })
    await flushPromises()
  })

  it('另一升级任务占用（409 busy）显示固定中文提示', async () => {
    setup(aiView(), {
      upgradeAiProfile: vi.fn(async () => {
        throw Object.assign(new Error('RAW_BUSY_DETAIL'), { code: 'busy', status: 409 })
      }),
    })
    await flushPromises()
    ;(q('[data-testid="upgrade-profile-btn-custom_1"]') as HTMLButtonElement).click()
    await flushPromises()
    ;(q('[data-testid="confirm-upgrade-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    const text = q('[data-testid="upgrade-dialog"]')?.textContent ?? ''
    expect(text).toContain('同时只允许一个升级任务')
    expect(text).not.toContain('RAW_BUSY_DETAIL')
  })

  it('ai.job 终态事件先于升级请求返回到达时，任务状态仍应为终态（不得永远停留在运行中）', async () => {
    let release!: (v: unknown) => void
    const { emit } = setup(aiView(), {
      upgradeAiProfile: vi.fn(() => new Promise((r) => (release = r))),
    })
    await flushPromises()
    ;(q('[data-testid="upgrade-profile-btn-custom_1"]') as HTMLButtonElement).click()
    await flushPromises()
    ;(q('[data-testid="confirm-upgrade-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    // 作业很快结束，事件在 HTTP 响应返回之前到达
    emit('ai.job', { job_id: 'aij_1', state: 'succeeded', exit_code: 0, output: 'upgraded' })
    release({ job_id: 'aij_1' })
    await flushPromises()
    expect(q('[data-testid="upgrade-job-box"] .job-state')?.getAttribute('data-state')).toBe(
      'succeeded',
    )
  })

  it('ai.job 只接受当前任务 id 的事件，其他任务的输出不混入', async () => {
    const { emit } = setup(aiView())
    await flushPromises()
    ;(q('[data-testid="upgrade-profile-btn-custom_1"]') as HTMLButtonElement).click()
    await flushPromises()
    ;(q('[data-testid="confirm-upgrade-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    emit('ai.job', { job_id: 'aij_OTHER', state: 'failed', exit_code: 1, output: 'FOREIGN' })
    await flushPromises()
    expect(q('[data-testid="upgrade-output"]')?.textContent ?? '').not.toContain('FOREIGN')
  })

  it('ai.job 输出上限：超长输出只保留末尾 256 KiB 以内', async () => {
    const { emit } = setup(aiView())
    await flushPromises()
    ;(q('[data-testid="upgrade-profile-btn-custom_1"]') as HTMLButtonElement).click()
    await flushPromises()
    ;(q('[data-testid="confirm-upgrade-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    const big = 'a'.repeat(300_000) + 'TAIL_MARK'
    emit('ai.job', { job_id: 'aij_1', state: 'running', output: big })
    await flushPromises()
    const shown = q('[data-testid="upgrade-output"]')?.textContent ?? ''
    expect(shown.length).toBeLessThanOrEqual(262144)
    expect(shown).toContain('TAIL_MARK')
  })

  it('取消升级幂等：重复点击取消不产生错误提示', async () => {
    const { ctx, emit } = setup(aiView())
    await flushPromises()
    ;(q('[data-testid="upgrade-profile-btn-custom_1"]') as HTMLButtonElement).click()
    await flushPromises()
    ;(q('[data-testid="confirm-upgrade-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    emit('ai.job', { job_id: 'aij_1', state: 'running', output: '' })
    await flushPromises()
    const cancel = q('[data-testid="cancel-job-btn"]') as HTMLButtonElement
    cancel.click()
    await flushPromises()
    cancel.click()
    await flushPromises()
    expect(ctx.cancelAiJob).toHaveBeenCalledTimes(2)
    expect(q('[data-testid="upgrade-dialog"] [role="alert"]')).toBeNull()
  })
})

describe('S5-D 独立：高权限档位提示与后端数据容错', () => {
  it('默认档位不显示高权限提示；选择高危档位后显示', async () => {
    const plain = setup(aiView())
    await flushPromises()
    expect(q('[data-testid="high-risk-tier-banner"]')).toBeNull()
    plain.w.unmount()
    mounted.splice(mounted.indexOf(plain.w), 1)
    document.body.innerHTML = ''

    const danger = setup(
      aiView({
        defaults: {
          claude: { permission: 'bypassPermissions', effort: null, model: null },
          codex: { sandbox: 'danger-full-access', effort: 'medium', model: null },
          agy: { mode: 'auto', model: null },
        },
      }),
    )
    await flushPromises()
    expect(q('[data-testid="high-risk-tier-banner"]')).not.toBeNull()
    danger.w.unmount()
  })

  it('后端返回未知枚举值与非对象字符串 profile 项时界面不崩溃', async () => {
    const view = aiView({
      defaults: {
        claude: { permission: 'future_mode', effort: 'ultra', model: null },
        codex: { sandbox: 'future-sandbox', effort: 'turbo', model: null },
        agy: { mode: 'future', model: null },
      },
      analysis: { claude: { permission: 'future' }, codex: { sandbox: 'x' }, agy: { mode: 'y' } },
      profiles: [
        profile({ id: 'future_cli', name: '未来 CLI', cli: 'future_cli', resolved: { ok: false } }),
        'junk-string-profile',
      ],
    })
    setup(view)
    await flushPromises()
    expect(q('[data-testid="ai-cli-tab"]')).not.toBeNull()
    expect(document.body.textContent).toContain('未来 CLI')
  })

  it('后端 profile 列表含 null 项时界面不崩溃（JsonValue 合同允许）', async () => {
    const view = aiView({
      defaults: {
        claude: { permission: 'future_mode', effort: 'ultra', model: null },
        codex: { sandbox: 'future-sandbox', effort: 'turbo', model: null },
        agy: { mode: 'future', model: null },
      },
      analysis: { claude: { permission: 'future' }, codex: { sandbox: 'x' }, agy: { mode: 'y' } },
      profiles: [
        profile({ id: 'future_cli', name: '未来 CLI', cli: 'future_cli', resolved: { ok: false } }),
        'junk-string-profile',
        null,
      ],
    })
    setup(view)
    await flushPromises()
    expect(q('[data-testid="ai-cli-tab"]')).not.toBeNull()
    expect(document.body.textContent).toContain('未来 CLI')
  })

  it('保存设置时必须保留后端返回的 Antigravity 模型预设（不得静默清空）', async () => {
    const { ctx } = setup(
      aiView({ model_presets: { claude: [], codex: [], agy: ['gemini-3.8-flash'] } }),
    )
    await flushPromises()
    ;(q('[data-testid="save-ai-settings-btn"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(ctx.patchAiSettings).toHaveBeenCalledTimes(1)
    const body = (ctx.patchAiSettings.mock.calls[0] as unknown[])[0] as {
      model_presets: { agy: string[] }
    }
    expect(body.model_presets.agy).toEqual(['gemini-3.8-flash'])
  })
})
