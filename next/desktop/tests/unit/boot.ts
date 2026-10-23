import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { vi } from 'vitest'
import App from '@/app/App.vue'
import { backendRuntimeKey, createBackendRuntime } from '@/app/backend-runtime'
import { createTestRouter } from '@/app/router'
import { useBackendStore } from '@/stores/backend'
import { FakeSocket } from './helpers'

export const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })

interface BootOpts {
  fetchImpl?: typeof fetch
  path?: string
}

/** 挂载整个 App（假 fetch、假 WebSocket），默认路由 `/`（重定向到 /tasks）。 */
export async function boot(opts: BootOpts = {}) {
  const m = await mountApp(opts)
  m.runtime.start()
  await flushPromises()
  const sock = FakeSocket.last()
  sock.open()
  await flushPromises()
  return { ...m, sock }
}

/** 挂载 App 但不调用 `runtime.start()`：尚未取得连接信息（`runtime.api()` 为 null）。 */
export async function bootUnconnected(opts: BootOpts = {}) {
  return mountApp(opts)
}

async function mountApp(opts: BootOpts) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const fetchMock =
    opts.fetchImpl ??
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
  router.push(opts.path ?? '/')
  await router.isReady()
  const wrapper = mount(App, {
    attachTo: document.body,
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
  return {
    wrapper,
    runtime,
    router,
    fetchMock: fetchMock as ReturnType<typeof vi.fn>,
    store: useBackendStore(),
    async done() {
      runtime.stop()
      wrapper.unmount()
    },
  }
}

/** 打开侧栏底部的连接状态弹出层（告警演示开关、pid、心跳延迟都在里面）。 */
export async function openConnection(b: {
  wrapper: { get: (s: string) => { trigger: (e: string) => Promise<unknown> } }
}) {
  if (document.querySelector('[data-testid=connection-popover]')) return
  await b.wrapper.get('[data-testid=connection-trigger]').trigger('click')
  await flushPromises()
}
