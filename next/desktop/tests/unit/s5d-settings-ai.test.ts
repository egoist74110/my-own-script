// S5-D：设置页「AI CLI」分区单测
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import { err, json, makeSettings, type Call } from './settings-fake'

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

const FAKE_PROFILES = [
  {
    id: 'prof-claude',
    name: 'Claude Code',
    cli: 'claude',
    command: 'claude',
    upgrade_command: 'npm i -g @anthropic-ai/claude-code',
    builtin: true,
    resolved: {
      ok: true,
      path: '/usr/local/bin/claude',
      version: '1.0.0',
      path_hint: '/usr/local/bin/claude',
    },
  },
  {
    id: 'prof-codex',
    name: 'Codex CLI',
    cli: 'codex',
    command: 'codex',
    upgrade_command: 'pip install -U codex',
    builtin: true,
    resolved: {
      ok: false,
      path: null,
      version: null,
      path_hint: '未在 PATH 找到 codex',
    },
  },
  {
    id: 'prof-custom',
    name: 'My Custom Runner',
    cli: 'other',
    command: '/opt/bin/custom-runner',
    upgrade_command: '',
    builtin: false,
    resolved: {
      ok: true,
      path: '/opt/bin/custom-runner',
      version: '0.9.0',
      path_hint: '/opt/bin/custom-runner',
    },
  },
]

interface FakeSettingsAiOpts {
  profiles?: ((typeof FAKE_PROFILES)[0] | unknown)[]
  modelPresets?: { claude?: string[]; codex?: string[]; agy?: string[] }
  storeState?: 'ready' | 'unavailable'
  onCheck?: (pid: string) => Response
  onUpgrade?: (pid: string) => Response
  onCancelJob?: (jid: string) => Response
  onCreateProfile?: (body: unknown) => Response
  onPatchProfile?: (pid: string, body: unknown) => Response
  onDeleteProfile?: (pid: string) => Response
  onPatchSettings?: (body: unknown) => Response
}

