import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/app/App.vue'
import { backendRuntimeKey, createBackendRuntime } from '@/app/backend-runtime'
import { createTestRouter } from '@/app/router'
import { useBackendStore } from '@/stores/backend'
import { FakeSocket, alertEvent, hello, resetSeq, env } from './helpers'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })

async function boot(fetchImpl?: typeof fetch) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const fetchMock =
    fetchImpl ??
    (vi.fn(async (req: Request) =>
      req.url.endsWith('/health')
        ? json({ status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 12.4, alert: false })
        : json({ active: true, reason: 'S0 DEMO ALERT', changed_at: 't' }),
    ) as unknown as typeof fetch)
  const runtime = createBackendRuntime({
    fetch: fetchMock,
    events: {
      getConnection: async () => ({ port: 5555, token: 'fake-token' }),
      createSocket: (u) => new FakeSocket(u),
    },
  })
  const router = createTestRouter()
  router.push('/')
  await router.isReady()
  const wrapper = mount(App, {
    global: {
      plugins: [
        pinia,
        router,
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
      provide: { [backendRuntimeKey as symbol]: runtime },
    },
  })
  runtime.start()
  await flushPromises()
  const sock = FakeSocket.last()
  sock.open()
  return {
    wrapper,
    runtime,
    sock,
    fetchMock: fetchMock as ReturnType<typeof vi.fn>,
    store: useBackendStore(),
  }
}

const denied = (w: VueWrapper) =>
  (w.get('[data-testid=hud-root]').element as HTMLElement).style.getPropertyValue('--denied')

describe('HUD 壳', () => {
  beforeEach(() => {
    FakeSocket.reset()
    resetSeq()
  })
  afterEach(() => vi.useRealTimers())

  it('告警事件把根节点 --denied 由 0 变 1 并显示 WARNING 框，解除后恢复', async () => {
    const { wrapper, sock, runtime } = await boot()
    sock.emit(hello())
    await flushPromises()
    expect(denied(wrapper)).toBe('0')
    expect(wrapper.find('[data-testid=warning-box]').exists()).toBe(false)

    sock.emit(alertEvent(true, 'disk full'))
    await flushPromises()
    expect(denied(wrapper)).toBe('1')
    const box = wrapper.get('[data-testid=warning-box]')
    expect(box.text()).toContain('WARNING')
    expect(box.text()).toContain('DISK FULL')

    sock.emit(alertEvent(false))
    await flushPromises()
    expect(denied(wrapper)).toBe('0')
    expect(wrapper.find('[data-testid=warning-box]').exists()).toBe(false)
    runtime.stop()
    wrapper.unmount()
  })

  it('hello 携带的告警态用于对齐；seq 倒退的旧事件被忽略', async () => {
    const { wrapper, sock, runtime } = await boot()
    sock.emit(hello(1, { active: true, reason: 'r', changed_at: 't' }))
    await flushPromises()
    expect(denied(wrapper)).toBe('1')
    const stale = alertEvent(false)
    sock.emit({ ...stale, seq: 0 })
    await flushPromises()
    expect(denied(wrapper)).toBe('1')
    runtime.stop()
    wrapper.unmount()
  })

  it('告警开关只发请求，不本地切换；仅事件改变告警态', async () => {
    const { wrapper, sock, fetchMock, runtime } = await boot()
    sock.emit(hello())
    await flushPromises()
    const sw = wrapper.get('[role=switch]')
    expect(sw.attributes('aria-checked')).toBe('false')
    await sw.trigger('click')
    await flushPromises()
    const post = fetchMock.mock.calls.map((c) => c[0] as Request).find((r) => r.method === 'POST')!
    expect(post.url).toBe('http://127.0.0.1:5555/api/system/alert')
    expect(post.headers.get('authorization')).toBe('Bearer fake-token')
    expect(post.url).not.toContain('fake-token')
    // 响应已回来，但没有 system.alert 事件 -> 仍是常态
    expect(denied(wrapper)).toBe('0')
    expect(wrapper.find('[data-testid=warning-box]').exists()).toBe(false)
    expect(wrapper.get('[role=switch]').attributes('aria-checked')).toBe('false')

    sock.emit(alertEvent(true, 'S0 DEMO ALERT'))
    await flushPromises()
    expect(denied(wrapper)).toBe('1')
    expect(wrapper.get('[role=switch]').attributes('aria-checked')).toBe('true')
    runtime.stop()
    wrapper.unmount()
  })

  it('开关请求失败时显示错误且不改变告警态', async () => {
    const failing = vi.fn(async (req: Request) =>
      req.method === 'POST'
        ? new Response('nope', { status: 401 })
        : json({ status: 'ok', version: 'v', pid: 1, uptime_s: 1, alert: false }),
    ) as unknown as typeof fetch
    const { wrapper, sock, runtime } = await boot(failing)
    sock.emit(hello())
    await flushPromises()
    await wrapper.get('[role=switch]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid=alert-error]').text()).toContain('401')
    expect(denied(wrapper)).toBe('0')
    runtime.stop()
    wrapper.unmount()
  })

  it('连接状态与 pid / 心跳延迟显示', async () => {
    const { wrapper, sock, store, runtime } = await boot()
    expect(wrapper.get('[data-testid=connection]').text()).toContain('CONNECTING')
    sock.emit(hello(777))
    await flushPromises()
    expect(wrapper.get('[data-testid=connection]').text()).toContain('ONLINE')
    expect(wrapper.get('[data-testid=connection-detail]').text()).toContain('PID 777')
    sock.emit(
      env('system.heartbeat', { uptime_s: 5 }, { ts: new Date(Date.now() - 30).toISOString() }),
    )
    await flushPromises()
    expect(store.latencyMs).toBeGreaterThanOrEqual(0)
    expect(wrapper.get('[data-testid=connection-detail]').text()).toMatch(/MS/)
    sock.drop()
    await flushPromises()
    expect(wrapper.get('[data-testid=connection]').text()).toContain('RECONNECTING')
    runtime.stop()
    wrapper.unmount()
  })

  it('/health 查询在 online 后显示版本', async () => {
    const { wrapper, sock, runtime } = await boot()
    sock.emit(hello())
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.get('[data-testid=health-version]').text()).toBe('9.9.9'))
    runtime.stop()
    wrapper.unmount()
  })

  it('左栏：只有总览可用，其余禁用并标切片号', async () => {
    const { wrapper, runtime } = await boot()
    const disabled = wrapper.findAll('[aria-disabled=true]')
    expect(disabled.map((d) => d.attributes('data-slice'))).toEqual([
      'S2',
      'S3',
      'S5',
      'S6',
      'S8',
      'S7',
      'S1',
    ])
    expect(wrapper.get('nav a').text()).toContain('总览')
    expect(wrapper.find('nav a[aria-disabled]').exists()).toBe(false)
    runtime.stop()
    wrapper.unmount()
  })

  it('∞ 占位标 PLACEHOLDER，页脚注明来源与字体许可', async () => {
    const { wrapper, runtime } = await boot()
    expect(wrapper.get('[data-testid=infinity-placeholder]').text()).toContain('PLACEHOLDER')
    expect(wrapper.get('[data-testid=about]').text()).toMatch(/AGPL-3\.0/)
    expect(wrapper.get('[data-testid=about]').text()).toMatch(/OFL/)
    runtime.stop()
    wrapper.unmount()
  })
})
