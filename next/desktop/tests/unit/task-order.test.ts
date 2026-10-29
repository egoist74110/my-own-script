// 任务页：发布配置列表与配置下命令的排序（拖拽、键盘、菜单、过滤禁用、乐观更新、失败回滚、冲突重拉、串行提交）
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { boot, json } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

type ReleaseView = components['schemas']['ReleaseView']

function makeCfg(id: string, withCommands: boolean): ReleaseView {
  return {
    id,
    name: `配置 ${id}`,
    sort_order: 0,
    project_id: 'p',
    repo_id: 'r',
    repo_name: `repo-${id}`,
    local_repo_path: `/repos/${id}`,
    branches: [
      { id: `${id}-b`, build_branch: 'main', update_branches: [], merges: [], push_branches: [] },
    ],
    warnings: [],
    targets: [{ id: `${id}-t`, name: '目标', enabled: true }],
    commands: withCommands
      ? ['m1', 'm2', 'm3'].map((m, i) => ({
          id: m,
          name: `命令 ${m}`,
          enabled: true,
          sort_order: i,
          branch_id: `${id}-b`,
          tg_command: '',
          tg_desc: '',
          target_ids: [`${id}-t`],
          active_run_id: null,
          last_run: null,
        }))
      : [],
  }
}

interface Put {
  path: string
  body: { ids: string[]; revision: number }
}

/** 带状态的假后端：配置/命令顺序随 PUT 变化，revision 随成功写入递增。 */
function makeServer(
  opts: {
    /** 第 n 次（从 0 起）order 写入的钩子：返回 Response 覆盖，或返回 Promise 先挂起。 */
    onPut?: (n: number, put: Put) => Response | Promise<Response | null> | null
  } = {},
) {
  let revision = 10
  let cfgOrder = ['c1', 'c2', 'c3']
  let cmdOrder = ['m1', 'm2', 'm3']
  const puts: Put[] = []
  const gets = { list: 0 }
  const view = (): ReleaseView[] =>
    cfgOrder.map((id) => {
      const c = makeCfg(id, id === 'c1')
      if (id === 'c1') c.commands = cmdOrder.map((m) => c.commands.find((x) => x.id === m)!)
      return c
    })
  const fetchImpl = (async (req: Request) => {
    const url = new URL(req.url)
    const p = url.pathname
    if (p === '/health')
      return json({ status: 'ok', version: '1', pid: 1, uptime_s: 1, alert: false })
    if (p === '/api/tasks') return json({ items: [], revision })
    if (p === '/api/runs') return json({ items: [], cursor: null })
    if (p === '/api/release-configs' && req.method === 'GET') {
      gets.list++
      return json({ items: view(), revision })
    }
    const mCfg = p.match(/^\/api\/release-configs\/(c\d)$/)
    if (mCfg && req.method === 'GET')
      return json({ item: view().find((c) => c.id === mCfg[1]), revision })
    if (req.method === 'PUT' && /\/order$/.test(p)) {
      const put: Put = { path: p, body: JSON.parse(await req.clone().text()) }
      const n = puts.length
      puts.push(put)
      const custom = await opts.onPut?.(n, put)
      if (custom) return custom
      revision += 1
      if (p === '/api/release-configs/order') cfgOrder = put.body.ids
      else cmdOrder = put.body.ids
      return json({ revision })
    }
    return json({})
  }) as unknown as typeof fetch
  return { fetchImpl, puts, gets, setRevision: (n: number) => (revision = n) }
}

const err = (status: number, code: string) =>
  new Response(JSON.stringify({ detail: { code, message: 'x' } }), {
    status,
    headers: { 'content-type': 'application/json' },
  })

async function settle() {
  for (let i = 0; i < 5; i++) await flushPromises()
}
async function bootTasks(server: ReturnType<typeof makeServer>) {
  const b = await boot({ path: '/tasks', fetchImpl: server.fetchImpl })
  b.sock.emit(hello())
  await settle()
  return b
}
const q = <T extends Element>(sel: string) => document.querySelector(sel) as T | null
const qa = <T extends Element>(sel: string) => Array.from(document.querySelectorAll(sel)) as T[]
const rowIds = () => qa<HTMLElement>('[data-row-id]').map((e) => e.dataset.rowId)
const cmdIds = () =>
  qa('[data-testid^="command-row-"]').map((e) =>
    e.getAttribute('data-testid')!.replace('command-row-', ''),
  )
