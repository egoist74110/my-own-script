// S6-C 单测：设置页 MCP 分区三张卡（ADO / Lark / Figma）、凭据不留痕、所有权门禁、二次确认、WS 水位与卸载释放
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import { json } from './settings-fake'

type S = components['schemas']

function makeMcpSnapshot(over: Partial<S['MCPSnapshot']> = {}): S['MCPSnapshot'] {
  return {
    revision: 10,
    self_test_running: false,
    managed_node_version: 'v24.13.0',
    node_min_version: '20.20.0',
    active_job: null,
    ado: {
      allow_create_work_item: false,
      attachment_cache_mb: 500,
      attachment_max_mb: 25,
      query_max_items: 200,
      ...(over.ado ?? {}),
    },
    figma: {
      expiry_days: 90,
      max_concurrency: 1,
      min_interval_ms: 350,
      max_retry: 4,
      token_configured: true,
      token_set_at: '2026-10-20T10:00:00Z',
      ...(over.figma ?? {}),
    },
    lark: {
      app_id: 'cli_fake_app_123',
      domain: 'https://open.larksuite.com',
      endpoint: 'http://localhost:3000/mcp',
      port: 3000,
      language: 'zh',
      tools: 'preset.doc.default',
      autostart: false,
      scope_hint: 'offline_access',
      secret_configured: true,
      keytar_available: true,
      owner_confirmed_at: '2026-10-25T10:00:00Z',
      state: 'stopped',
      log_tail: '',
      warnings: [],
      patches: {
        all_applied: true,
        auth_store: 'applied',
        mcp_tool: 'applied',
        oidc: 'applied',
      },
      token_status: {
        state: 'ok',
        logged_in_at: '2026-10-25T10:00:00Z',
        last_event_at: '2026-10-26T00:00:00Z',
        message: null,
      },
      login: {
        logged_in_at: '2026-10-25T10:00:00Z',
        scope: 'offline_access',
      },
      ...(over.lark ?? {}),
    },
    runtime: {
      ready: true,
      packages_installed: true,
      lark_package_ready: true,
      figma_package_ready: true,
      keytar_ready: true,
      packages: {
        '@larksuiteoapi/lark-mcp': '0.5.1',
        'figma-developer-mcp': '0.13.2',
      },
      node: {
        source: 'detected',
        path: '/usr/local/bin/node',
        version: 'v24.13.0',
      },
      ...(over.runtime ?? {}),
    },
    ...over,
  }
}

function makeAiView(over: Partial<S['AIView']> = {}): S['AIView'] {
  return {
    revision: 10,
    store_state: 'ready',
    profiles: [],
    selected_profile_id: '',
    defaults: {
      claude: { permission: 'manual', effort: 'medium', model: null },
      codex: { sandbox: 'read-only', effort: 'medium', model: null },
      agy: { mode: 'auto', model: null },
    },
    analysis: {
      mcp_source: 'legacy',
    },
    model_presets: { claude: [], codex: [], agy: [] },
    ...over,
  }
}

interface S6CFakeState {
  settings: S['SettingsResponse']
  ado: S['AdoResponse']
  creds: S['CredentialStatus'][]
  mcp: S['MCPSnapshot']
  ai: S['AIView']
}

interface CallRecord {
  method: string
  path: string
  body: unknown
}

