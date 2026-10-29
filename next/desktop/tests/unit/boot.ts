import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { vi } from 'vitest'
import App from '@/app/App.vue'
import { backendRuntimeKey, createBackendRuntime } from '@/app/backend-runtime'
import { createTestRouter } from '@/app/router'
import { useBackendStore } from '@/stores/backend'
import { FakeSocket } from './helpers'

/**
 * 旧用例里一个“任务”对应新结构里“一个发布配置（带一个分支）+ 一条运行命令”：配置 id 与命令 id 都沿用任务 id。
 * 用它把 `/api/tasks` 的假数据转成 `/api/release-configs` 的响应，旧用例的夹具不用重写。
 */
export function releaseFromTask(t: Record<string, unknown>) {
  const raw = (t.targets as Array<Record<string, unknown>>) ?? []
  // 命令至少要选一个目标；旧夹具没写目标时补一个，保证命令能被选中运行
  const targets = (raw.length ? raw : [{ name: '目标1', enabled: true }]).map((x, i) => ({
    ...x,
    id: `${t.id}-target-${i}`,
  }))
  const flow = {
    build_branch: 'main',
    ...((t.git_flow as Record<string, unknown> | null | undefined) ?? {}),
  }
  const branchId = `${t.id}-branch-0`
  return {
    id: t.id,
    name: t.name,
    sort_order: t.sort_order ?? 0,
    project_id: t.project_id ?? null,
    repo_id: t.repo_id ?? null,
    repo_name: t.repo_name ?? null,
    local_repo_path: t.local_repo_path ?? '',
    // v8：配置里只有分支目录；旧任务的 git_flow 变成一个分支，命令用它
    branches: [{ update_branches: [], merges: [], push_branches: [], ...flow, id: branchId }],
    agent_queue_id: t.agent_queue_id ?? null,
    agent_queue_name: t.agent_queue_name ?? null,
    warnings: t.warnings ?? [],
    targets,
    commands: [
      {
        id: t.id,
        name: t.tg_desc || t.name,
        enabled: t.enabled ?? true,
        sort_order: t.sort_order ?? 0,
        tg_command: t.tg_command ?? '',
        tg_desc: t.tg_desc ?? '',
        branch_id: branchId,
        target_ids: targets.map((x) => x.id),
        last_run: t.last_run ?? null,
        active_run_id: t.active_run_id ?? null,
      },
    ],
  }
}

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
  const userFetch = opts.fetchImpl
  const fetchMock = userFetch
    ? (vi.fn(async (req: Request) => {
        const url = new URL(req.url)
        if (
          (url.pathname === '/api/tasks' || url.pathname === '/api/release-configs') &&
          req.method === 'GET' &&
          !opts.path
        ) {
          return json({ items: [], revision: 1 })
        }
        // 发布配置列表：由同一份 `/api/tasks` 假数据派生（一个任务 = 一个配置 + 一条命令）
        if (url.pathname === '/api/release-configs' && req.method === 'GET') {
          // 用例自己提供了发布配置接口就直接用；没提供（返回里没有 items 数组）才从任务假数据派生
          const own = await userFetch(req.clone())
          const ownBody = (await own
            .clone()
            .json()
            .catch(() => null)) as { items?: unknown } | null
          if (own.ok && Array.isArray(ownBody?.items)) return own
          const res = await userFetch(
            new Request(new URL('/api/tasks', req.url), { method: 'GET' }),
          )
          if (!res.ok) return res
          const body = (await res.json()) as {
            items?: Array<Record<string, unknown>>
            revision?: number
          }
          return json({
            items: (body.items ?? []).map(releaseFromTask),
            revision: body.revision ?? 0,
          })
        }
        return userFetch(req)
      }) as unknown as typeof fetch)
    : (vi.fn(async (req: Request) =>
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

/** 点工具条上的运行 / 只发布 / 回滚，然后在选择器里选中这条命令（命令 id 即旧任务 id）。 */
export async function pickCommand(
  b: { wrapper: { get: (s: string) => { trigger: (e: string) => Promise<unknown> } } },
  commandId: string,
  button: 'run-task-btn' | 'deploy-only-btn' | 'rollback-btn' = 'run-task-btn',
) {
  await b.wrapper.get(`[data-testid="${button}"]`).trigger('click')
  await flushPromises()
  const item = document.querySelector(`[data-testid="command-pick-${commandId}"]`) as HTMLElement
  if (!item) throw new Error(`选择器里没有命令 ${commandId}`)
  item.click()
  await flushPromises()
}