async function click(sel: string) {
  const el = q<HTMLElement>(sel)
  if (!el) throw new Error(`找不到 ${sel}`)
  el.click()
  await settle()
}
async function keyAlt(sel: string, key: 'ArrowUp' | 'ArrowDown') {
  q(sel)!.dispatchEvent(new KeyboardEvent('keydown', { key, altKey: true, bubbles: true }))
  await settle()
}
/** 假装每行高 60px，从上到下排列。 */
function stubRects() {
  qa<HTMLElement>('[data-row-id]').forEach((el, i) => {
    el.getBoundingClientRect = () =>
      ({
        top: i * 60,
        height: 60,
        bottom: i * 60 + 60,
        left: 0,
        right: 200,
        width: 200,
        x: 0,
        y: i * 60,
      }) as DOMRect
  })
}
async function drag(id: string, toY: number) {
  stubRects()
  q(`[data-testid="row-handle-${id}"]`)!.dispatchEvent(
    new MouseEvent('pointerdown', { bubbles: true, clientY: 10, button: 0 }),
  )
  await settle()
  document.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientY: toY }))
  await settle()
  const indicator = q('[data-drop]')?.getAttribute('data-drop') ?? null
  document.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, clientY: toY }))
  await settle()
  return indicator
}

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  document.body.innerHTML = ''
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('发布配置列表排序', () => {
  it('拖拽手柄重排：拖动时显示插入线；松开后立刻换位，PUT 带全部 id 的新顺序和当前 revision；整行点击仍是选中', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    expect(rowIds()).toEqual(['c1', 'c2', 'c3'])
    // 点整行是选中，不会触发排序
    await click('[data-testid="task-row-c2"]')
    expect(server.puts).toHaveLength(0)

    // 把 c1 拖到 c2 与 c3 之间（y=140 小于第 3 行中线 150）
    const indicator = await drag('c1', 140)
    expect(indicator).toBe('before')
    expect(rowIds()).toEqual(['c2', 'c1', 'c3'])
    expect(server.puts).toHaveLength(1)
    expect(server.puts[0]).toMatchObject({
      path: '/api/release-configs/order',
      body: { ids: ['c2', 'c1', 'c3'], revision: 10 },
    })
    // 拖到最底下
    await drag('c2', 500)
    expect(rowIds()).toEqual(['c1', 'c3', 'c2'])
    expect(server.puts[1]!.body).toMatchObject({ ids: ['c1', 'c3', 'c2'], revision: 11 })
    // 原地放下不发请求
    await drag('c1', 10)
    expect(server.puts).toHaveLength(2)
    await b.done()
  })

  it('键盘：⌥↓ / ⌥↑ 上移下移，到头不动', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    expect(rowIds()).toEqual(['c2', 'c1', 'c3'])
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowUp')
    expect(rowIds()).toEqual(['c1', 'c2', 'c3'])
    const n = server.puts.length
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowUp') // 已在最上面
    expect(server.puts).toHaveLength(n)
    expect(server.puts.map((p) => p.body.ids)).toEqual([
      ['c2', 'c1', 'c3'],
      ['c1', 'c2', 'c3'],
    ])
    await b.done()
  })

  it('行菜单：上移 / 下移 / 移到顶部 / 移到底部；到头的项禁用', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    expect(q<HTMLButtonElement>('[data-testid="row-move-up-c1"]')!.disabled).toBe(true)
    expect(q<HTMLButtonElement>('[data-testid="row-move-top-c1"]')!.disabled).toBe(true)
    expect(q<HTMLButtonElement>('[data-testid="row-move-down-c3"]')!.disabled).toBe(true)
    await click('[data-testid="row-move-top-c3"]')
    expect(rowIds()).toEqual(['c3', 'c1', 'c2'])
    await click('[data-testid="row-move-bottom-c3"]')
    expect(rowIds()).toEqual(['c1', 'c2', 'c3'])
    await click('[data-testid="row-move-down-c1"]')
    expect(rowIds()).toEqual(['c2', 'c1', 'c3'])
    await click('[data-testid="row-move-up-c3"]')
    expect(rowIds()).toEqual(['c2', 'c3', 'c1'])
    expect(server.puts.map((p) => p.body.ids)).toEqual([
      ['c3', 'c1', 'c2'],
      ['c1', 'c2', 'c3'],
      ['c2', 'c1', 'c3'],
      ['c2', 'c3', 'c1'],
    ])
    await b.done()
  })

  it('有搜索或分段不是“全部”时禁用排序：手柄不显示，菜单项禁用并提示，键盘无效', async () => {
    const server = makeServer()
    const b = await bootTasks(server)
    expect(q('[data-testid="row-handle-c1"]')).not.toBeNull()
    const input = q<HTMLInputElement>('input[type="search"]')!
    input.value = '配置'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await settle()
    expect(q('[data-testid="row-handle-c1"]')).toBeNull()
    expect(q<HTMLButtonElement>('[data-testid="row-move-down-c1"]')!.disabled).toBe(true)
    expect(q('[data-testid="row-sort-hint-c1"]')!.textContent).toContain(
      '清空搜索并切到全部后才能排序',
    )
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    expect(server.puts).toHaveLength(0)
    // 分段控件切到“运行中”同样禁用
    input.value = ''
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await settle()
    expect(q('[data-testid="row-handle-c1"]')).not.toBeNull()
    const tab = qa<HTMLElement>('[role="tab"]').find((t) => t.textContent?.includes('运行中'))!
    tab.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, ctrlKey: false }))
    await settle()
    expect(q('[data-testid="row-handle-c1"]')).toBeNull()
    await b.done()
  })

  it('失败回滚：先乐观换位，接口失败后恢复原顺序并显示错误提示条', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const server = makeServer({
      onPut: async () => {
        await gate
        return err(500, 'internal')
      },
    })
    const b = await bootTasks(server)
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    expect(rowIds()).toEqual(['c2', 'c1', 'c3']) // 乐观
    release()
    await settle()
    expect(rowIds()).toEqual(['c1', 'c2', 'c3']) // 回滚
    expect(q('[data-testid="config-op-error"]')).not.toBeNull()
    await b.done()
  })

  it('revision 冲突：回滚并重新拉取列表，提示用户重试；重试用新 revision 成功', async () => {
    const server = makeServer({
      onPut: (n) => (n === 0 ? err(409, 'revision_conflict') : null),
    })
    const b = await bootTasks(server)
    const before = server.gets.list
    server.setRevision(20) // 别处已改过
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    expect(rowIds()).toEqual(['c1', 'c2', 'c3'])
    expect(server.gets.list).toBeGreaterThan(before)
    expect(q('[data-testid="config-op-error"]')!.textContent).toContain('重新读取')
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    expect(rowIds()).toEqual(['c2', 'c1', 'c3'])
    expect(server.puts).toHaveLength(2)
    expect(server.puts[0]!.body.revision).toBe(10)
    expect(server.puts[1]!.body.revision).toBe(20)
    await b.done()
  })

  it('连续快速移动串行提交：前一条完成前不发下一条，后一条用前一条返回的新 revision', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const server = makeServer({
      onPut: async (n) => {
        if (n === 0) await gate
        return null
      },
    })
    const b = await bootTasks(server)
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    // 界面立刻是两次移动后的顺序，但只发出了一条请求
    expect(rowIds()).toEqual(['c2', 'c3', 'c1'])
    expect(server.puts).toHaveLength(1)
    release()
    await settle()
    expect(server.puts).toHaveLength(2)
    expect(server.puts[0]!.body).toMatchObject({ ids: ['c2', 'c1', 'c3'], revision: 10 })
    expect(server.puts[1]!.body).toMatchObject({ ids: ['c2', 'c3', 'c1'], revision: 11 })
    expect(rowIds()).toEqual(['c2', 'c3', 'c1'])
    await b.done()
  })

  it('串行中前一条失败：丢弃后面排队的，回滚到服务端顺序，不发出基于过期顺序的请求', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const server = makeServer({
      onPut: async (n) => {
        if (n === 0) {
          await gate
          return err(500, 'internal')
        }
        return null
      },
    })
    const b = await bootTasks(server)
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    await keyAlt('[data-testid="task-row-c1"]', 'ArrowDown')
    release()
    await settle()
    expect(server.puts).toHaveLength(1)
    expect(rowIds()).toEqual(['c1', 'c2', 'c3'])
    expect(q('[data-testid="config-op-error"]')).not.toBeNull()
    await b.done()
  })
})