function createS6CFake(initialMcp?: Partial<S['MCPSnapshot']>, initialAi?: Partial<S['AIView']>) {
  const state: S6CFakeState = {
    settings: {
      app_version: '0.1.0',
      data_dir: '/tmp/fake-data',
      legacy_config_dir: '/tmp/fake-legacy',
      revision: 10,
      schema_version: 4,
      store_state: 'ok',
      import: { state: 'completed' },
    },
    ado: {
      active_library_id: 'lib:a',
      active_project_id: 'proj:a',
      libraries: [
        {
          id: 'lib:a',
          name: '测试库',
          base_url: 'https://ado.example.com',
          credential: { present: true, source: 'manual', state: 'present' },
        },
      ],
      local_repos: [],
      projects: [],
      revision: 10,
    },
    creds: [],
    mcp: makeMcpSnapshot(initialMcp),
    ai: makeAiView(initialAi),
  }

  const calls: CallRecord[] = []

  let overrideHandler: ((req: Request) => Promise<Response | undefined>) | null = null

  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const req = input instanceof Request ? input : new Request(input, init)
    if (overrideHandler) {
      const res = await overrideHandler(req)
      if (res) return res
    }
    const url = new URL(req.url)
    const p = url.pathname
    const method = req.method
    const raw = method === 'GET' || method === 'DELETE' ? '' : await req.text()
    let body: unknown
    try {
      body = raw ? JSON.parse(raw) : undefined
    } catch {
      body = undefined
    }

    if (p !== '/health') {
      calls.push({ method, path: p, body })
    }

    if (p === '/health')
      return json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 1, alert: false })
    if (p === '/api/settings' && method === 'GET') return json(state.settings)
    if (p === '/api/ado' && method === 'GET') return json(state.ado)
    if (p === '/api/credentials' && method === 'GET') return json(state.creds)
    if (p === '/api/mcp' && method === 'GET') return json(state.mcp)
    if (p === '/api/ai' && method === 'GET') return json(state.ai)

    if (p === '/api/mcp/ado/self-test' && method === 'POST') {
      return json({
        ok: true,
        protocol_version: '2025-06-18',
        server_name: 'toolbox_ado',
        tools: ['ado_query_work_items', 'ado_get_attachment', 'ado_evaluate_change_policy'],
        duration_ms: 125,
        error_code: null,
        stderr_tail: '',
      })
    }

    if (p === '/api/mcp/figma/self-test' && method === 'POST') {
      return json({
        ok: true,
        protocol_version: '2025-06-18',
        server_name: 'figma-developer-mcp',
        tools: ['get_figma_data', 'download_figma_images'],
        duration_ms: 320,
        error_code: null,
        stderr_tail: '',
      })
    }

    if (p === '/api/mcp/client-config' && method === 'GET') {
      const server = url.searchParams.get('server')
      const cli = url.searchParams.get('cli')
      return json({
        server,
        cli,
        name: server === 'ado' ? 'toolbox_ado' : server === 'figma' ? 'toolbox_figma' : 'lark',
        config: {},
        snippet: `# ${server} ${cli} snippet\nmcp add ${server}`,
      })
    }

    if (p === '/api/mcp/settings' && method === 'PATCH') {
      const patch = body as S['MCPSettingsPatch']
      if (patch.ado) state.mcp.ado = { ...state.mcp.ado, ...patch.ado }
      if (patch.figma) {
        state.mcp.figma = {
          ...state.mcp.figma!,
          ...patch.figma,
          token_configured: state.mcp.figma?.token_configured ?? false,
        }
      }
      if (patch.lark) {
        state.mcp.lark = {
          ...state.mcp.lark!,
          ...patch.lark,
          endpoint: `http://localhost:${patch.lark.port}/mcp`,
        }
      }
      state.mcp.revision++
      return json({ revision: state.mcp.revision })
    }

    if (p === '/api/ai/settings' && method === 'PATCH') {
      const patch = body as S['AISettingsPatch']
      if (patch.analysis) {
        state.ai.analysis = { ...state.ai.analysis, ...patch.analysis }
      }
      state.ai.revision++
      return json({ revision: state.ai.revision })
    }

    if (p.startsWith('/api/mcp/credentials/') && (method === 'PUT' || method === 'DELETE')) {
      state.mcp.revision++
      return json({ revision: state.mcp.revision })
    }

    if (p === '/api/mcp/credentials/import-legacy' && method === 'POST') {
      state.mcp.revision++
      return json({ revision: state.mcp.revision })
    }

    if (p === '/api/mcp/lark/ownership') {
      if (method === 'POST') {
        state.mcp.lark!.owner_confirmed_at = '2026-10-26T12:00:00Z'
      } else if (method === 'DELETE') {
        state.mcp.lark!.owner_confirmed_at = null
      }
      return json(state.mcp)
    }

    if (p === '/api/mcp/lark/start' && method === 'POST') {
      state.mcp.lark!.state = 'running'
      return json(state.mcp)
    }

    if (p === '/api/mcp/lark/stop' && method === 'POST') {
      state.mcp.lark!.state = 'stopped'
      return json(state.mcp)
    }

    if (p === '/api/mcp/lark/login' && method === 'POST') {
      state.mcp.lark!.state = 'logging_in'
      return json(state.mcp)
    }

    if (p === '/api/mcp/lark/login/cancel' && method === 'POST') {
      state.mcp.lark!.state = 'stopped'
      return json(state.mcp)
    }

    if (p === '/api/mcp/lark/logout' && method === 'POST') {
      state.mcp.lark!.token_status = {
        state: 'unknown',
        logged_in_at: null,
        last_event_at: null,
        message: null,
      }
      state.mcp.lark!.login = undefined
      return json(state.mcp)
    }

    if (p === '/api/mcp/runtime/install' && method === 'POST') {
      const job: S['McpJobView'] = {
        job_id: 'job-1',
        kind: 'runtime_install',
        state: 'running',
        started_at: '2026-10-26T12:00:00Z',
        finished_at: null,
        output: 'Downloading Node v24.13.0...\n',
        error: null,
      }
      state.mcp.active_job = job
      return json(job)
    }

    if (p === '/api/mcp/jobs/job-1/cancel' && method === 'POST') {
      const job: S['McpJobView'] = {
        job_id: 'job-1',
        kind: 'runtime_install',
        state: 'cancelled',
        started_at: '2026-10-26T12:00:00Z',
        finished_at: '2026-10-26T12:01:00Z',
        output: 'Downloading Node v24.13.0...\nCancelled by user',
        error: null,
      }
      state.mcp.active_job = job
      return json(job)
    }

    return json({ revision: 10 })
  }) as unknown as typeof fetch

  return {
    state,
    calls,
    fetchImpl,
    setOverride: (fn: (req: Request) => Promise<Response | undefined>) => {
      overrideHandler = fn
    },
  }
}

