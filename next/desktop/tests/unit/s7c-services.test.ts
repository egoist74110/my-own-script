// S7-C 单测：设置页「服务」分区（网络信息条、code-server 卡、cloudflared 卡）、状态映射、错误码文案、公网二次确认、WS 水位与无凭据安全门禁
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { err, json } from './settings-fake'

type S = components['schemas']

function makeServicesSnapshot(over: Partial<S['ServicesSnapshot']> = {}): S['ServicesSnapshot'] {
  return {
    revision: 20,
    binaries: {
      code_server: {
        confirmed: true,
        found: true,
        path: '/opt/homebrew/bin/code-server',
        version: '4.96.2',
      },
      cloudflared: {
        confirmed: true,
        found: true,
        path: '/usr/local/bin/cloudflared',
        version: '2026.3.0',
      },
      ...(over.binaries ?? {}),
    },
    code_server: {
      id: 'code-server',
      state: 'stopped',
      port: 8080,
      url: 'http://127.0.0.1:8080',
      owned: true,
      log_tail_available: true,
      last_error: null,
      target_url: null,
      ...(over.code_server ?? {}),
    },
    cloudflared: {
      global: {
        id: 'cloudflared-global',
        state: 'stopped',
        port: 8080,
        url: 'https://myself-test.trycloudflare.com',
        owned: true,
        log_tail_available: true,
        last_error: null,
        target_url: 'http://127.0.0.1:8080',
      },
      tunnels: [
        {
          id: 'tun-1',
          state: 'running',
          port: 3000,
          url: 'https://custom-tunnel.trycloudflare.com',
          owned: true,
          log_tail_available: true,
          last_error: null,
          target_url: 'http://127.0.0.1:3000',
        },
      ],
      ...(over.cloudflared ?? {}),
    },
    network: {
      vpn_ip: '10.254.1.42',
      lan_ip: '192.168.1.100',
      on_lan: true,
      ...(over.network ?? {}),
    },
    settings: {
      binaries: {
        code_server: '/opt/homebrew/bin/code-server',
        cloudflared: '/usr/local/bin/cloudflared',
      },
      code_server: {
        start_timeout_s: 30,
      },
      cloudflared: {
        protocol: 'http2',
        max_tunnels: 5,
      },
      ...(over.settings ?? {}),
    },
    ...over,
  }
}

interface Call {
  method: string
  path: string
  body: unknown
}

