// HUD 壳故障路径（独立编写）：告警态渲染、告警开关失败路径、连接徽章、token 不泄露。
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/app/App.vue'
import { backendRuntimeKey, createBackendRuntime, type BackendRuntime } from '@/app/backend-runtime'
import { createTestRouter } from '@/app/router'
import { useBackendStore } from '@/stores/backend'
import { FAKE_TOKEN, FakeSock, alertEnv, flush, helloEnv, resetSeqCounter } from './support'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })

const HEALTH = { status: 'ok', version: '9.9.9', pid: 4242, uptime_s: 12.4, alert: false }

type Req = { url: string; method: string; auth: string | null; body: string }

/** 假 fetch：记录请求；/health 固定 200；POST 的响应由 alertReply 决定。 */
function fakeFetch(alertReply: () => Promise<Response> | Response) {
  const calls: Req[] = []
  const fn = vi.fn(async (input: Request | string | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(String(input), init)
    const body = await req.text()
    calls.push({
      url: req.url,
      method: req.method,
      auth: req.headers.get('authorization'),
      body,
    })
    if (req.url.endsWith('/health')) return json(HEALTH)
    return alertReply()
  })
  return { fn: fn as unknown as typeof fetch, calls }
}

async function boot(
  opts: { alertReply?: () => Promise<Response> | Response; start?: boolean } = {},
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const sockets: FakeSock[] = []
  const f = fakeFetch(
    opts.alertReply ?? (() => json({ active: true, reason: null, changed_at: 'T' })),
  )
  const runtime: BackendRuntime = createBackendRuntime({
    fetch: f.fn,
    events: {
      getConnection: async () => ({ port: 5555, token: FAKE_TOKEN }),
      createSocket: (u) => {
        const s = new FakeSock(u)
        sockets.push(s)
        return s
      },
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
  if (opts.start !== false) runtime.start()
  await flushPromises()
  return { wrapper, runtime, sockets, calls: f.calls, store: useBackendStore() }
}

const rootDenied = (w: VueWrapper) =>
  (w.get('[data-testid=hud-root]').element as HTMLElement).style.getPropertyValue('--denied')

async function online(sockets: FakeSock[]) {
  await flush()
  const s = sockets[sockets.length - 1]!
  s.open()
  s.env(helloEnv(1))
  await flushPromises()
  return s
}

async function clickSwitch(wrapper: VueWrapper) {
  await wrapper.get('[role="switch"]').trigger('click')
  await flushPromises()
}

describe('HUD 壳：告警态渲染（独立）', () => {
  beforeEach(() => resetSeqCounter())
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('告警事件使根节点 --denied 由 0 变 1 并显示 WARNING 框；解除后恢复', async () => {
    const { wrapper, sockets, store } = await boot()
    const s = await online(sockets)
    expect(rootDenied(wrapper)).toBe('0')
    expect(wrapper.find('[data-testid=warning-box]').exists()).toBe(false)

    s.env(alertEnv(2, true, 'disk full'))
    await flushPromises()
    expect(store.denied).toBe(1)
    expect(rootDenied(wrapper)).toBe('1')
    expect(wrapper.find('[data-testid=warning-box]').exists()).toBe(true)
    expect(wrapper.find('[data-testid=warning-box]').text()).toContain('WARNING')

    s.env(alertEnv(3, false))
    await flushPromises()
    expect(rootDenied(wrapper)).toBe('0')
    expect(wrapper.find('[data-testid=warning-box]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('告警 reason 含 HTML 时以文本显示，不生成任何 img/脚本元素', async () => {
    const { wrapper, sockets } = await boot()
    const s = await online(sockets)
    const payload = '<img src=x onerror=alert(1)>'
    s.env(alertEnv(2, true, payload))
    await flushPromises()
    const box = wrapper.get('[data-testid=warning-box]').element as HTMLElement
    expect(box.querySelector('img')).toBeNull()
    expect(box.querySelector('script')).toBeNull()
    expect(box.querySelectorAll('[onerror]')).toHaveLength(0)
    // 大写化后的原文以文本形式存在
    expect(box.textContent).toContain('<IMG SRC=X ONERROR=ALERT(1)>')
    wrapper.unmount()
  })

  it('告警 reason 为 null 时显示占位文字而不是 "null"', async () => {
    const { wrapper, sockets } = await boot()
    const s = await online(sockets)
    s.env(alertEnv(2, true, null))
    await flushPromises()
    const text = wrapper.get('[data-testid=warning-box]').text()
    expect(text).toContain('NO REASON GIVEN')
    expect(text).not.toContain('NULL')
    wrapper.unmount()
  })

  it('hello 之前收到的告警事件不会把 UI 标记为 online，但告警态仍然生效', async () => {
    const { wrapper, sockets, store } = await boot()
    await flush()
    const s = sockets[0]!
    s.open()
    s.env(alertEnv(1, true, 'early'))
    await flushPromises()
    expect(store.connection).toBe('connecting')
    expect(store.denied).toBe(1)
    expect(rootDenied(wrapper)).toBe('1')
    wrapper.unmount()
  })
})

describe('HUD 壳：告警开关失败路径（独立）', () => {
  beforeEach(() => resetSeqCounter())
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('请求带 Bearer，JSON 体为 {active:true, reason}', async () => {
    const { wrapper, sockets, calls } = await boot()
    await online(sockets)
    await clickSwitch(wrapper)
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.url).toBe('http://127.0.0.1:5555/api/system/alert')
    expect(post.auth).toBe(`Bearer ${FAKE_TOKEN}`)
    expect(JSON.parse(post.body)).toEqual({ active: true, reason: 'S0 DEMO ALERT' })
    expect(post.url).not.toContain(FAKE_TOKEN)
    wrapper.unmount()
  })

  it('成功响应本身不在前端切换告警态：只有随后的 system.alert 事件才生效', async () => {
    const { wrapper, sockets, store } = await boot({
      alertReply: () => json({ active: true, reason: 'S0 DEMO ALERT', changed_at: 'T' }),
    })
    const s = await online(sockets)
    await clickSwitch(wrapper)
    expect(store.denied).toBe(0)
    expect(rootDenied(wrapper)).toBe('0')
    s.env(alertEnv(2, true, 'S0 DEMO ALERT'))
    await flushPromises()
    expect(rootDenied(wrapper)).toBe('1')
    wrapper.unmount()
  })

  it('401 响应：显示错误，告警态不切换', async () => {
    const { wrapper, sockets, store } = await boot({ alertReply: () => json({ detail: 'x' }, 401) })
    await online(sockets)
    await clickSwitch(wrapper)
    expect(wrapper.get('[data-testid=alert-error]').text()).toContain('401')
    expect(store.denied).toBe(0)
    expect(rootDenied(wrapper)).toBe('0')
    expect(wrapper.find('[data-testid=warning-box]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('500 响应：显示错误，告警态不切换', async () => {
    const { wrapper, sockets, store } = await boot({ alertReply: () => json({}, 500) })
    await online(sockets)
    await clickSwitch(wrapper)
    expect(wrapper.get('[data-testid=alert-error]').text()).toContain('500')
    expect(store.denied).toBe(0)
    expect(rootDenied(wrapper)).toBe('0')
    wrapper.unmount()
  })

  it('网络异常（fetch 抛错）：显示网络错误，告警态不切换', async () => {
    const { wrapper, sockets, store } = await boot({
      alertReply: () => {
        throw new TypeError('fetch failed')
      },
    })
    await online(sockets)
    await clickSwitch(wrapper)
    expect(wrapper.get('[data-testid=alert-error]').text()).toContain('网络')
    expect(store.denied).toBe(0)
    expect(rootDenied(wrapper)).toBe('0')
    wrapper.unmount()
  })

  it('后端未连接时点击开关：不发请求，显示 后端未连接', async () => {
    const { wrapper, calls } = await boot({ start: false })
    await clickSwitch(wrapper)
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    expect(wrapper.get('[data-testid=alert-error]').text()).toContain('后端未连接')
    wrapper.unmount()
  })
})

describe('HUD 壳：连接徽章与 token 不泄露（独立）', () => {
  beforeEach(() => resetSeqCounter())
  afterEach(() => {
    document.body.innerHTML = ''
    localStorage.clear()
    sessionStorage.clear()
  })

  it('徽章随状态切换 data-state；online 时显示 PID', async () => {
    const { wrapper, sockets } = await boot()
    await flush()
    const badge = () =>
      wrapper.get('[data-testid=connection] [data-state]').attributes('data-state')
    expect(badge()).toBe('connecting')
    const s = sockets[0]!
    s.open()
    s.env(helloEnv(1, 4242))
    await flushPromises()
    expect(badge()).toBe('online')
    expect(wrapper.get('[data-testid=connection-detail]').text()).toContain('PID 4242')
    s.drop(1006)
    await flushPromises()
    expect(badge()).toBe('reconnecting')
    expect(wrapper.find('[data-testid=connection-detail]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('token 不出现在 DOM、localStorage、sessionStorage、任何 WS/HTTP URL 中', async () => {
    const { wrapper, sockets, calls } = await boot()
    const s = await online(sockets)
    await clickSwitch(wrapper)
    s.env(alertEnv(2, true, 'x'))
    await flushPromises()

    const html = document.body.innerHTML + wrapper.html()
    expect(html).not.toContain(FAKE_TOKEN)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    for (const sock of sockets) expect(sock.url).not.toContain(FAKE_TOKEN)
    for (const c of calls) expect(c.url).not.toContain(FAKE_TOKEN)
    // token 只应出现在 auth 帧与 Authorization 头中
    expect(s.authFrames()[0]).toEqual({ type: 'auth', token: FAKE_TOKEN })
    wrapper.unmount()
  })

  it('断线后重连：新 socket 的 auth 帧使用重新取得的 token', async () => {
    const { wrapper, sockets } = await boot()
    const s1 = await online(sockets)
    // 之后的重连定时器使用假定时器（在断线前安装）
    vi.useFakeTimers()
    try {
      s1.drop(1006)
      await vi.advanceTimersByTimeAsync(499)
      expect(sockets).toHaveLength(1)
      await vi.advanceTimersByTimeAsync(1)
      expect(sockets).toHaveLength(2)
      const s2 = sockets[1]!
      s2.open()
      expect(s2.authFrames()).toEqual([{ type: 'auth', token: FAKE_TOKEN }])
    } finally {
      vi.useRealTimers()
    }
    wrapper.unmount()
  })
})