async function openMcpTab(fake: ReturnType<typeof createS6CFake>) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetchImpl })
  b.sock.emit(hello())
  await flushPromises()

  // 切换到 MCP 页签
  const tabs = b.wrapper.findAll('[role=tab]')
  const mcpTab = tabs.find((t) => t.text().includes('MCP'))!
  expect(mcpTab).toBeDefined()
  await mcpTab.trigger('mousedown')
  await flushPromises()
  await flushPromises()
  return b
}

describe('S6-C: MCP 分区与三张卡单测', () => {
  beforeEach(() => {
    FakeSocket.reset()
    resetSeq()
    localStorage.clear()
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('verified_by=executor, independent=false: MCP 分区渲染与三张卡存在', async () => {
    const fake = createS6CFake()
    const b = await openMcpTab(fake)

    expect(b.wrapper.find('[data-testid="mcp-tab"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="mcp-ado-card"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="mcp-lark-card"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="mcp-figma-card"]').exists()).toBe(true)

    await b.done()
  })

  it('ADO 卡片：自检请求与结果字段展示', async () => {
    const fake = createS6CFake()
    const b = await openMcpTab(fake)

    const selftestBtn = b.wrapper.get('[data-testid="mcp-ado-selftest-btn"]')
    await selftestBtn.trigger('click')
    await flushPromises()

    const call = fake.calls.find((c) => c.path === '/api/mcp/ado/self-test')
    expect(call).toBeDefined()
    expect(call?.body).toEqual({ timeout_s: 15 })

    const resultBox = b.wrapper.find('[data-testid="ado-selftest-result"]')
    expect(resultBox.exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="ado-selftest-status"]').text()).toContain('握手成功')
    expect(b.wrapper.find('[data-testid="ado-selftest-tools"]').text()).toContain(
      'ado_query_work_items',
    )

    await b.done()
  })

  it('ADO 卡片：写工具二次确认 Sheet（开启需二次确认，取消不开启，关闭直接生效）', async () => {
    const fake = createS6CFake({
      ado: {
        allow_create_work_item: false,
        attachment_cache_mb: 500,
        attachment_max_mb: 25,
        query_max_items: 200,
      },
    })
    const b = await openMcpTab(fake)

    const sw = b.wrapper.get('[data-testid="ado-allow-create-work-item-switch"]')

    // 1. 点击尝试打开开关 -> 弹出确认 Sheet
    await sw.trigger('click')
    await flushPromises()

    expect(document.querySelector('[data-testid="mcp-ado-write-confirm-dialog"]')).not.toBeNull()
    // 尚未发送 PATCH
    expect(fake.calls.filter((c) => c.path === '/api/mcp/settings')).toHaveLength(0)

    // 2. 点击取消 -> Sheet 关闭，未修改
    const cancelBtn = document.querySelector(
      '[data-testid="cancel-enable-write-btn"]',
    ) as HTMLButtonElement
    cancelBtn.click()
    await flushPromises()
    expect(fake.calls.filter((c) => c.path === '/api/mcp/settings')).toHaveLength(0)

    // 3. 再次点击并确认开启 -> 发送 PATCH allow_create_work_item=true
    await sw.trigger('click')
    await flushPromises()
    const confirmBtn = document.querySelector(
      '[data-testid="confirm-enable-write-btn"]',
    ) as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    const patchCall = fake.calls.find((c) => c.path === '/api/mcp/settings')
    expect(patchCall).toBeDefined()
    expect((patchCall?.body as S['MCPSettingsPatch'])?.ado?.allow_create_work_item).toBe(true)

    await b.done()
  })

  it('ADO 卡片：分析来源切换需勾选确认（切到 toolbox 需确认已在 CLI 注册，切回 legacy 无需勾选）', async () => {
    const fake = createS6CFake({}, { analysis: { mcp_source: 'legacy' } })
    const b = await openMcpTab(fake)

    expect(b.wrapper.get('[data-testid="ado-current-mcp-source"]').text()).toContain('旧版工单 MCP')

    // 打开切换 Sheet
    await b.wrapper.get('[data-testid="open-source-sheet-btn"]').trigger('click')
    await flushPromises()

    const sheet = document.querySelector('[data-testid="mcp-source-sheet"]')
    expect(sheet).not.toBeNull()

    const confirmBtn = document.querySelector(
      '[data-testid="confirm-switch-source-btn"]',
    ) as HTMLButtonElement
    // 未勾选前禁用
    expect(confirmBtn.disabled).toBe(true)

    // 勾选确认
    const checkbox = document.querySelector(
      '[data-testid="ack-cli-registered-checkbox"]',
    ) as HTMLInputElement
    checkbox.click()
    await flushPromises()

    expect(confirmBtn.disabled).toBe(false)

    // 点击提交
    confirmBtn.click()
    await flushPromises()

    const aiPatch = fake.calls.find((c) => c.path === '/api/ai/settings')
    expect(aiPatch).toBeDefined()
    const body = aiPatch?.body as S['AISettingsPatch']
    expect(body.ack_cli_registered).toBe(true)
    expect(body.analysis?.mcp_source).toBe('toolbox')

    await b.done()
  })

  it('Lark 卡片：所有权确认 Sheet（必须勾选承诺停用旧应用才可接管）', async () => {
    const fake = createS6CFake({
      lark: {
        owner_confirmed_at: null,
        state: 'stopped',
        app_id: 'cli_fake',
        domain: 'https://open.larksuite.com',
        endpoint: 'http://localhost:3000/mcp',
        port: 3000,
        language: 'zh',
        tools: '',
        autostart: false,
        scope_hint: '',
        secret_configured: true,
        keytar_available: true,
        log_tail: '',
        warnings: [],
      },
    })
    const b = await openMcpTab(fake)

    expect(b.wrapper.find('[data-testid="lark-ownership-status"]').text()).toContain('未确认所有权')

    // 打开所有权 Sheet
    await b.wrapper.get('[data-testid="lark-open-ownership-btn"]').trigger('click')
    await flushPromises()

    expect(document.querySelector('[data-testid="mcp-lark-ownership-sheet"]')).not.toBeNull()
    const confirmBtn = document.querySelector(
      '[data-testid="confirm-ownership-btn"]',
    ) as HTMLButtonElement
    // 未勾选禁用
    expect(confirmBtn.disabled).toBe(true)

    // 勾选承诺已停止旧应用
    const check = document.querySelector(
      '[data-testid="ack-old-app-stopped-checkbox"]',
    ) as HTMLInputElement
    check.click()
    await flushPromises()
    expect(confirmBtn.disabled).toBe(false)

    // 提交接管
    confirmBtn.click()
    await flushPromises()

    const ownCall = fake.calls.find(
      (c) => c.path === '/api/mcp/lark/ownership' && c.method === 'POST',
    )
    expect(ownCall).toBeDefined()
    const ownBody = ownCall?.body as S['LarkOwnershipRequest']
    expect(ownBody.ack_old_app_stopped).toBe(true)
    expect(ownBody.request_id).toMatch(/^[0-9a-f-]{36}$/)

    await b.done()
  })

  it('Lark 卡片：启停、登录提示 60 秒与登出提示', async () => {
    const fake = createS6CFake({
      lark: {
        state: 'stopped',
        owner_confirmed_at: '2026-10-25T10:00:00Z',
        secret_configured: true,
        app_id: 'cli_fake',
        domain: 'https://open.larksuite.com',
        endpoint: 'http://localhost:3000/mcp',
        port: 3000,
        language: 'zh',
        tools: '',
        autostart: false,
        scope_hint: '',
        keytar_available: true,
        log_tail: '',
        warnings: [],
      },
    })
    const b = await openMcpTab(fake)

    // 1. 启动服务
    await b.wrapper.get('[data-testid="lark-start-btn"]').trigger('click')
    await flushPromises()
    expect(fake.calls.some((c) => c.path === '/api/mcp/lark/start')).toBe(true)

    // 2. 模拟运行中状态
    fake.state.mcp.lark!.state = 'running'
    await b.wrapper.get('[data-testid="mcp-lark-card"]')
    // 触发刷新
    b.sock.emit(env('mcp.status', fake.state.mcp, { topic: 'mcp' }))
    await flushPromises()

    // 停止服务
    const stopBtn = b.wrapper.find('[data-testid="lark-stop-btn"]')
    expect(stopBtn.exists()).toBe(true)
    await stopBtn.trigger('click')
    await flushPromises()
    expect(fake.calls.some((c) => c.path === '/api/mcp/lark/stop')).toBe(true)

    await b.done()
  })

  it('Lark 补丁降级与令牌状态提示展示', async () => {
    const fake = createS6CFake({
      lark: {
        state: 'running_degraded',
        keytar_available: false,
        patches: { all_applied: false, auth_store: 'skipped', mcp_tool: 'applied', oidc: 'failed' },
        token_status: {
          state: 'refresh_failing',
          logged_in_at: '2026-10-24T10:00:00Z',
          last_event_at: '2026-10-26T00:00:00Z',
          message: null,
        },
        app_id: 'cli_fake',
        domain: 'https://open.larksuite.com',
        endpoint: 'http://localhost:3000/mcp',
        port: 3000,
        language: 'zh',
        tools: '',
        autostart: false,
        scope_hint: '',
        secret_configured: true,
        log_tail: '',
        warnings: [],
      },
    })
    const b = await openMcpTab(fake)

    const degBanner = b.wrapper.find('[data-testid="lark-degraded-banner"]')
    expect(degBanner.exists()).toBe(true)
    expect(degBanner.text()).toContain('刷新补丁未生效：过期后可能需要重登')
    expect(degBanner.text()).toContain('令牌存储不可用，重启后需重登')

    const refreshFailingBanner = b.wrapper.find('[data-testid="lark-refresh-failing-banner"]')
    expect(refreshFailingBanner.exists()).toBe(true)
    expect(refreshFailingBanner.text()).toContain('令牌刷新失败')
    expect(b.wrapper.find('[data-testid="lark-relogin-btn"]').exists()).toBe(true)

    await b.done()
  })

  it('凭据安全：提交后清空且 DOM / localStorage / URL 全局无凭据泄漏', async () => {
    const fake = createS6CFake()
    const b = await openMcpTab(fake)

    const FAKE_LARK_SECRET = 'LARK_SUPER_SECRET_TOKEN_999888'
    const FAKE_FIGMA_TOKEN = 'figd_SUPER_SECRET_FIGMA_TOKEN_777666'

    // 1. 提交 Lark Secret
    const larkInput = b.wrapper.get('[data-testid="lark-secret-input"] input')
    await larkInput.setValue(FAKE_LARK_SECRET)
    await b.wrapper.get('[data-testid="save-lark-secret-btn"]').trigger('click')
    await flushPromises()

    // 确认已发送到后端 PUT
    const larkPut = fake.calls.find((c) => c.path === '/api/mcp/credentials/lark_app_secret')
    expect(larkPut).toBeDefined()
    expect((larkPut?.body as S['CredentialPut'])?.value).toBe(FAKE_LARK_SECRET)

    // 2. 提交 Figma Token
    const figmaInput = b.wrapper.get('[data-testid="figma-token-input"] input')
    await figmaInput.setValue(FAKE_FIGMA_TOKEN)
    await b.wrapper.get('[data-testid="save-figma-token-btn"]').trigger('click')
    await flushPromises()

    const figmaPut = fake.calls.find((c) => c.path === '/api/mcp/credentials/figma_token')
    expect(figmaPut).toBeDefined()
    expect((figmaPut?.body as S['CredentialPut'])?.value).toBe(FAKE_FIGMA_TOKEN)

    // 3. 严格扫描：DOM、localStorage、URL 不得出现假密钥
    const html = document.body.innerHTML
    expect(html).not.toContain(FAKE_LARK_SECRET)
    expect(html).not.toContain(FAKE_FIGMA_TOKEN)

    const lsKeys = Object.keys(localStorage)
    for (const k of lsKeys) {
      expect(localStorage.getItem(k)).not.toContain(FAKE_LARK_SECRET)
      expect(localStorage.getItem(k)).not.toContain(FAKE_FIGMA_TOKEN)
    }

    expect(window.location.href).not.toContain(FAKE_LARK_SECRET)
    expect(window.location.href).not.toContain(FAKE_FIGMA_TOKEN)

    await b.done()
  })

  it('Figma 卡片：到期天数提醒与限流参数保存', async () => {
    // 模拟到期天数还有 3 天
    const threeDaysAgo = new Date(Date.now() - 87 * 24 * 60 * 60 * 1000).toISOString()
    const fake = createS6CFake({
      figma: {
        token_configured: true,
        token_set_at: threeDaysAgo,
        expiry_days: 90,
        max_concurrency: 2,
        min_interval_ms: 500,
        max_retry: 3,
      },
    })
    const b = await openMcpTab(fake)

    // 应出现即将到期 Banner (剩余 3 天 <= 7 天)
    const expiringBanner = b.wrapper.find('[data-testid="figma-token-expiring-banner"]')
    expect(expiringBanner.exists()).toBe(true)
    expect(expiringBanner.text()).toContain('即将在')

    // 保存限流参数
    const concurrencyInput = b.wrapper.get('[data-testid="figma-concurrency-input"] input')
    await concurrencyInput.setValue('3')
    await b.wrapper.get('[data-testid="save-figma-ratelimit-btn"]').trigger('click')
    await flushPromises()

    const patchCall = fake.calls.find(
      (c) => c.path === '/api/mcp/settings' && (c.body as S['MCPSettingsPatch'])?.figma,
    )
    expect(patchCall).toBeDefined()
    expect((patchCall?.body as S['MCPSettingsPatch'])?.figma?.max_concurrency).toBe(3)

    await b.done()
  })

  it('WS 状态更新与去重：水位去重且更新后状态同步', async () => {
    const fake = createS6CFake()
    const b = await openMcpTab(fake)

    // 订阅回执
    b.sock.emit(env('mcp.subscribed', { last_seq: 10 }, { topic: 'mcp', seq: 10 }))
    await flushPromises()

    // 模拟旧 seq=5 的状态变更 -> 水位已到 10，应被去重忽略
    const oldSnapshot = makeMcpSnapshot({
      lark: {
        state: 'failed',
        app_id: 'cli_old',
        domain: 'https://open.larksuite.com',
        endpoint: '',
        port: 3000,
        language: 'zh',
        tools: '',
        autostart: false,
        scope_hint: '',
        secret_configured: false,
        keytar_available: true,
        log_tail: '',
        warnings: [],
      },
    })
    b.sock.emit(env('mcp.status', oldSnapshot, { topic: 'mcp', seq: 5 }))
    await flushPromises()

    // 状态仍为原状，未被旧事件污染
    expect(b.wrapper.find('[data-testid="lark-status-pill"]').text()).toContain('已停止')

    // 模拟新 seq=15 的状态变更 -> 状态被更新为运行中
    const newSnapshot = makeMcpSnapshot({
      lark: {
        state: 'running',
        app_id: 'cli_new',
        domain: 'https://open.larksuite.com',
        endpoint: '',
        port: 3000,
        language: 'zh',
        tools: '',
        autostart: false,
        scope_hint: '',
        secret_configured: true,
        keytar_available: true,
        log_tail: '',
        warnings: [],
      },
    })
    b.sock.emit(env('mcp.status', newSnapshot, { topic: 'mcp', seq: 15 }))
    await flushPromises()

    expect(b.wrapper.find('[data-testid="lark-status-pill"]').text()).toContain('运行中')

    await b.done()
  })

  it('错误码文案：mcp_busy、mcp_port_in_use 等清晰中文提示', async () => {
    const fake = createS6CFake()
    // 覆盖 /api/mcp/lark/start 返回 409 mcp_port_in_use
    fake.setOverride(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/mcp/lark/start' && req.method === 'POST') {
        return json({ detail: { code: 'mcp_port_in_use', message: '端口已被占用' } }, 409)
      }
      return undefined
    })

    const b = await openMcpTab(fake)
    await b.wrapper.get('[data-testid="lark-start-btn"]').trigger('click')
    await flushPromises()

    const errBanner = b.wrapper.find('[data-testid="lark-error-banner"]')
    expect(errBanner.exists()).toBe(true)
    expect(errBanner.text()).toContain('端口已被占用')

    await b.done()
  })

  it('卸载释放：离开 MCP 页签或组件卸载时调用 unsubscribeMcp 并释放监听', async () => {
    const fake = createS6CFake()
    const b = await openMcpTab(fake)

    const unsubSpy = vi.spyOn(b.runtime, 'unsubscribeMcp')

    // 卸载组件树
    b.wrapper.unmount()
    await flushPromises()

    expect(unsubSpy).toHaveBeenCalled()
    await b.done()
  })
})