function createSettingsAiFetch(opts: FakeSettingsAiOpts = {}) {
  const profiles = opts.profiles ? [...opts.profiles] : [...FAKE_PROFILES]
  const calls: Call[] = []
  let revision = 10

  const handler = async (req: Request) => {
    const url = new URL(req.url)
    const method = req.method
    const pathname = url.pathname

    let body: unknown = null
    let raw = ''
    if (method === 'POST' || method === 'PATCH' || method === 'PUT') {
      try {
        raw = await req.clone().text()
        body = JSON.parse(raw)
      } catch {
        // raw body
      }
    }
    calls.push({
      method,
      path: pathname,
      query: Object.fromEntries(url.searchParams),
      body,
      raw,
    })

    if (pathname === '/health') {
      return json({ status: 'ok', version: '0.1.0', pid: 4242, uptime_s: 10, alert: false })
    }
    if (pathname === '/api/settings' && method === 'GET') {
      return json(makeSettings({ revision }))
    }
    if (pathname === '/api/ado' && method === 'GET') {
      return json({
        libraries: [],
        projects: [],
        local_repos: [],
        active_library_id: null,
        active_project_id: null,
        revision,
      })
    }
    if (pathname === '/api/credentials' && method === 'GET') {
      return json([])
    }
    if (pathname === '/api/ai' && method === 'GET') {
      return json({
        profiles,
        defaults: {
          claude: { permission: 'default', effort: null, model: null },
          codex: { sandbox: 'read-only', effort: 'medium', model: null },
          agy: { mode: 'sandbox', model: null },
        },
        analysis: {
          claude: { permission: 'plan' },
          codex: { sandbox: 'read-only' },
          agy: { mode: 'sandbox' },
        },
        model_presets: opts.modelPresets ?? {
          claude: ['claude-3-5-sonnet', 'claude-3-opus'],
          codex: ['gpt-5.3-codex'],
          agy: ['gemini-3.8-flash'],
        },
        store_state: opts.storeState ?? 'ready',
        revision,
      })
    }
    if (pathname.startsWith('/api/ai/profiles/') && pathname.endsWith('/check')) {
      const pid = pathname.split('/')[4]!
      if (opts.onCheck) return opts.onCheck(pid)
      return json({ ok: true, exit_code: 0, output: 'Claude Code 1.0.0 (darwin-arm64)' })
    }
    if (pathname.startsWith('/api/ai/profiles/') && pathname.endsWith('/upgrade')) {
      const pid = pathname.split('/')[4]!
      if (opts.onUpgrade) return opts.onUpgrade(pid)
      return json({ job_id: 'job-upgrade-1', status: 'started' })
    }
    if (pathname.startsWith('/api/ai/jobs/') && pathname.endsWith('/cancel')) {
      const jid = pathname.split('/')[4]!
      if (opts.onCancelJob) return opts.onCancelJob(jid)
      return json({ status: 'cancelled' })
    }
    if (pathname === '/api/ai/profiles' && method === 'POST') {
      if (opts.onCreateProfile) return opts.onCreateProfile(body)
      revision++
      const newProf = {
        id: 'prof-created',
        name: String((body as Record<string, unknown>).name ?? ''),
        cli: String((body as Record<string, unknown>).cli ?? 'other'),
        command: String((body as Record<string, unknown>).command ?? ''),
        upgrade_command: String((body as Record<string, unknown>).upgrade_command ?? ''),
        builtin: false,
        resolved: { ok: true, path: '/bin/custom', version: '1.0', path_hint: '/bin/custom' },
      }
      profiles.push(newProf)
      return json({ revision, profile: newProf }, 201)
    }
    if (pathname.startsWith('/api/ai/profiles/') && method === 'PATCH') {
      const pid = pathname.split('/')[4]!
      if (opts.onPatchProfile) return opts.onPatchProfile(pid, body)
      revision++
      return json({ revision }, 200)
    }
    if (pathname.startsWith('/api/ai/profiles/') && method === 'DELETE') {
      const pid = pathname.split('/')[4]!
      if (opts.onDeleteProfile) return opts.onDeleteProfile(pid)
      revision++
      return json({ revision }, 200)
    }
    if (pathname === '/api/ai/settings' && method === 'PATCH') {
      if (opts.onPatchSettings) return opts.onPatchSettings(body)
      revision++
      return json({ revision }, 200)
    }

    return json({ detail: 'not found' }, 404)
  }

  return { fetch: handler as unknown as typeof fetch, calls, getRev: () => revision }
}

async function openAiSettings(fake: ReturnType<typeof createSettingsAiFetch>) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  await flushPromises()
  await flushPromises()

  // 切换到 AI CLI 页签
  const tabs = b.wrapper.findAll('[role=tab]')
  const aiTab = tabs.find((t) => t.text().includes('AI CLI'))!
  expect(aiTab).toBeDefined()
  await aiTab.trigger('mousedown')
  await flushPromises()
  await flushPromises()

  return b
}

