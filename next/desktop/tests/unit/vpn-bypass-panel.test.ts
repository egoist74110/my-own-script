// VPN 分流面板单测：直接挂载组件，注入假 API 客户端（不连真实后端、不改路由）。
// CRUD、保存/同步、安装应用/停用撤销、取消授权、状态与目标、轮询不覆盖草稿、只读/忙碌、预览只发 apply:false。
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backendRuntimeKey } from '@/app/backend-runtime'
import { createApiClient } from '@/api/client'
import { useBackendStore } from '@/stores/backend'
import VpnBypassPanel from '@/features/settings/VpnBypassPanel.vue'
import type { VpnBypassView } from '@/features/settings/api'
import { err, json } from './settings-fake'

interface Call {
  method: string
  path: string
  body: unknown
}

function makeStatus(over: Record<string, unknown> = {}) {
  return {
    mode: 'managed',
    installed: false,
    running: false,
    synced: false,
    state: 'not_installed',
    message: '助手未安装',
    last_sweep_at: null,
    targets: [],
    errors: [],
    limitations: ['可能压不过其他策略路由'],
    ...over,
  }
}

function makeView(
  revision = 5,
  over: Record<string, unknown> = {},
  status: Record<string, unknown> = {},
): VpnBypassView {
  return {
    revision,
    settings: {
      enabled: false,
      gateway: null,
      interface: null,
      interval_s: 20,
      retention_s: 300,
      apps: [
        {
          id: 'app-1',
          name: '游戏加速器',
          enabled: true,
          executable_path: '/opt/acc/bin/acc',
          application_path: null,
        },
      ],
      targets: ['203.0.113.7'],
      ...over,
    },
    status: makeStatus(status),
  } as unknown as VpnBypassView
}

const ENABLED = { enabled: true, gateway: '192.168.1.1', interface: 'en0' }
const INSTALLED = {
  installed: true,
  running: true,
  synced: true,
  state: 'active',
  message: '运行中',
}

function setup(initial = makeView()) {
  const calls: Call[] = []
  const state = { view: initial, handler: null as null | ((c: Call) => Response | undefined) }
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init)
    const path = new URL(req.url, 'http://127.0.0.1').pathname
    let body: unknown
    try {
      const t = await req.clone().text()
      if (t) body = JSON.parse(t)
    } catch {
      // 非 JSON 请求体
    }
    const call = { method: req.method.toUpperCase(), path, body }
    calls.push(call)
    const custom = state.handler?.(call)
    if (custom) return custom
    if (path === '/api/vpn/bypass' && call.method === 'GET') return json(state.view)
    if (path === '/api/vpn/bypass/settings' && call.method === 'PATCH') {
      const b = body as { revision: number; settings: VpnBypassView['settings'] }
      if (b.revision !== state.view.revision) return err(409, 'revision_conflict', '版本冲突')
      state.view = { ...state.view, revision: state.view.revision + 1, settings: b.settings }
      return json({ revision: state.view.revision })
    }
    if (path === '/api/vpn/bypass/sweep') {
      return json({
        applied: false,
        requires_privilege: false,
        targets: ['198.51.100.9'],
        gateway: null,
        interface: null,
        errors: [],
        message: '预览完成',
      })
    }
    if (path === '/api/vpn/bypass/activate' && call.method === 'POST')
      return json(
        (state.view = makeView(state.view.revision, { ...state.view.settings }, INSTALLED)),
      )
    if (path === '/api/vpn/bypass/deactivate' && call.method === 'POST')
      return json((state.view = makeView(state.view.revision, { ...state.view.settings })))
    return json({})
  }) as unknown as typeof fetch
  const client = createApiClient({ port: 1, token: 't' }, fetchImpl)
  return { calls, state, client }
}

async function mountPanel(
  ctx: ReturnType<typeof setup>,
  props: { revision?: number | null; busy?: boolean; writable?: boolean } = { writable: true },
) {
  useBackendStore().setConnection('online')
  const wrapper = mount(VpnBypassPanel, {
    props,
    global: { provide: { [backendRuntimeKey as symbol]: { api: () => ctx.client } } },
  })
  await flushPromises()
  return wrapper
}

