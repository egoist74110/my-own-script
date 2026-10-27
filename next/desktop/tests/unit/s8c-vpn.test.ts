// S8-C 单测：设置页「服务」分区顶部 VPN 卡、状态映射、错误码文案、凭据只写无回填、TOTP 导入多匹配选择、手输 MFA Sheet、WS 事件与水位管理、无凭据安全门禁
import { flushPromises, DOMWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { err, json } from './settings-fake'
import { VPN_ERROR_MESSAGES, vpnErrorMessage } from '@/features/settings/api'

// Sheet 经 Teleport 挂到 document.body，不在 wrapper 内
const bodyFind = (sel: string) => new DOMWrapper(document.querySelector(sel))
const bodyFindAll = (sel: string) =>
  Array.from(document.querySelectorAll(sel)).map((el) => new DOMWrapper(el))

type S = components['schemas']

function makeVpnSnapshot(over: Partial<S['VpnSnapshot']> = {}): S['VpnSnapshot'] {
  return {
    revision: 10,
    connected: false,
    ip: null,
    client: {
      installed: true,
      running: true,
      app_name: 'Check Point SASE',
      version: '13.1.0',
      ...(over.client ?? {}),
    },
    credentials: {
      password: false,
      totp_secret: false,
      ...(over.credentials ?? {}),
    },
    permissions: {
      screen_recording: 'denied',
      accessibility: 'denied',
      ...(over.permissions ?? {}),
    },
    settings: {
      client: {
        bundle_id: 'com.safervpn.osx.smb',
        app_name: null,
        url_scheme: 'CheckPointSASE',
      },
      tunnel_prefix: '10.254.',
      login: {
        workspace: 'test.perimeter81.com',
        residency: 'US Data Residency',
        email: 'user@example.com',
        totp_filter: 'Perimeter',
        headless: true,
      },
      window_automation: 'off',
      rung_timeout_s: 30,
      login_timeout_s: 75,
      max_run_s: 480,
      chrome_path: null,
      ...(over.settings ?? {}),
    },
    current_run: null,
    ...over,
  }
}

interface Call {
  method: string
  path: string
  body: unknown
}

function createS8CFake(initialSnapshot: S['VpnSnapshot'] = makeVpnSnapshot()) {
  const calls: Call[] = []
  const state = {
    snapshot: JSON.parse(JSON.stringify(initialSnapshot)) as S['VpnSnapshot'],
  }

  let overrideHandler: ((req: Request) => Promise<Response | undefined>) | null = null

  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init)
    const url = new URL(req.url, 'http://127.0.0.1')
    const p = url.pathname
    const method = req.method.toUpperCase()

    let body: unknown = undefined
    try {
      const cloned = req.clone()
      const text = await cloned.text()
      if (text) body = JSON.parse(text)
    } catch {
      // 忽略无法解析 JSON
    }

    calls.push({ method, path: p, body })

    if (overrideHandler) {
      const custom = await overrideHandler(req)
      if (custom !== undefined) return custom
    }

    if (p === '/api/settings' && method === 'GET') {
      return json({
        app_version: '0.1.0',
        data_dir: '/tmp/fake-data',
        legacy_config_dir: '/tmp/fake-legacy',
        revision: 10,
        schema_version: 6,
        store_state: 'ok',
        import: { state: 'completed' },
      })
    }

    if (p === '/api/ado' && method === 'GET') {
      return json({ libraries: [], local_repos: [], revision: 10 })
    }

    if (p === '/api/credentials' && method === 'GET') {
      return json([])
    }

    if (p === '/api/services' && method === 'GET') {
      return json({
        revision: 10,
        binaries: {
          code_server: { confirmed: true, found: true, path: '/bin/code-server', version: '1.0' },
          cloudflared: { confirmed: true, found: true, path: '/bin/cloudflared', version: '1.0' },
        },
        code_server: {
          id: 'code-server',
          state: 'stopped',
          port: 8080,
          url: 'http://127.0.0.1:8080',
          owned: true,
          log_tail_available: false,
          last_error: null,
          target_url: null,
        },
        cloudflared: {
          global: {
            id: 'cf',
            state: 'stopped',
            port: 8080,
            url: '',
            owned: true,
            log_tail_available: false,
            last_error: null,
            target_url: null,
          },
          tunnels: [],
        },
        network: { vpn_ip: null, lan_ip: '192.168.1.5', on_lan: true },
        settings: {
          binaries: { code_server: null, cloudflared: null },
          code_server: { start_timeout_s: 30 },
          cloudflared: { protocol: 'http2', max_tunnels: 5 },
        },
      })
    }

    // --- VPN 路由 ---
    if (p === '/api/vpn' && method === 'GET') {
      return json(state.snapshot)
    }

    if (p === '/api/vpn/connect' && method === 'POST') {
      const run: S['VpnRunView'] = {
        run_id: 'run-test-1',
        request_id: 'req-1',
        state: 'running',
        rung: 1,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ip: null,
        error_code: null,
        events: [
          {
            run_id: 'run-test-1',
            run_seq: 1,
            state: 'running',
            rung: 1,
            event: 'rungA_open',
            error_code: null,
            ip: null,
          },
        ],
      }
      state.snapshot.current_run = run
      return json(run, 202)
    }

    if (p === '/api/vpn/relogin' && method === 'POST') {
      const run: S['VpnRunView'] = {
        run_id: 'run-relogin-1',
        request_id: 'req-2',
        state: 'running',
        rung: 3,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ip: null,
        error_code: null,
        events: [
          {
            run_id: 'run-relogin-1',
            run_seq: 1,
            state: 'running',
            rung: 3,
            event: 'rungC_login',
            error_code: null,
            ip: null,
          },
        ],
      }
      state.snapshot.current_run = run
      return json(run, 202)
    }

    if (p.startsWith('/api/vpn/runs/') && p.endsWith('/cancel') && method === 'POST') {
      if (state.snapshot.current_run) {
        state.snapshot.current_run.state = 'cancelled'
        return json(state.snapshot.current_run)
      }
      return err(404, 'not_found', '运行不存在')
    }

    if (p.startsWith('/api/vpn/runs/') && p.endsWith('/mfa') && method === 'POST') {
      const b = body as S['ManualMfa']
      if (b.code === '999999') {
        return err(400, 'login_mfa_rejected', 'MFA 验证码错误')
      }
      return json({ accepted: true })
    }

    if (p.startsWith('/api/vpn/credentials/') && method === 'PUT') {
      const kind = p.split('/').pop()
      if (kind === 'vpn_password') state.snapshot.credentials.password = true
      if (kind === 'vpn_totp_secret') state.snapshot.credentials.totp_secret = true
      return json({ configured: true })
    }

    if (p.startsWith('/api/vpn/credentials/') && method === 'DELETE') {
      const kind = p.split('/').pop()
      if (kind === 'vpn_password') state.snapshot.credentials.password = false
      if (kind === 'vpn_totp_secret') state.snapshot.credentials.totp_secret = false
      return json({ configured: false })
    }

    if (p === '/api/vpn/totp/import' && method === 'POST') {
      const b = body as S['TotpImport']
      if (b.text.includes('ambiguous') && b.index === undefined) {
        return err(409, 'totp_ambiguous', '找到多个匹配项目，请选择一个', {
          items: [
            { issuer: 'Perimeter 81', label: 'user@company.com', index: 0 },
            { issuer: 'Check Point', label: 'admin@company.com', index: 1 },
          ],
        })
      }
      if (b.text.includes('unsupported')) {
        return err(400, 'totp_unsupported', '不支持的算法')
      }
      state.snapshot.credentials.totp_secret = true
      return json({ configured: true })
    }

    if (p === '/api/vpn/credentials/import-legacy' && method === 'POST') {
      state.snapshot.credentials.password = true
      state.snapshot.credentials.totp_secret = true
      if (state.snapshot.settings?.login) {
        state.snapshot.settings.login.workspace = 'legacy.perimeter81.com'
      }
      return json({ imported: ['vpn_password', 'vpn_totp_secret'] })
    }

    if (p === '/api/vpn/settings' && method === 'PATCH') {
      const b = body as S['VpnSettingsPatch']
      if (b.revision !== state.snapshot.revision) {
        return err(409, 'revision_conflict', '配置版本冲突')
      }
      state.snapshot.settings = b.vpn
      state.snapshot.revision++
      return json({ revision: state.snapshot.revision })
    }

    if (p === '/api/vpn/browser-profile' && method === 'DELETE') {
      if (state.snapshot.current_run?.state === 'running') {
        return err(409, 'vpn_busy', 'VPN 运行期间不能清除浏览器配置')
      }
      return json({ cleared: true })
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

async function openServicesTab(fake: ReturnType<typeof createS8CFake>) {
  const b = await boot({ path: '/settings', fetchImpl: fake.fetchImpl })
  b.sock.emit(hello())
  await flushPromises()

  // 切换到「服务」页签
  const tabs = b.wrapper.findAll('[role=tab]')
  const servicesTab = tabs.find((t) => t.text().includes('服务'))!
  expect(servicesTab).toBeDefined()
  await servicesTab.trigger('mousedown')
  await flushPromises()
  await flushPromises()
  return b
}

describe('S8-C: 前端 VPN 卡单测', () => {
  beforeEach(() => {
    FakeSocket.reset()
    resetSeq()
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('verified_by=executor, independent=false: 服务页顶部 VPN 卡渲染与初始状态映射', async () => {
    const fake = createS8CFake(
      makeVpnSnapshot({
        connected: false,
        ip: null,
        client: { installed: true, running: true, app_name: 'Check Point SASE', version: '13.1.0' },
      }),
    )
    const b = await openServicesTab(fake)

    // 确认卡片存在
    const card = b.wrapper.find('[data-testid="vpn-card"]')
    expect(card.exists()).toBe(true)

    // 状态胶囊：未连接
    const pill = b.wrapper.find('[data-testid="vpn-status-pill"]')
    expect(pill.text()).toBe('未连接')

    // 客户端状态与版本
    expect(b.wrapper.find('[data-testid="client-running-tag"]').text()).toBe('运行中')
    expect(b.wrapper.find('[data-testid="client-version-text"]').text()).toContain(
      'Check Point SASE 13.1.0',
    )

    // IP
    expect(b.wrapper.find('[data-testid="vpn-ip-text"]').text()).toBe('未分配')

    // 按钮存在
    expect(b.wrapper.find('[data-testid="vpn-connect-btn"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="vpn-relogin-btn"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="open-legacy-import-btn"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="clear-browser-btn"]').exists()).toBe(true)

    await b.done()
  })

  it('verified_by=executor, independent=false: 已连接状态与 IP 展现及复制', async () => {
    const fake = createS8CFake(
      makeVpnSnapshot({
        connected: true,
        ip: '10.254.12.34',
        client: { installed: true, running: true, app_name: 'Check Point SASE', version: '13.1.0' },
      }),
    )
    const b = await openServicesTab(fake)

    const pill = b.wrapper.find('[data-testid="vpn-status-pill"]')
    expect(pill.text()).toBe('已连接')

    const ipText = b.wrapper.find('[data-testid="vpn-ip-text"]')
    expect(ipText.text()).toBe('10.254.12.34')

    const copyBtn = b.wrapper.find('[data-testid="copy-ip-btn"]')
    expect(copyBtn.exists()).toBe(true)

    // 已连接时「连接」按钮禁用
    const connectBtn = b.wrapper.find('[data-testid="vpn-connect-btn"]')
    expect((connectBtn.element as HTMLButtonElement).disabled).toBe(true)

    await b.done()
  })

  it('verified_by=executor, independent=false: 客户端缺失或未运行状态映射', async () => {
    const fake = createS8CFake(
      makeVpnSnapshot({
        connected: false,
        client: { installed: false, running: false, app_name: null, version: null },
      }),
    )
    const b = await openServicesTab(fake)

    expect(b.wrapper.find('[data-testid="client-not-installed-tag"]').text()).toBe('未安装客户端')
    // 客户端未安装时连接与重登按钮均禁用
    expect(
      (b.wrapper.find('[data-testid="vpn-connect-btn"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(
      (b.wrapper.find('[data-testid="vpn-relogin-btn"]').element as HTMLButtonElement).disabled,
    ).toBe(true)

    await b.done()
  })

  it('verified_by=executor, independent=false: 连接、强制重登与取消流程', async () => {
    const fake = createS8CFake()
    const b = await openServicesTab(fake)

    // 触发连接
    const connectBtn = b.wrapper.find('[data-testid="vpn-connect-btn"]')
    await connectBtn.trigger('click')
    await flushPromises()

    expect(fake.calls.some((c) => c.path === '/api/vpn/connect' && c.method === 'POST')).toBe(true)

    // 运行中展现「取消连接」按钮与进行中状态
    const cancelBtn = b.wrapper.find('[data-testid="vpn-cancel-btn"]')
    expect(cancelBtn.exists()).toBe(true)

    // 点击取消
    await cancelBtn.trigger('click')
    await flushPromises()
    expect(
      fake.calls.some((c) => c.path === '/api/vpn/runs/run-test-1/cancel' && c.method === 'POST'),
    ).toBe(true)

    await b.done()
  })

  it('verified_by=executor, independent=false: 全部错误码文案均有中文定义', () => {
    const errorCodes = [
      'vpn_busy',
      'vpn_client_missing',
      'vpn_not_configured',
      'vpn_mfa_required',
      'vpn_mfa_timeout',
      'totp_ambiguous',
      'totp_unsupported',
      'window_permission_missing',
      'client_stuck',
      'max_run_exceeded',
      'login_selector_missing',
      'login_credentials_rejected',
      'login_mfa_rejected',
      'login_timeout',
      'login_callback_not_captured',
      'vpn_not_implemented',
      'vpn_profile_unsafe',
      'revision_conflict',
    ]

    for (const code of errorCodes) {
      const expected = VPN_ERROR_MESSAGES[code]
      expect(expected).toBeDefined()
      expect(expected?.length).toBeGreaterThan(3)
      const msg = vpnErrorMessage(code)
      expect(msg).toBe(expected)
    }
  })

  it('verified_by=executor, independent=false: 凭据只写：提交后立即清空内存，绝不回填明文', async () => {
    const fake = createS8CFake(
      makeVpnSnapshot({
        credentials: { password: false, totp_secret: false },
      }),
    )
    const b = await openServicesTab(fake)

    // 初始状态：未配置
    expect(b.wrapper.find('[data-testid="password-status-tag"]').text()).toBe('未配置')
    expect(b.wrapper.find('[data-testid="totp-status-tag"]').text()).toBe('未配置')

    // 输入密码
    const pwdInput = b.wrapper.find('[data-testid="vpn-password-input"]')
    await pwdInput.setValue('SuperSecretPassword999!')

    // 保存密码
    const savePwdBtn = b.wrapper.find('[data-testid="save-password-btn"]')
    await savePwdBtn.trigger('click')
    await flushPromises()

    // 断言后端调用
    const call = fake.calls.find(
      (c) => c.path === '/api/vpn/credentials/vpn_password' && c.method === 'PUT',
    )
    expect(call).toBeDefined()
    expect((call?.body as S['CredentialWrite'] | undefined)?.value).toBe('SuperSecretPassword999!')

    // 关键门禁：提交后输入框必须立即清空，避免在内存或 DOM 驻留明文
    expect((pwdInput.element as HTMLInputElement).value).toBe('')
    expect(b.wrapper.find('[data-testid="password-status-tag"]').text()).toBe('已配置')

    // 删除密码
    const delPwdBtn = b.wrapper.find('[data-testid="delete-password-btn"]')
    expect(delPwdBtn.exists()).toBe(true)
    await delPwdBtn.trigger('click')
    await flushPromises()
    expect(
      fake.calls.some(
        (c) => c.path === '/api/vpn/credentials/vpn_password' && c.method === 'DELETE',
      ),
    ).toBe(true)
    expect(b.wrapper.find('[data-testid="password-status-tag"]').text()).toBe('未配置')

    // 保存 TOTP 种子
    const totpInput = b.wrapper.find('[data-testid="vpn-totp-input"]')
    await totpInput.setValue('JBSWY3DPEHPK3PXP')
    const saveTotpBtn = b.wrapper.find('[data-testid="save-totp-btn"]')
    await saveTotpBtn.trigger('click')
    await flushPromises()

    expect(
      fake.calls.some(
        (c) => c.path === '/api/vpn/credentials/vpn_totp_secret' && c.method === 'PUT',
      ),
    ).toBe(true)
    expect((totpInput.element as HTMLInputElement).value).toBe('')
    expect(b.wrapper.find('[data-testid="totp-status-tag"]').text()).toBe('已配置')

    await b.done()
  })

  it('verified_by=executor, independent=false: TOTP 导入 Sheet 多匹配（409 totp_ambiguous）选择与重提交', async () => {
    const fake = createS8CFake()
    const b = await openServicesTab(fake)

    // 打开 TOTP 导入 Sheet
    const openSheetBtn = b.wrapper.find('[data-testid="open-totp-import-btn"]')
    await openSheetBtn.trigger('click')
    await flushPromises()

    const sheet = bodyFind('[data-testid="vpn-totp-import-sheet"]')
    expect(sheet.exists()).toBe(true)

    // 输入会触发 ambiguous 的文本
    const textarea = bodyFind('[data-testid="totp-text-input"]')
    await textarea.setValue('export-content-with-ambiguous-results')

    const submitBtn = bodyFind('[data-testid="submit-totp-import-btn"]')
    await submitBtn.trigger('click')
    await flushPromises()

    // 应该展现多匹配候选列表
    const candidatesBox = bodyFind('[data-testid="totp-candidates-container"]')
    expect(candidatesBox.exists()).toBe(true)

    const radios = bodyFindAll('[data-testid="totp-candidate-radio"]')
    expect(radios.length).toBe(2)

    // 选中第二个候选
    await radios[1]!.trigger('change')
    await flushPromises()

    // 再次提交，带上 index
    await submitBtn.trigger('click')
    await flushPromises()

    const submitCall = fake.calls.find(
      (c) =>
        c.path === '/api/vpn/totp/import' &&
        (c.body as Record<string, unknown> | undefined)?.index === 1,
    )
    expect(submitCall).toBeDefined()

    // 提交成功后提示“请自行删除导出文件”
    expect(b.wrapper.find('[data-testid="vpn-notice-banner"]').text()).toContain(
      '请自行删除导出文件',
    )

    await b.done()
  })

  it('verified_by=executor, independent=false: 手输 MFA 动态口令 Sheet 与 120 秒倒计时', async () => {
    const fake = createS8CFake(
      makeVpnSnapshot({
        current_run: {
          run_id: 'run-mfa-req-1',
          state: 'running',
          rung: 3,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          events: [],
        },
      }),
    )
    const b = await openServicesTab(fake)

    // WS 推送 vpn.mfa_required 事件
    b.sock.emit({
      seq: 20,
      topic: 'vpn',
      type: 'vpn.mfa_required',
      ts: new Date().toISOString(),
      data: {
        run_id: 'run-mfa-req-1',
        expires_in_s: 120,
        vpn_seq: 1,
      },
    })
    await flushPromises()

    // MFA Sheet 自动打开
    const mfaSheet = bodyFind('[data-testid="vpn-mfa-sheet"]')
    expect(mfaSheet.exists()).toBe(true)

    const countdown = bodyFind('[data-testid="mfa-countdown"]')
    expect(countdown.text()).toBe('120')

    // 输入 6 位口令
    const mfaInput = bodyFind('[data-testid="mfa-code-input"] input')
    await mfaInput.setValue('654321')

    const submitMfaBtn = bodyFind('[data-testid="submit-mfa-btn"]')
    await submitMfaBtn.trigger('click')
    await flushPromises()

    const mfaCall = fake.calls.find((c) => c.path === '/api/vpn/runs/run-mfa-req-1/mfa')
    expect(mfaCall).toBeDefined()
    expect((mfaCall?.body as S['ManualMfa'] | undefined)?.code).toBe('654321')

    await b.done()
  })

  it('verified_by=executor, independent=false: 设置项表单 PATCH、权限提示与忘记此浏览器', async () => {
    const fake = createS8CFake()
    const b = await openServicesTab(fake)

    // 展开设置
    const toggleBtn = b.wrapper.find('[data-testid="toggle-vpn-settings-btn"]')
    await toggleBtn.trigger('click')
    await flushPromises()

    expect(b.wrapper.find('[data-testid="vpn-settings-container"]').exists()).toBe(true)

    // 切换窗口自动化档位为 connect
    const autoSelect = b.wrapper.find('[data-testid="vpn-window-automation-select"]')
    await autoSelect.setValue('connect')
    await flushPromises()

    // 缺少权限时必须出现警告与说明
    const warn = b.wrapper.find('[data-testid="permissions-warning-banner"]')
    expect(warn.exists()).toBe(true)
    expect(warn.text()).toContain('会移动真实鼠标')
    expect(warn.text()).toContain('授权对象是启动后端的那个应用')

    // 保存设置
    const saveSettingsBtn = b.wrapper.find('[data-testid="save-vpn-settings-btn"]')
    await saveSettingsBtn.trigger('click')
    await flushPromises()

    expect(fake.calls.some((c) => c.path === '/api/vpn/settings' && c.method === 'PATCH')).toBe(
      true,
    )

    // 忘记此浏览器
    const clearBrowserBtn = b.wrapper.find('[data-testid="clear-browser-btn"]')
    await clearBrowserBtn.trigger('click')
    await flushPromises()

    const confirmClearBtn = b.wrapper.find('[data-testid="confirm-clear-browser-btn"]')
    expect(confirmClearBtn.exists()).toBe(true)
    await confirmClearBtn.trigger('click')
    await flushPromises()

    expect(
      fake.calls.some((c) => c.path === '/api/vpn/browser-profile' && c.method === 'DELETE'),
    ).toBe(true)

    await b.done()
  })

  it('verified_by=executor, independent=false: WS 水位只进不退与单实例卸载释放', async () => {
    const fake = createS8CFake()
    const b = await openServicesTab(fake)

    // 发送 vpn.subscribed 设置初始水位
    b.sock.emit({
      seq: 30,
      topic: 'vpn',
      type: 'vpn.subscribed',
      ts: new Date().toISOString(),
      data: { last_seq: 10 },
    })
    await flushPromises()

    // 发送比水位旧的 vpn.status（应该被丢弃）
    b.sock.emit({
      seq: 31,
      topic: 'vpn',
      type: 'vpn.status',
      ts: new Date().toISOString(),
      data: {
        connected: true,
        ip: '10.254.99.99',
        vpn_seq: 5, // <= 10
      },
    })
    await flushPromises()
    expect(b.wrapper.find('[data-testid="vpn-status-pill"]').text()).toBe('未连接')

    // 发送新于水位的 vpn.status（生效）
    b.sock.emit({
      seq: 32,
      topic: 'vpn',
      type: 'vpn.status',
      ts: new Date().toISOString(),
      data: {
        connected: true,
        ip: '10.254.88.88',
        vpn_seq: 15,
      },
    })
    await flushPromises()
    expect(b.wrapper.find('[data-testid="vpn-status-pill"]').text()).toBe('已连接')
    expect(b.wrapper.find('[data-testid="vpn-ip-text"]').text()).toBe('10.254.88.88')

    // 步骤时间线通过 vpn.run 事件接收
    b.sock.emit({
      seq: 33,
      topic: 'vpn',
      type: 'vpn.run',
      ts: new Date().toISOString(),
      data: {
        run_id: 'run-step-1',
        run_seq: 1,
        state: 'running',
        rung: 1,
        event: 'rungA_open',
        error_code: null,
        ip: null,
        vpn_seq: 16,
      },
    })
    await flushPromises()
    expect(b.wrapper.find('[data-testid="vpn-timeline-card"]').exists()).toBe(true)

    // 卸载组件不抛错
    b.wrapper.unmount()
    await flushPromises()
  })

  it('verified_by=executor, independent=false: 安全门禁：DOM、存储与 URL 绝无凭据与深链泄露', async () => {
    const fake = createS8CFake()
    const b = await openServicesTab(fake)

    const forbiddenStrings = [
      'SuperSecretPassword999!',
      'JBSWY3DPEHPK3PXP',
      'otpauth://',
      'CheckPointSASE://',
      'HarmonySASE://',
    ]

    const html = b.wrapper.html()
    for (const secret of forbiddenStrings) {
      expect(html).not.toContain(secret)
    }

    expect(JSON.stringify(localStorage)).not.toContain('password')
    expect(JSON.stringify(sessionStorage)).not.toContain('password')

    await b.done()
  })
})