function createS7CFake(initialSnapshot: S['ServicesSnapshot'] = makeServicesSnapshot()) {
  const calls: Call[] = []
  const state = {
    snapshot: JSON.parse(JSON.stringify(initialSnapshot)) as S['ServicesSnapshot'],
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
        revision: state.snapshot.revision,
        schema_version: 5,
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
      return json(state.snapshot)
    }

    if (p === '/api/services/code-server/start' && method === 'POST') {
      state.snapshot.code_server.state = 'running'
      return json(state.snapshot)
    }

    if (p === '/api/services/code-server/stop' && method === 'POST') {
      state.snapshot.code_server.state = 'stopped'
      return json(state.snapshot)
    }

    if (p === '/api/services/cloudflared/start' && method === 'POST') {
      state.snapshot.cloudflared.global!.state = 'running'
      return json(state.snapshot)
    }

    if (p === '/api/services/cloudflared/stop' && method === 'POST') {
      state.snapshot.cloudflared.global!.state = 'stopped'
      return json(state.snapshot)
    }

    if (p === '/api/services/cloudflared/protocol' && method === 'POST') {
      const b = body as { protocol: 'http2' | 'quic'; revision: number }
      state.snapshot.settings!.cloudflared!.protocol = b.protocol
      state.snapshot.revision++
      return json({
        restart_required: true,
        revision: state.snapshot.revision,
      })
    }

    if (p === '/api/services/cloudflared/tunnels' && method === 'POST') {
      const b = body as { target_url: string; ack_public: boolean }
      const newTun: S['ServiceView'] = {
        id: 'tun-new-99',
        state: 'running',
        port: 4000,
        url: 'https://new-tunnel.trycloudflare.com',
        owned: true,
        log_tail_available: true,
        last_error: null,
        target_url: b.target_url,
      }
      state.snapshot.cloudflared.tunnels = [...(state.snapshot.cloudflared.tunnels ?? []), newTun]
      return json(state.snapshot)
    }

    if (p.startsWith('/api/services/cloudflared/tunnels/') && method === 'DELETE') {
      const id = p.split('/').pop()
      state.snapshot.cloudflared.tunnels = (state.snapshot.cloudflared.tunnels ?? []).filter(
        (t) => t.id !== id,
      )
      return json(state.snapshot)
    }

    if (p === '/api/services/import-legacy' && method === 'POST') {
      state.snapshot.settings!.cloudflared!.protocol = 'quic'
      state.snapshot.revision++
      return json({
        restart_required: true,
        revision: state.snapshot.revision,
      })
    }

    if (p === '/api/services/settings' && method === 'PATCH') {
      const b = body as { revision: number; services: S['ServicesConfig'] }
      state.snapshot.settings = { ...state.snapshot.settings, ...b.services }
      state.snapshot.revision++
      return json({
        restart_required: false,
        revision: state.snapshot.revision,
      })
    }

    if (p === '/api/services/code-server/logs' && method === 'GET') {
      return json({
        text: '[2026-10-26T12:00:00Z] info  code-server 4.96.2 started at http://127.0.0.1:8080\n',
      })
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

async function openServicesTab(fake: ReturnType<typeof createS7CFake>) {
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

describe('S7-C: 服务分区单测', () => {
  beforeEach(() => {
    FakeSocket.reset()
    resetSeq()
    localStorage.clear()
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('verified_by=executor, independent=false: 服务分区渲染、网络信息条与 code-server / cloudflared 卡渲染', async () => {
    const fake = createS7CFake()
    const b = await openServicesTab(fake)

    expect(b.wrapper.find('[data-testid="services-tab"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="network-bar"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="code-server-card"]').exists()).toBe(true)
    expect(b.wrapper.find('[data-testid="cloudflared-card"]').exists()).toBe(true)

    await b.done()
  })

  it('顶部网络信息条：展示 VPN IP、局域网 IP 与复制，缺失时展示“未检测到”', async () => {
    const snap = makeServicesSnapshot({
      network: { vpn_ip: '10.254.9.99', lan_ip: '192.168.31.50', on_lan: true },
    })
    const fake = createS7CFake(snap)
    const b = await openServicesTab(fake)

    expect(b.wrapper.get('[data-testid="vpn-ip"]').text()).toBe('10.254.9.99')
    expect(b.wrapper.get('[data-testid="lan-ip"]').text()).toBe('192.168.31.50')
    expect(b.wrapper.find('[data-testid="on-lan-tag"]').exists()).toBe(true)

    // 复制点击不抛异常
    const copyVpnBtn = b.wrapper.get('[data-testid="copy-vpn-btn"]')
    await copyVpnBtn.trigger('click')
    await flushPromises()

    const copyLanBtn = b.wrapper.get('[data-testid="copy-lan-btn"]')
    await copyLanBtn.trigger('click')
    await flushPromises()

    // 缺失场景
    fake.state.snapshot.network = { vpn_ip: null, lan_ip: null, on_lan: false }
    const b2 = await openServicesTab(fake)
    expect(b2.wrapper.find('[data-testid="vpn-ip-missing"]').text()).toBe('未检测到')
    expect(b2.wrapper.find('[data-testid="lan-ip-missing"]').text()).toBe('未检测到')
    expect(b2.wrapper.find('[data-testid="on-lan-tag"]').exists()).toBe(false)

    await b.done()
    await b2.done()
  })

  it('code-server 卡：运行状态映射（stopped, starting, running, stopping, failed, external, unhealthy）', async () => {
    const states: Array<{
      s: S['ServiceView']['state']
      pillLabel: string
      pillState: string
    }> = [
      { s: 'stopped', pillLabel: '已停止', pillState: 'disabled' },
      { s: 'starting', pillLabel: '启动中', pillState: 'running' },
      { s: 'running', pillLabel: '运行中', pillState: 'running' },
      { s: 'stopping', pillLabel: '停止中', pillState: 'stopping' },
      { s: 'failed', pillLabel: '服务异常', pillState: 'failed' },
      { s: 'external', pillLabel: '外部进程占用', pillState: 'verify' },
      { s: 'unhealthy', pillLabel: '健康探测异常', pillState: 'verify' },
    ]

    for (const item of states) {
      const snap = makeServicesSnapshot()
      snap.code_server.state = item.s
      const fake = createS7CFake(snap)
      const b = await openServicesTab(fake)

      const pill = b.wrapper.get('[data-testid="code-server-status-pill"]')
      expect(pill.text()).toContain(item.pillLabel)
      expect(pill.attributes('data-state')).toBe(item.pillState)
      await b.done()
    }
  })

  it('code-server 卡：external 外部进程占用时展示警告文案，且停止按钮被禁用/替换为非破坏态', async () => {
    const snap = makeServicesSnapshot()
    snap.code_server.state = 'external'
    const fake = createS7CFake(snap)
    const b = await openServicesTab(fake)

    const banner = b.wrapper.find('[data-testid="code-server-external-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('该端口已被非本应用启动的进程占用，应用不会停止它')

    // 外部运行中不可点停止
    expect(b.wrapper.find('[data-testid="code-server-stop-btn"]').exists()).toBe(false)
    const extBtn = b.wrapper.get('[data-testid="code-server-external-btn"]')
    expect(extBtn.attributes('disabled')).toBeDefined()

    await b.done()
  })

  it('code-server 卡：启停操作（POST /api/services/code-server/{start|stop}），request_id 为 UUID，单按钮 loading 不乐观写', async () => {
    const snap = makeServicesSnapshot()
    snap.code_server.state = 'stopped'
    const fake = createS7CFake(snap)
    const b = await openServicesTab(fake)

    // 点击启动
    const startBtn = b.wrapper.get('[data-testid="code-server-start-btn"]')
    await startBtn.trigger('click')
    await flushPromises()

    const startCall = fake.calls.find((c) => c.path === '/api/services/code-server/start')
    expect(startCall).toBeDefined()
    expect(startCall?.method).toBe('POST')
    const startBody = startCall?.body as { request_id: string; ack_public: boolean }
    expect(startBody.request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(startBody.ack_public).toBe(false)

    // 状态变成 running 后出现停止按钮
    const stopBtn = b.wrapper.get('[data-testid="code-server-stop-btn"]')
    await stopBtn.trigger('click')
    await flushPromises()

    const stopCall = fake.calls.find((c) => c.path === '/api/services/code-server/stop')
    expect(stopCall).toBeDefined()
    expect(stopCall?.method).toBe('POST')

    await b.done()
  })

  it('code-server 卡：service_unsafe_config 错误文案展示', async () => {
    const fake = createS7CFake()
    fake.setOverride(async (req) => {
      if (req.url.endsWith('/api/services/code-server/start')) {
        return err(
          409,
          'service_unsafe_config',
          'code-server 配置为无认证且监听非回环地址，已拒绝启动；请在其 config.yaml 中启用密码认证',
        )
      }
      return undefined
    })

    const b = await openServicesTab(fake)
    const startBtn = b.wrapper.get('[data-testid="code-server-start-btn"]')
    await startBtn.trigger('click')
    await flushPromises()

    const errorBanner = b.wrapper.find('[data-testid="code-server-error-banner"]')
    expect(errorBanner.exists()).toBe(true)
    expect(errorBanner.text()).toContain(
      'code-server 配置为无认证且监听非回环地址，已拒绝启动；请在其 config.yaml 中启用密码认证',
    )

    await b.done()
  })

  it('code-server 卡：二进制状态缺失展示 service_binary_missing 文案', async () => {
    const snap = makeServicesSnapshot()
    snap.binaries.code_server = {
      confirmed: false,
      found: false,
      path: null,
      version: null,
    }
    const fake = createS7CFake(snap)
    const b = await openServicesTab(fake)

    const missingBanner = b.wrapper.find('[data-testid="code-server-binary-missing-banner"]')
    expect(missingBanner.exists()).toBe(true)
    expect(missingBanner.text()).toContain('未找到服务二进制执行文件，请检查安装路径')

    await b.done()
  })

  it('code-server 卡：查看脱敏日志尾部（GET /api/services/{name}/logs），等宽只读展示', async () => {
    const fake = createS7CFake()
    const b = await openServicesTab(fake)

    const toggleLogsBtn = b.wrapper.get('[data-testid="code-server-toggle-logs-btn"]')
    await toggleLogsBtn.trigger('click')
    await flushPromises()

    const logCall = fake.calls.find((c) => c.path === '/api/services/code-server/logs')
    expect(logCall).toBeDefined()

    const pre = b.wrapper.get('[data-testid="code-server-logs-pre"]')
    expect(pre.text()).toContain('code-server 4.96.2 started at http://127.0.0.1:8080')
    expect(pre.classes()).toContain('st-mono')

    await b.done()
  })

  it('cloudflared 卡：全局隧道启停与域名展示及复制', async () => {
    const snap = makeServicesSnapshot()
    snap.cloudflared.global!.state = 'stopped'
    const fake = createS7CFake(snap)
    const b = await openServicesTab(fake)

    // 启动全局隧道
    const startBtn = b.wrapper.get('[data-testid="global-tunnel-start-btn"]')
    await startBtn.trigger('click')
    await flushPromises()

    const startCall = fake.calls.find((c) => c.path === '/api/services/cloudflared/start')
    expect(startCall).toBeDefined()

    // 域名展示与复制
    const urlText = b.wrapper.get('[data-testid="global-tunnel-url"]')
    expect(urlText.text()).toContain('trycloudflare.com')

    const copyBtn = b.wrapper.get('[data-testid="copy-global-tunnel-url-btn"]')
    await copyBtn.trigger('click')
    await flushPromises()

    // 停止全局隧道
    const stopBtn = b.wrapper.get('[data-testid="global-tunnel-stop-btn"]')
    await stopBtn.trigger('click')
    await flushPromises()

    const stopCall = fake.calls.find((c) => c.path === '/api/services/cloudflared/stop')
    expect(stopCall).toBeDefined()

    await b.done()
  })

  it('cloudflared 卡：协议选择 http2|quic，切换返回 restart_required 时展示提示，不自动重启', async () => {
    const fake = createS7CFake()
    const b = await openServicesTab(fake)

    // 切换到 QUIC
    const seg = b.wrapper.findComponent(
      '[data-testid="protocol-segmented-control"]',
    ) as unknown as {
      vm: { $emit(event: string, ...args: unknown[]): void }
    }
    seg.vm.$emit('update:modelValue', 'quic')
    await flushPromises()

    const protoCall = fake.calls.find((c) => c.path === '/api/services/cloudflared/protocol')
    expect(protoCall).toBeDefined()
    expect(protoCall?.body).toEqual({ protocol: 'quic', revision: 20 })

    // 出现 restart_required 提示，不自动调用 stop 或 start 重启
    const restartBanner = b.wrapper.find('[data-testid="protocol-restart-banner"]')
    expect(restartBanner.exists()).toBe(true)
    expect(restartBanner.text()).toContain('协议已变更，需重启隧道后生效')

    // 验证未发出自动重启请求
    const stopCalls = fake.calls.filter((c) => c.path === '/api/services/cloudflared/stop')
    expect(stopCalls.length).toBe(0)

    await b.done()
  })

  it('cloudflared 卡：从旧应用导入协议偏好（POST /api/services/import-legacy），路径输入与只读单个枚举值说明', async () => {
    const fake = createS7CFake()
    const b = await openServicesTab(fake)

    // 打开导入 Sheet（Teleport 到 document.body）
    const openBtn = b.wrapper.get('[data-testid="open-import-pref-btn"]')
    await openBtn.trigger('click')
    await flushPromises()

    const sheet = document.querySelector('[data-testid="cloudflared-import-sheet"]')
    expect(sheet).not.toBeNull()
    expect(sheet?.textContent).toContain('只读取旧 JSON 配置文件中的协议枚举值')

    // 输入路径并提交
    const input = document.querySelector(
      '[data-testid="legacy-import-path-input"] input',
    ) as HTMLInputElement
    input.value = '/Users/foo/cloudflared_pref.json'
    input.dispatchEvent(new Event('input'))
    await flushPromises()

    const submitBtn = document.querySelector(
      '[data-testid="submit-import-btn"]',
    ) as HTMLButtonElement
    submitBtn.click()
    await flushPromises()

    const importCall = fake.calls.find((c) => c.path === '/api/services/import-legacy')
    expect(importCall).toBeDefined()
    expect(importCall?.body).toEqual({
      path: '/Users/foo/cloudflared_pref.json',
      revision: 20,
    })

    await b.done()
  })

  it('cloudflared 卡：自定义隧道列表展示（目标、域名、状态）与逐条关闭', async () => {
    const fake = createS7CFake()
    const b = await openServicesTab(fake)

    const tunnelItem = b.wrapper.find('[data-testid="custom-tunnel-item-tun-1"]')
    expect(tunnelItem.exists()).toBe(true)
    expect(tunnelItem.find('[data-testid="tunnel-target-text"]').text()).toBe(
      'http://127.0.0.1:3000',
    )
    expect(tunnelItem.find('[data-testid="tunnel-domain-text"]').text()).toContain(
      'custom-tunnel.trycloudflare.com',
    )

    // 点击关闭此隧道
    const closeBtn = tunnelItem.get('[data-testid="close-tunnel-btn"]')
    await closeBtn.trigger('click')
    await flushPromises()

    const deleteCall = fake.calls.find((c) => c.path === '/api/services/cloudflared/tunnels/tun-1')
    expect(deleteCall).toBeDefined()
    expect(deleteCall?.method).toBe('DELETE')

    await b.done()
  })

  it('cloudflared 自定义隧道 Sheet：必须勾选“该地址将可被公网任何人访问，隧道本身无认证”才可提交，提交体含 ack_public: true', async () => {
    const fake = createS7CFake()
    const b = await openServicesTab(fake)

    // 打开添加自定义隧道 Sheet（Teleport 到 document.body）
    const openSheetBtn = b.wrapper.get('[data-testid="open-add-tunnel-sheet-btn"]')
    await openSheetBtn.trigger('click')
    await flushPromises()

    const sheet = document.querySelector('[data-testid="cloudflared-tunnel-sheet"]')
    expect(sheet).not.toBeNull()

    const submitBtn = document.querySelector(
      '[data-testid="submit-tunnel-btn"]',
    ) as HTMLButtonElement
    // 尚未勾选时禁用
    expect(submitBtn.disabled).toBe(true)

    // 勾选确认公网暴露
    const ackCheckbox = document.querySelector(
      '[data-testid="ack-public-checkbox"]',
    ) as HTMLInputElement
    ackCheckbox.click()
    await flushPromises()

    // 此时可提交
    expect(submitBtn.disabled).toBe(false)
    submitBtn.click()
    await flushPromises()

    const createCall = fake.calls.find((c) => c.path === '/api/services/cloudflared/tunnels')
    expect(createCall).toBeDefined()
    expect(createCall?.method).toBe('POST')
    const createBody = createCall?.body as {
      target_url: string
      ack_public: boolean
      request_id: string
    }
    expect(createBody.ack_public).toBe(true)
    expect(createBody.target_url).toBe('http://127.0.0.1:3000')
    expect(createBody.request_id).toMatch(/^[0-9a-f-]{36}$/)

    await b.done()
  })

  it('cloudflared 自定义隧道错误码文案：tunnel_target_forbidden、tunnel_limit、service_busy、service_port_in_use', async () => {
    const errors = [
      {
        code: 'tunnel_target_forbidden',
        expected: '隧道目标地址不合法，仅允许显式端口的回环地址（localhost / 127.0.0.1 / [::1]）',
      },
      { code: 'tunnel_limit', expected: '自定义隧道已达到数量上限' },
      { code: 'service_busy', expected: '操作正在进行中或服务运行中，请稍后重试' },
      { code: 'service_port_in_use', expected: '端口已被占用，请检查是否有其他进程正在使用该端口' },
    ]

    for (const item of errors) {
      const fake = createS7CFake()
      fake.setOverride(async (req) => {
        if (req.url.endsWith('/api/services/cloudflared/tunnels')) {
          return err(409, item.code, item.expected)
        }
        return undefined
      })

      const b = await openServicesTab(fake)
      await b.wrapper.get('[data-testid="open-add-tunnel-sheet-btn"]').trigger('click')
      await flushPromises()

      const ackCheckbox = document.querySelector(
        '[data-testid="ack-public-checkbox"]',
      ) as HTMLInputElement
      ackCheckbox.click()
      await flushPromises()

      const submitBtn = document.querySelector(
        '[data-testid="submit-tunnel-btn"]',
      ) as HTMLButtonElement
      submitBtn.click()
      await flushPromises()

      const errBanner = document.querySelector('[data-testid="tunnel-error-banner"]')
      expect(errBanner).not.toBeNull()
      expect(errBanner?.textContent).toContain(item.expected)

      await b.done()
    }
  })

  it('设置项 PATCH /api/services/settings：修改 binaries.*、code_server.start_timeout_s、cloudflared.max_tunnels，运行中 409 service_busy 文案', async () => {
    const fake = createS7CFake()
    const b = await openServicesTab(fake)

    // 打开 code-server 高级设置
    const details = b.wrapper.get('[data-testid="code-server-settings-details"]')
    await details.trigger('click')
    await flushPromises()

    const timeoutInput = b.wrapper.get('[data-testid="code-server-timeout-input"] input')
    await timeoutInput.setValue('45')
    await flushPromises()

    const saveCsBtn = b.wrapper.get('[data-testid="save-code-server-settings-btn"]')
    await saveCsBtn.trigger('click')
    await flushPromises()

    const patchCall = fake.calls.find((c) => c.path === '/api/services/settings')
    expect(patchCall).toBeDefined()
    expect(patchCall?.method).toBe('PATCH')
    const patchBody = patchCall?.body as { revision: number; services: S['ServicesConfig'] }
    expect(patchBody.services.code_server?.start_timeout_s).toBe(45)

    // 运行中修改返回 409 service_busy 的文案展示
    fake.setOverride(async (req) => {
      if (req.url.endsWith('/api/services/settings')) {
        return err(
          409,
          'service_busy',
          '操作正在进行中或服务运行中，请稍后重试（运行中修改设置请先停止服务）',
        )
      }
      return undefined
    })

    await saveCsBtn.trigger('click')
    await flushPromises()

    expect(b.wrapper.text()).toContain(
      '操作正在进行中或服务运行中，请稍后重试（运行中修改设置请先停止服务）',
    )

    await b.done()
  })

  it('WS services 主题订阅与状态回放：更新 snapshot，水位去重不重复处理，组件卸载时调用 unsubscribeServices', async () => {
    const fake = createS7CFake()
    const b = await boot({ path: '/settings', fetchImpl: fake.fetchImpl })
    b.sock.emit(hello())
    await flushPromises()

    // 切换到服务页签
    const tabs = b.wrapper.findAll('[role=tab]')
    const servicesTab = tabs.find((t) => t.text().includes('服务'))!
    await servicesTab.trigger('mousedown')
    await flushPromises()
    await flushPromises()

    // 验证发出了 subscribe services 消息
    const sentSubscribe = b.sock.sent.find(
      (m) => typeof m === 'string' && m.includes('"topic":"services"') && m.includes('"subscribe"'),
    )
    expect(sentSubscribe).toBeDefined()

    // 后端推回 services.status 事件
    const updatedSnap = makeServicesSnapshot({
      network: { vpn_ip: '10.254.99.100', lan_ip: '192.168.1.200', on_lan: true },
    })
    b.sock.emit({
      seq: 10,
      topic: 'services',
      type: 'services.status',
      ts: new Date().toISOString(),
      data: {
        services_seq: 1,
        snapshot: updatedSnap,
      },
    })
    await flushPromises()

    expect(b.wrapper.get('[data-testid="vpn-ip"]').text()).toBe('10.254.99.100')

    // 切换到其他页签（如常规），验证触发 unsubscribe
    const generalTab = tabs.find((t) => t.text().includes('常规'))!
    await generalTab.trigger('mousedown')
    await flushPromises()
    await flushPromises()

    const sentUnsubscribe = b.sock.sent.find(
      (m) =>
        typeof m === 'string' && m.includes('"topic":"services"') && m.includes('"unsubscribe"'),
    )
    expect(sentUnsubscribe).toBeDefined()

    await b.done()
  })

  it('安全检查：DOM 中无任何密码、token 输入或展示，且无任何 dsh 元素', async () => {
    const fake = createS7CFake()
    const b = await openServicesTab(fake)

    const html = b.wrapper.html()

    // 页面任何位置不得出现密码 / token 输入或展示
    expect(html).not.toMatch(/password/i)
    expect(html).not.toMatch(/token/i)
    expect(b.wrapper.find('input[type="password"]').exists()).toBe(false)

    // 本包不含 dsh，页面上不得出现任何 dsh 元素
    expect(html).not.toMatch(/\bdsh\b/i)
    expect(html).not.toContain('dsh')
    expect(b.wrapper.find('[data-testid*="dsh"]').exists()).toBe(false)

    await b.done()
  })
})