describe('命令排序（配置详情里的运行命令）', () => {
  it('上移/下移：乐观换位，PUT 带全部命令 id；连续移动串行；到头禁用', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const server = makeServer({
      onPut: async (n) => {
        if (n === 0) await gate
        return null
      },
    })
    const b = await bootTasks(server)
    expect(cmdIds()).toEqual(['m1', 'm2', 'm3'])
    expect(q<HTMLButtonElement>('[data-testid="command-up-m1"]')!.disabled).toBe(true)
    await click('[data-testid="command-down-m1"]')
    await click('[data-testid="command-down-m1"]')
    expect(cmdIds()).toEqual(['m2', 'm3', 'm1'])
    expect(server.puts).toHaveLength(1)
    release()
    await settle()
    expect(server.puts.map((p) => p.path)).toEqual([
      '/api/release-configs/c1/commands/order',
      '/api/release-configs/c1/commands/order',
    ])
    expect(server.puts[0]!.body).toMatchObject({ ids: ['m2', 'm1', 'm3'], revision: 10 })
    expect(server.puts[1]!.body).toMatchObject({ ids: ['m2', 'm3', 'm1'], revision: 11 })
    expect(cmdIds()).toEqual(['m2', 'm3', 'm1'])
    await b.done()
  })

  it('失败回滚并提示；revision 冲突重拉后可重试', async () => {
    const server = makeServer({
      onPut: (n) =>
        n === 0 ? err(409, 'revision_conflict') : n === 1 ? err(500, 'internal') : null,
    })
    const b = await bootTasks(server)
    const before = server.gets.list
    await click('[data-testid="command-down-m1"]')
    expect(cmdIds()).toEqual(['m1', 'm2', 'm3'])
    expect(server.gets.list).toBeGreaterThan(before)
    expect(q('[data-testid="command-error"]')!.textContent).toContain('重新读取')
    await click('[data-testid="command-down-m1"]')
    expect(cmdIds()).toEqual(['m1', 'm2', 'm3'])
    expect(q('[data-testid="command-error"]')).not.toBeNull()
    await click('[data-testid="command-down-m1"]')
    expect(cmdIds()).toEqual(['m2', 'm1', 'm3'])
    await b.done()
  })
})