describe('VpnBypassPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('加载后展示规则/目标、精简的能力边界与未安装状态', async () => {
    const w = await mountPanel(setup())
    expect(w.findAll('[data-testid=bp-app-row]')).toHaveLength(1)
    expect((w.find('[data-testid=bp-app-name]').element as HTMLInputElement).value).toBe(
      '游戏加速器',
    )
    expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
      '203.0.113.7',
    )
    const limits = w.find('[data-testid=bp-limits]').text()
    expect(limits).toContain('IPv4')
    expect(limits).toContain('共用')
    expect(limits).toContain('不是按进程隔离')
    expect(limits).toContain('不覆盖 IPv6')
    expect(w.find('[data-testid=bp-status]').text()).toContain('助手未安装')
  })

  it('后端重新上线时刷新，仍保留未保存的草稿', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx)
    await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
    useBackendStore().setConnection('offline')
    await flushPromises()
    ctx.state.view = makeView(6)
    useBackendStore().setConnection('online')
    await flushPromises()
    expect(ctx.calls.filter((c) => c.method === 'GET')).toHaveLength(2)
    expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
      '9.9.9.9',
    )
    expect(w.find('[data-testid=bp-conflict-banner]').exists()).toBe(true)
  })

  it('CRUD：新增/修改/删除应用与目标后保存，带当前修订号，未安装时不触发安装', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx)
    await w.find('[data-testid=bp-add-app-btn]').trigger('click')
    const rows = w.findAll('[data-testid=bp-app-row]')
    expect(rows).toHaveLength(2)
    await rows[1]!.find('[data-testid=bp-app-name]').setValue('浏览器')
    await rows[1]!.find('[data-testid=bp-app-kind]').setValue('application')
    await rows[1]!.find('[data-testid=bp-app-path]').setValue('/Applications/Foo.app')
    await rows[0]!.find('[data-testid=bp-app-remove]').trigger('click')
    await w.find('[data-testid=bp-targets-input]').setValue('10.0.0.0/8\n10.0.0.0/8, 1.2.3.4')
    expect(w.find('[data-testid=bp-dirty-tag]').exists()).toBe(true)

    await w.find('[data-testid=bp-save-btn]').trigger('click')
    await flushPromises()
    const patch = ctx.calls.find((c) => c.method === 'PATCH')!
    const body = patch.body as { revision: number; settings: VpnBypassView['settings'] }
    expect(body.revision).toBe(5)
    expect(body.settings.targets).toEqual(['10.0.0.0/8', '1.2.3.4'])
    expect(body.settings.apps).toHaveLength(1)
    expect(body.settings.apps?.[0]).toMatchObject({
      name: '浏览器',
      executable_path: null,
      application_path: '/Applications/Foo.app',
    })
    expect(w.find('[data-testid=bp-dirty-tag]').exists()).toBe(false)
    expect(w.find('[data-testid=bp-notice]').text()).toContain('尚未安装')
    expect(w.find('[data-testid=bp-save-btn]').text()).toBe('保存配置')
    expect(ctx.calls.some((c) => c.path.endsWith('/activate'))).toBe(false)
  })

  it('前端预检：启用缺网关、相对路径、非法目标时禁止保存且不发请求', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx)
    await w.find('[data-testid=bp-targets-input]').setValue('999.1.1.1')
    await w.find('[data-testid=bp-app-path]').setValue('relative/path')
    await w.find('[data-testid=bp-enabled-switch]').trigger('click')
    const problems = w.find('[data-testid=bp-problems]').text()
    expect(problems).toContain('启用分流需同时填写网关与网卡')
    expect(problems).toContain('合法 IPv4/CIDR')
    expect(problems).toContain('绝对路径')
    expect((w.find('[data-testid=bp-save-btn]').element as HTMLButtonElement).disabled).toBe(true)
    expect(ctx.calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('只提供通用应用规则，不包含写死的应用预设；路径为空时不能保存', async () => {
    const w = await mountPanel(setup())
    expect(w.find('[data-testid=bp-add-uu-btn]').exists()).toBe(false)
    await w.find('[data-testid=bp-add-app-btn]').trigger('click')
    const rows = w.findAll('[data-testid=bp-app-row]')
    expect((rows[1]!.find('[data-testid=bp-app-path]').element as HTMLInputElement).value).toBe('')
    expect(w.find('[data-testid=bp-problems]').text()).toContain('仅填写一个路径')
    expect((w.find('[data-testid=bp-save-btn]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('真实开关状态写入配置：总开关和应用开关保存、刷新后保持一致', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx)
    const toggle = () => w.find('[data-testid=bp-enabled-switch]')
    expect(toggle().attributes('aria-checked')).toBe('false')
    expect(w.find('[data-testid=bp-app-enabled]').attributes('aria-checked')).toBe('true')
    await w.find('[data-testid=bp-gateway-input]').setValue('192.168.1.1')
    await w.find('[data-testid=bp-interface-input]').setValue('en0')
    await toggle().trigger('click')
    await w.find('[data-testid=bp-app-enabled]').trigger('click')
    expect(toggle().attributes('aria-checked')).toBe('true')
    expect(w.find('[data-testid=bp-dirty-tag]').exists()).toBe(true)
    await w.find('[data-testid=bp-save-btn]').trigger('click')
    await flushPromises()
    const patch = ctx.calls.find((c) => c.method === 'PATCH')!
    const body = patch.body as { settings: VpnBypassView['settings'] }
    expect(body.settings.enabled).toBe(true)
    expect(body.settings.apps?.[0]?.enabled).toBe(false)
    await w.find('[data-testid=bp-refresh-btn]').trigger('click')
    await flushPromises()
    expect(toggle().attributes('aria-checked')).toBe('true')
    expect(w.find('[data-testid=bp-app-enabled]').attributes('aria-checked')).toBe('false')
  })

  it('未保存时禁止预览旧配置，隐藏旧结果并提示先保存', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx)
    await w.find('[data-testid=bp-preview-btn]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid=bp-preview-result]').exists()).toBe(true)
    await w.find('[data-testid=bp-enabled-switch]').trigger('click')
    expect(w.find('[data-testid=bp-problems]').text()).toContain('网关与网卡')
    expect(w.find('[data-testid=bp-preview-dirty-hint]').text()).toContain('先补全配置并保存')
    expect(w.find('[data-testid=bp-preview-result]').exists()).toBe(false)
    expect((w.find('[data-testid=bp-preview-btn]').element as HTMLButtonElement).disabled).toBe(
      true,
    )
    await w.find('[data-testid=bp-preview-btn]').trigger('click')
    expect(ctx.calls.filter((c) => c.path.endsWith('/sweep'))).toHaveLength(1)
  })

  it('静默刷新不覆盖脏草稿，仅提示远端更新；显式确认后才采用', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx, { writable: true, revision: 5 })
    await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
    ctx.state.view = makeView(6, { targets: ['5.5.5.5'] })
    await w.setProps({ revision: 6 })
    await flushPromises()
    expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
      '9.9.9.9',
    )
    expect(w.find('[data-testid=bp-conflict-banner]').text()).toContain('版本 6')
    await w.find('[data-testid=bp-reload-remote-btn]').trigger('click')
    await w.find('[data-testid=bp-confirm-reload-btn]').trigger('click')
    await flushPromises()
    expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
      '5.5.5.5',
    )
    expect(w.find('[data-testid=bp-conflict-banner]').exists()).toBe(false)
  })

  it('干净草稿时刷新直接采用新版本', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx, { writable: true, revision: 5 })
    ctx.state.view = makeView(6, { targets: ['5.5.5.5'] })
    await w.setProps({ revision: 6 })
    await flushPromises()
    expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
      '5.5.5.5',
    )
  })

  it('保存遇 409：保留草稿、显示错误与远端更新，不自动重试', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx)
    await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
    ctx.state.view = makeView(8)
    await w.find('[data-testid=bp-save-btn]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid=bp-save-error]').text()).toContain('刷新')
    expect(w.find('[data-testid=bp-conflict-banner]').text()).toContain('版本 8')
    expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
      '9.9.9.9',
    )
    expect(ctx.calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
  })

  it('保存失败（非冲突）显示错误且草稿保持脏', async () => {
    const ctx = setup()
    ctx.state.handler = (c) =>
      c.method === 'PATCH' ? err(422, 'validation_error', '网关不在物理网卡直连网段') : undefined
    const w = await mountPanel(ctx)
    await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
    await w.find('[data-testid=bp-save-btn]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid=bp-save-error]').text()).toContain('网关不在物理网卡直连网段')
    expect(w.find('[data-testid=bp-dirty-tag]').exists()).toBe(true)
  })

  it('加载失败显示错误并保留重试入口', async () => {
    const ctx = setup()
    ctx.state.handler = (c) => (c.method === 'GET' ? err(500, 'store_unavailable', 'x') : undefined)
    const w = await mountPanel(ctx)
    expect(w.find('[data-testid=bp-load-error]').text()).toContain('配置存储不可用')
    expect(w.find('[data-testid=bp-apps-empty]').exists()).toBe(false)
    ctx.state.handler = null
    await w.find('[data-testid=bp-refresh-btn]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid=bp-load-error]').exists()).toBe(false)
    expect(w.findAll('[data-testid=bp-app-row]')).toHaveLength(1)
  })

  it('只读或忙碌时禁用编辑与保存', async () => {
    const w = await mountPanel(setup(), { writable: false })
    expect(w.find('[data-testid=bp-readonly-hint]').exists()).toBe(true)
    expect((w.find('[data-testid=bp-add-app-btn]').element as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).disabled).toBe(
      true,
    )
    const busy = await mountPanel(setup(), { writable: true, busy: true })
    expect((busy.find('[data-testid=bp-add-app-btn]').element as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect((busy.find('[data-testid=bp-preview-btn]').element as HTMLButtonElement).disabled).toBe(
      true,
    )
  })

  it('预览只发 apply:false 并展示发现的目标', async () => {
    const ctx = setup()
    const w = await mountPanel(ctx)
    await w.find('[data-testid=bp-preview-btn]').trigger('click')
    await flushPromises()
    const sweep = ctx.calls.find((c) => c.path === '/api/vpn/bypass/sweep')!
    expect(sweep.body).toEqual({ apply: false })
    expect(w.find('[data-testid=bp-preview-targets]').text()).toContain('198.51.100.9')
  })

  describe('安装/应用/停用', () => {
    const readyView = (status: Record<string, unknown> = {}) => makeView(5, ENABLED, status)
    const btn = (w: Awaited<ReturnType<typeof mountPanel>>, id: string) =>
      w.find(`[data-testid=${id}]`).element as HTMLButtonElement

    it('不再有 Python 路径/导出入口；未安装时主按钮为“授权安装并应用”', async () => {
      const w = await mountPanel(setup(readyView()))
      expect(w.find('[data-testid=bp-python-input]').exists()).toBe(false)
      expect(w.find('[data-testid=bp-export-btn]').exists()).toBe(false)
      expect(w.find('[data-testid=bp-activate-btn]').text()).toBe('授权安装并应用')
      expect(btn(w, 'bp-activate-btn').disabled).toBe(false)
      expect(btn(w, 'bp-deactivate-btn').disabled).toBe(true)
    })

    it('安装成功：带修订号 POST activate，并按真实快照展示状态与目标', async () => {
      const ctx = setup(readyView())
      const w = await mountPanel(ctx)
      ctx.state.handler = (c) =>
        c.path.endsWith('/activate')
          ? json(
              (ctx.state.view = makeView(5, ENABLED, {
                ...INSTALLED,
                last_sweep_at: 1700000000,
                targets: [
                  {
                    target: '1.2.3.4',
                    gateway: '192.168.1.1',
                    interface: 'en0',
                    owned: true,
                    verified: true,
                  },
                  {
                    target: '5.6.7.8',
                    gateway: null,
                    interface: null,
                    owned: false,
                    verified: false,
                  },
                ],
              })),
            )
          : undefined
      await w.find('[data-testid=bp-activate-btn]').trigger('click')
      await flushPromises()
      const act = ctx.calls.find((c) => c.path.endsWith('/activate'))!
      expect(act.body).toEqual({ revision: 5 })
      // 操作后取回了最新快照
      expect(ctx.calls.filter((c) => c.method === 'GET').length).toBeGreaterThanOrEqual(2)
      expect(w.find('[data-testid=bp-state-tag]').text()).toBe('路由已验证')
      expect(w.find('[data-testid=bp-installed-tag]').text()).toBe('助手已安装')
      expect(w.find('[data-testid=bp-running-tag]').text()).toBe('运行中')
      expect(w.find('[data-testid=bp-synced-tag]').text()).toBe('配置已同步')
      const rows = w.findAll('[data-testid=bp-target-row]')
      expect(rows).toHaveLength(2)
      expect(rows[0]!.text()).toContain('已验证')
      expect(rows[0]!.text()).toContain('本工具持有')
      expect(rows[1]!.text()).toContain('未验证')
      expect(rows[1]!.text()).toContain('非本工具持有')
      expect(w.find('[data-testid=bp-activate-btn]').text()).toBe('重新应用')
      expect(w.find('[data-testid=bp-last-sweep]').text()).not.toContain('尚未扫描')
    })

    it('已安装但待同步（pending）与已生效（active）显示不同；零目标不算成功', async () => {
      const pending = await mountPanel(
        setup(readyView({ installed: true, running: true, synced: false, state: 'pending' })),
      )
      expect(pending.find('[data-testid=bp-state-tag]').text()).toBe('待同步')
      expect(pending.find('[data-testid=bp-synced-tag]').text()).toBe('配置未同步')
      expect(pending.find('[data-testid=bp-activate-btn]').text()).toBe('应用已保存配置')

      const active = await mountPanel(setup(readyView(INSTALLED)))
      expect(active.find('[data-testid=bp-state-tag]').text()).toBe('路由已验证')
      expect(active.find('[data-testid=bp-no-targets]').text()).toContain('没有生效')
      expect(active.find('[data-testid=bp-target-list]').exists()).toBe(false)
    })

    it('状态中的错误列表被展示', async () => {
      const w = await mountPanel(
        setup(readyView({ ...INSTALLED, state: 'degraded', errors: ['路由添加失败 1.2.3.4'] })),
      )
      expect(w.find('[data-testid=bp-status-errors]').text()).toContain('路由添加失败')
    })

    it('取消系统授权：显示“已取消”，不当作错误，并刷新真实状态', async () => {
      const ctx = setup(readyView())
      ctx.state.handler = (c) =>
        c.path.endsWith('/activate')
          ? err(409, 'bypass_auth_cancelled', '用户取消了授权')
          : undefined
      const w = await mountPanel(ctx)
      await w.find('[data-testid=bp-activate-btn]').trigger('click')
      await flushPromises()
      expect(w.find('[data-testid=bp-cancelled]').exists()).toBe(true)
      expect(w.find('[data-testid=bp-action-error]').exists()).toBe(false)
      expect(w.find('[data-testid=bp-installed-tag]').text()).toBe('助手未安装')
      expect(w.find('[data-testid=bp-notice]').exists()).toBe(false)
    })

    it('应用失败显示错误且不声称成功', async () => {
      const ctx = setup(readyView())
      ctx.state.handler = (c) =>
        c.path.endsWith('/activate')
          ? err(500, 'bypass_install_failed', '安装失败: 权限不足')
          : undefined
      const w = await mountPanel(ctx)
      await w.find('[data-testid=bp-activate-btn]').trigger('click')
      await flushPromises()
      expect(w.find('[data-testid=bp-action-error]').text()).toContain('安装失败')
      expect(w.find('[data-testid=bp-notice]').exists()).toBe(false)
      expect(w.find('[data-testid=bp-cancelled]').exists()).toBe(false)
    })

    it('配置未启用或有未保存修改时不能应用', async () => {
      const off = await mountPanel(setup(makeView(5, {}, {})))
      expect(btn(off, 'bp-activate-btn').disabled).toBe(true)
      expect(off.find('[data-testid=bp-activate-disabled-hint]').exists()).toBe(true)

      const w = await mountPanel(setup(readyView()))
      await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
      expect(btn(w, 'bp-activate-btn').disabled).toBe(true)
      expect(btn(w, 'bp-preview-btn').disabled).toBe(true)
      expect(w.find('[data-testid=bp-activate-dirty-hint]').exists()).toBe(true)
    })

    it('已安装：保存按钮为“保存并同步”，保存后取回真实状态', async () => {
      const ctx = setup(readyView(INSTALLED))
      const w = await mountPanel(ctx)
      expect(w.find('[data-testid=bp-save-btn]').text()).toBe('保存并同步')
      expect(w.find('[data-testid=bp-save-sync-hint]').text()).toContain('授权')
      await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
      const gets = ctx.calls.filter((c) => c.method === 'GET').length
      await w.find('[data-testid=bp-save-btn]').trigger('click')
      await flushPromises()
      expect(ctx.calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
      expect(ctx.calls.filter((c) => c.method === 'GET').length).toBe(gets + 1)
      expect(ctx.calls.some((c) => c.path.endsWith('/activate'))).toBe(false)
      expect(w.find('[data-testid=bp-dirty-tag]').exists()).toBe(false)
    })

    it('保存已落库但同步失败：显式“已保存未同步”，保留草稿、刷新版本，可重试', async () => {
      const ctx = setup(readyView(INSTALLED))
      const w = await mountPanel(ctx)
      await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
      ctx.state.handler = (c) => {
        if (c.method !== 'PATCH') return undefined
        const b = c.body as { settings: VpnBypassView['settings'] }
        ctx.state.view = makeView(
          6,
          { ...b.settings },
          {
            ...INSTALLED,
            synced: false,
            state: 'error',
          },
        )
        return err(409, 'bypass_sync_failed', '配置已保存，但助手更新失败，请查看实际状态。', {
          cause: 'bypass_authorization_cancelled',
        })
      }
      await w.find('[data-testid=bp-save-btn]').trigger('click')
      await flushPromises()
      expect(w.find('[data-testid=bp-sync-error]').text()).toContain('已保存')
      expect(w.find('[data-testid=bp-cancelled]').text()).toContain('已取消系统授权')
      expect(w.find('[data-testid=bp-cancelled]').text()).not.toContain('未做任何更改')
      expect(w.find('[data-testid=bp-save-error]').exists()).toBe(false)
      expect(w.find('[data-testid=bp-conflict-banner]').exists()).toBe(false)
      expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
        '9.9.9.9',
      )
      expect(w.find('[data-testid=bp-synced-tag]').text()).toBe('配置未同步')
      // 版本已刷新：重试用 6，不再冲突
      ctx.state.handler = null
      await w.find('[data-testid=bp-targets-input]').setValue('8.8.8.8')
      await w.find('[data-testid=bp-save-btn]').trigger('click')
      await flushPromises()
      const patches = ctx.calls.filter((c) => c.method === 'PATCH')
      expect((patches[1]!.body as { revision: number }).revision).toBe(6)
    })

    it('同步失败时服务端配置与草稿不同：保留草稿并采用新版本号', async () => {
      const ctx = setup(readyView(INSTALLED))
      const w = await mountPanel(ctx)
      await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
      ctx.state.handler = (c) => {
        if (c.method !== 'PATCH') return undefined
        ctx.state.view = makeView(6, { ...ENABLED, targets: ['7.7.7.7'] }, INSTALLED)
        return err(502, 'bypass_sync_failed', '配置已保存，但同步失败')
      }
      await w.find('[data-testid=bp-save-btn]').trigger('click')
      await flushPromises()
      expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
        '9.9.9.9',
      )
      expect(w.find('[data-testid=bp-dirty-tag]').exists()).toBe(true)
      expect(w.find('[data-testid=bp-sync-error]').exists()).toBe(true)
    })

    it('停用并撤销：已安装即可，哪怕未启用、草稿脏且非法；草稿保留', async () => {
      const ctx = setup(
        makeView(5, {}, { installed: true, running: true, synced: true, state: 'active' }),
      )
      const w = await mountPanel(ctx)
      await w.find('[data-testid=bp-gateway-input]').setValue('not-an-ip')
      await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
      expect(w.find('[data-testid=bp-problems]').exists()).toBe(true)
      expect(btn(w, 'bp-activate-btn').disabled).toBe(true)
      expect(btn(w, 'bp-deactivate-btn').disabled).toBe(false)
      await w.find('[data-testid=bp-deactivate-btn]').trigger('click')
      await flushPromises()
      const call = ctx.calls.find((c) => c.path.endsWith('/deactivate'))!
      expect(call.body).toEqual({ revision: 5 })
      expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
        '9.9.9.9',
      )
      expect(w.find('[data-testid=bp-installed-tag]').text()).toBe('助手未安装')
    })

    it('操作进行中：所有变更按钮与输入被锁定，完成后恢复', async () => {
      const ctx = setup(readyView())
      const w = await mountPanel(ctx)
      let release: (r: Response) => void = () => {}
      ctx.state.handler = (c) => {
        if (!c.path.endsWith('/activate')) return undefined
        return new Promise<Response>((r) => (release = r)) as unknown as Response
      }
      await w.find('[data-testid=bp-activate-btn]').trigger('click')
      await flushPromises()
      expect(btn(w, 'bp-save-btn').disabled).toBe(true)
      expect(btn(w, 'bp-activate-btn').disabled).toBe(true)
      expect(btn(w, 'bp-deactivate-btn').disabled).toBe(true)
      expect(btn(w, 'bp-preview-btn').disabled).toBe(true)
      expect(btn(w, 'bp-add-app-btn').disabled).toBe(true)
      expect(w.find('[data-testid=bp-op-hint]').exists()).toBe(true)
      ctx.state.handler = null
      release(json(makeView(5, ENABLED, INSTALLED)))
      await flushPromises()
      expect(w.find('[data-testid=bp-op-hint]').exists()).toBe(false)
      expect(btn(w, 'bp-add-app-btn').disabled).toBe(false)
    })

    it('只读或 busy：应用与停用都禁用，且不发请求', async () => {
      const installed = makeView(5, ENABLED, INSTALLED)
      for (const props of [{ writable: false }, { writable: true, busy: true }]) {
        const ctx = setup(installed)
        const w = await mountPanel(ctx, props)
        expect(btn(w, 'bp-activate-btn').disabled).toBe(true)
        expect(btn(w, 'bp-deactivate-btn').disabled).toBe(true)
        expect(btn(w, 'bp-save-btn').disabled).toBe(true)
        await w.find('[data-testid=bp-deactivate-btn]').trigger('click')
        expect(ctx.calls.some((c) => c.method === 'POST')).toBe(false)
      }
    })

    it('activate 遇修订号冲突：提示远端更新，不覆盖', async () => {
      const ctx = setup(readyView())
      const w = await mountPanel(ctx)
      ctx.state.handler = (c) =>
        c.path.endsWith('/activate') ? err(409, 'revision_conflict', '版本冲突') : undefined
      ctx.state.view = makeView(9, ENABLED)
      await w.find('[data-testid=bp-activate-btn]').trigger('click')
      await flushPromises()
      expect(w.find('[data-testid=bp-action-error]').text()).toContain('刷新')
      expect(w.find('[data-testid=bp-conflict-banner]').text()).toContain('版本 9')
    })
  })

  describe('状态轮询', () => {
    beforeEach(() => vi.useFakeTimers())
    afterEach(() => vi.useRealTimers())

    it('约 5 秒轮询状态；脏草稿不被覆盖、版本不变；卸载后停止', async () => {
      const ctx = setup(makeView(5, ENABLED))
      const w = await mountPanel(ctx)
      await w.find('[data-testid=bp-targets-input]').setValue('9.9.9.9')
      const gets = () => ctx.calls.filter((c) => c.method === 'GET').length
      const g0 = gets()
      ctx.state.view = makeView(5, ENABLED, INSTALLED)
      await vi.advanceTimersByTimeAsync(5000)
      expect(gets()).toBe(g0 + 1)
      expect(w.find('[data-testid=bp-state-tag]').text()).toBe('路由已验证')
      expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
        '9.9.9.9',
      )
      expect(w.find('[data-testid=bp-conflict-banner]').exists()).toBe(false)
      // 轮询发现新版本：仅提示，不覆盖草稿
      ctx.state.view = makeView(7, { ...ENABLED, targets: ['5.5.5.5'] }, INSTALLED)
      await vi.advanceTimersByTimeAsync(5000)
      expect((w.find('[data-testid=bp-targets-input]').element as HTMLTextAreaElement).value).toBe(
        '9.9.9.9',
      )
      expect(w.find('[data-testid=bp-conflict-banner]').text()).toContain('版本 7')
      w.unmount()
      const g1 = gets()
      await vi.advanceTimersByTimeAsync(20000)
      expect(gets()).toBe(g1)
    })

    it('操作进行中不轮询；轮询失败不弹错', async () => {
      const ctx = setup(makeView(5, ENABLED))
      const w = await mountPanel(ctx)
      ctx.state.handler = () => err(500, 'store_unavailable', 'x')
      await vi.advanceTimersByTimeAsync(5000)
      expect(w.find('[data-testid=bp-load-error]').exists()).toBe(false)
      w.unmount()
    })
  })
})