describe('S5-D 设置页「AI CLI」分区', () => {
  it('页签渲染并展示 Profiles 列表、resolved 状态与内置不可删除', async () => {
    const fake = createSettingsAiFetch()
    const b = await openAiSettings(fake)

    const tabContent = b.wrapper.find('[data-testid="ai-cli-tab"]')
    expect(tabContent.exists()).toBe(true)

    // 检查行渲染
    const rowClaude = b.wrapper.find('[data-testid="profile-row-prof-claude"]')
    expect(rowClaude.exists()).toBe(true)
    expect(rowClaude.text()).toContain('Claude Code')
    expect(rowClaude.text()).toContain('内置')
    expect(rowClaude.text()).toContain('claude')
    expect(rowClaude.text()).toContain('可执行')
    expect(rowClaude.text()).toContain('(1.0.0)')

    // 内置配置的删除按钮应为 disabled 且有提示
    const delClaudeBtn = b.wrapper.get('[data-testid="delete-profile-btn-prof-claude"]')
    expect(delClaudeBtn.attributes('disabled')).toBeDefined()
    expect(delClaudeBtn.attributes('title')).toBe('内置配置不可删除')

    // Codex 未在 PATH 找到
    const rowCodex = b.wrapper.find('[data-testid="profile-row-prof-codex"]')
    expect(rowCodex.text()).toContain('不可执行')
    expect(rowCodex.text()).toContain('未在 PATH 找到 codex')

    // 自定义配置可删除
    const delCustomBtn = b.wrapper.get('[data-testid="delete-profile-btn-prof-custom"]')
    expect(delCustomBtn.attributes('disabled')).toBeUndefined()

    await b.done()
  })

  it('“检测”按钮调用 POST /api/ai/profiles/{pid}/check 并显示退出码与输出', async () => {
    let checkedPid = ''
    const fake = createSettingsAiFetch({
      onCheck: (pid) => {
        checkedPid = pid
        return json({
          ok: true,
          exit_code: 0,
          output: 'claude version 1.0.0 (darwin-arm64)',
        })
      },
    })
    const b = await openAiSettings(fake)

    await b.wrapper.get('[data-testid="check-profile-btn-prof-claude"]').trigger('click')
    await flushPromises()

    expect(checkedPid).toBe('prof-claude')

    const outputPre = document.querySelector('[data-testid="check-output"]')
    expect(outputPre).not.toBeNull()
    expect(outputPre!.textContent).toContain('claude version 1.0.0')

    await b.done()
  })

  it('“升级”按钮经 Sheet 确认调用 POST upgrade，接收 WS ai.job 实时输出与取消', async () => {
    let upgradedPid = ''
    let cancelledJid = ''
    const fake = createSettingsAiFetch({
      onUpgrade: (pid) => {
        upgradedPid = pid
        return json({ job_id: 'job-up-99', status: 'started' })
      },
      onCancelJob: (jid) => {
        cancelledJid = jid
        return json({ status: 'cancelled' })
      },
    })
    const b = await openAiSettings(fake)

    // 点击 Claude 升级
    await b.wrapper.get('[data-testid="upgrade-profile-btn-prof-claude"]').trigger('click')
    await flushPromises()

    const promptText = document.querySelector('.upgrade-prompt')
    expect(promptText).not.toBeNull()
    expect(promptText!.textContent).toContain('npm i -g @anthropic-ai/claude-code')

    // 确认升级
    const confirmBtn = document.querySelector(
      '[data-testid="confirm-upgrade-btn"]',
    ) as HTMLButtonElement
    expect(confirmBtn).not.toBeNull()
    confirmBtn.click()
    await flushPromises()

    expect(upgradedPid).toBe('prof-claude')

    // 模拟后端推送 WS ai.job 进度与日志输出
    b.sock.emit(
      env(
        'ai.job',
        {
          job_id: 'job-up-99',
          state: 'running',
          output: 'fetching @anthropic-ai/claude-code\ndownloading packages...',
        },
        { topic: 'ai' },
      ),
    )
    await flushPromises()

    const outputBox = document.querySelector('[data-testid="upgrade-output"]')
    expect(outputBox).not.toBeNull()
    expect(outputBox!.textContent).toContain('downloading packages...')

    // 取消升级
    const cancelBtn = document.querySelector('[data-testid="cancel-job-btn"]') as HTMLButtonElement
    expect(cancelBtn).not.toBeNull()
    cancelBtn.click()
    await flushPromises()

    expect(cancelledJid).toBe('job-up-99')

    await b.done()
  })

  it('同时只允许一个升级任务，后端返回 409 时提示', async () => {
    const fake = createSettingsAiFetch({
      onUpgrade: () => err(409, 'busy', 'Another job is running'),
    })
    const b = await openAiSettings(fake)

    await b.wrapper.get('[data-testid="upgrade-profile-btn-prof-claude"]').trigger('click')
    await flushPromises()

    const confirmBtn = document.querySelector(
      '[data-testid="confirm-upgrade-btn"]',
    ) as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    const dialog = document.querySelector('[data-testid="upgrade-dialog"]')
    expect(dialog?.textContent).toContain('已有 AI 升级任务正在运行')

    await b.done()
  })

  it('添加自定义 profile 与 revision 409 冲突处理', async () => {
    let createCalled = false
    const fake = createSettingsAiFetch({
      onCreateProfile: (body) => {
        createCalled = true
        const b = body as Record<string, unknown>
        expect(b.name).toBe('Custom Runner 2')
        expect(b.cli).toBe('other')
        expect(b.command).toBe('/usr/bin/custom')
        return json({ revision: 11, profile: { id: 'prof-2', ...b } }, 201)
      },
    })
    const b = await openAiSettings(fake)

    await b.wrapper.get('[data-testid="add-profile-btn"]').trigger('click')
    await flushPromises()

    const form = document.querySelector('[data-testid="profile-form"]')
    expect(form).not.toBeNull()

    const nameInput = document.querySelector(
      '[data-testid="profile-name-input"] input',
    ) as HTMLInputElement
    const cmdInput = document.querySelector(
      '[data-testid="profile-cmd-input"] input',
    ) as HTMLInputElement

    nameInput.value = 'Custom Runner 2'
    nameInput.dispatchEvent(new Event('input'))
    cmdInput.value = '/usr/bin/custom'
    cmdInput.dispatchEvent(new Event('input'))
    await flushPromises()

    const saveBtn = document.querySelector('[data-testid="save-profile-btn"]') as HTMLButtonElement
    saveBtn.click()
    await flushPromises()

    expect(createCalled).toBe(true)
    await b.done()
  })

  it('选择高权限档位时显示醒目风险说明 (已决4)', async () => {
    const fake = createSettingsAiFetch()
    const b = await openAiSettings(fake)

    // 初始 Claude 为 default，无高危提示
    expect(b.wrapper.find('[data-testid="high-risk-tier-banner"]').exists()).toBe(false)

    // 选中 Claude bypassPermissions
    const claudeSelect = b.wrapper.get('[data-testid="claude-perm-select"]')
    await claudeSelect.setValue('bypassPermissions')
    await flushPromises()

    const warnBanner = b.wrapper.find('[data-testid="high-risk-tier-banner"]')
    expect(warnBanner.exists()).toBe(true)
    expect(warnBanner.text()).toContain('高权限档位风险提示')
    expect(warnBanner.text()).toContain('bypassPermissions')

    await b.done()
  })

  it('模型预设输入正则格式校验', async () => {
    const fake = createSettingsAiFetch()
    const b = await openAiSettings(fake)

    const claudePresets = b.wrapper.get('[data-testid="claude-presets-textarea"]')
    // 输入含有非法字符的模型名（例如以 @ 开头或包含非法特殊符号）
    await claudePresets.setValue('@invalid-model-name#!!!')
    await flushPromises()

    await b.wrapper.get('[data-testid="save-ai-settings-btn"]').trigger('click')
    await flushPromises()

    const banner = b.wrapper.find('[data-testid="settings-error-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('Claude 模型预设格式不合规')

    await b.done()
  })

  it('键盘可达性：Esc 可关闭检测 Sheet 与添加 Profile Sheet', async () => {
    const fake = createSettingsAiFetch()
    const b = await openAiSettings(fake)

    // 1. 打开检测 Sheet
    await b.wrapper.get('[data-testid="check-profile-btn-prof-claude"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-testid="check-dialog"]')).not.toBeNull()

    // Esc 关闭
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(document.querySelector('[data-testid="check-dialog"]')).toBeNull()

    // 2. 打开添加 Profile Sheet
    await b.wrapper.get('[data-testid="add-profile-btn"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-testid="profile-form"]')).not.toBeNull()

    // Esc 关闭
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(document.querySelector('[data-testid="profile-form"]')).toBeNull()

    await b.done()
  })
})

describe('S5-D1 第 2 轮回归测试 (S5D-T04, S5D-T05, S5D-T06, S5D-T07)', () => {
  it('S5D-T04 回归：保存设置时必须保留后端返回的 Antigravity 模型预设与未编辑字段', async () => {
    let patchedBody: Record<string, unknown> | null = null
    const fake = createSettingsAiFetch({
      modelPresets: {
        claude: ['claude-3-5-sonnet'],
        codex: ['gpt-5.3-codex'],
        agy: ['gemini-3.8-flash', 'gemini-3.8-pro'],
      },
      onPatchSettings: (body) => {
        patchedBody = body as Record<string, unknown>
        return json({ status: 'ok', revision: 11 })
      },
    })
    const b = await openAiSettings(fake)

    await b.wrapper.get('[data-testid="save-ai-settings-btn"]').trigger('click')
    await flushPromises()

    expect(patchedBody).not.toBeNull()
    const presets = (patchedBody as unknown as { model_presets: { agy: string[] } }).model_presets
    expect(presets.agy).toEqual(['gemini-3.8-flash', 'gemini-3.8-pro'])

    await b.done()
  })

  it('S5D-T05 回归：升级确认按钮快速连击时同步重入保护，只发送一次 POST', async () => {
    let upgradeCalls = 0
    let resolveUpgrade!: (r: Response) => void
    const fake = createSettingsAiFetch({
      onUpgrade: () => {
        upgradeCalls++
        return new Promise<Response>((resolve) => {
          resolveUpgrade = resolve
        }) as unknown as Response
      },
    })
    const b = await openAiSettings(fake)

    // 打开内置 Profile 的升级弹窗
    await b.wrapper.get('[data-testid="upgrade-profile-btn-prof-claude"]').trigger('click')
    await flushPromises()

    const confirmBtn = document.querySelector(
      '[data-testid="confirm-upgrade-btn"]',
    ) as HTMLButtonElement
    expect(confirmBtn).not.toBeNull()

    // 快速连点两次
    confirmBtn.click()
    confirmBtn.click()
    await flushPromises()

    expect(upgradeCalls).toBe(1)

    // 解除挂起
    resolveUpgrade(json({ job_id: 'job-upgrade-reentry' }))
    await flushPromises()

    await b.done()
  })

  it('S5D-T06 回归：ai.job 早到事件在 POST 返回前到达时不丢失，合并后状态为终态', async () => {
    let resolveUpgrade!: (r: Response) => void
    const fake = createSettingsAiFetch({
      onUpgrade: () =>
        new Promise<Response>((resolve) => {
          resolveUpgrade = resolve
        }) as unknown as Response,
    })
    const b = await openAiSettings(fake)

    await b.wrapper.get('[data-testid="upgrade-profile-btn-prof-claude"]').trigger('click')
    await flushPromises()

    const confirmBtn = document.querySelector(
      '[data-testid="confirm-upgrade-btn"]',
    ) as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    // 作业先于 HTTP 响应结束，WS 事件提前到达
    b.sock.emit(
      env(
        'ai.job',
        {
          job_id: 'job-early-1',
          state: 'succeeded',
          exit_code: 0,
          output: 'Upgrade succeeded early!',
        },
        { topic: 'ai' },
      ),
    )
    await flushPromises()

    // HTTP 响应返回
    resolveUpgrade(json({ job_id: 'job-early-1' }))
    await flushPromises()

    const jobBox = document.querySelector('[data-testid="upgrade-job-box"]')
    expect(jobBox).not.toBeNull()
    const stateEl = jobBox?.querySelector('.job-state')
    expect(stateEl?.getAttribute('data-state')).toBe('succeeded')
    expect(document.querySelector('[data-testid="upgrade-output"]')?.textContent).toContain(
      'Upgrade succeeded early!',
    )

    await b.done()
  })

  it('S5D-T07 回归：后端 profiles 列表包含 null 或非对象脏数据时安全过滤并提示，不崩溃', async () => {
    const fake = createSettingsAiFetch({
      profiles: [FAKE_PROFILES[0], null, 'dirty-string-profile', FAKE_PROFILES[2]],
    })
    const b = await openAiSettings(fake)

    // 页面正常渲染，未崩溃
    expect(b.wrapper.find('[data-testid="ai-cli-tab"]').exists()).toBe(true)
    // 渲染提示横幅
    const banner = document.querySelector('[data-testid="invalid-profiles-banner"]')
    expect(banner).not.toBeNull()
    expect(banner?.textContent).toContain('无效配置项')
    // 有效 profile 正常展示
    expect(document.body.textContent).toContain('Claude Code')

    await b.done()
  })
})
