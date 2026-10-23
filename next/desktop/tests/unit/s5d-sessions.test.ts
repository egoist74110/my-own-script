// S5-D：AI 会话页终端会话、WS 状态驱动、新会话 Sheet、操作与安全性单测
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boot } from './boot'
import { FakeSocket, env, hello, resetSeq } from './helpers'
import { err, json } from './settings-fake'
import { toApiError } from '@/features/ai/api'

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
    is_builtin: true,
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
    is_builtin: true,
    resolved: {
      ok: false,
      path: null,
      version: null,
      path_hint: '未在 PATH 找到 codex',
    },
  },
  {
    id: 'prof-agy',
    name: 'Antigravity CLI',
    cli: 'agy',
    command: 'agy',
    upgrade_command: 'pip install -U antigravity',
    is_builtin: true,
    resolved: {
      ok: true,
      path: '/usr/local/bin/agy',
      version: '2.0.0',
      path_hint: '/usr/local/bin/agy',
    },
  },
]

const FAKE_LOCAL_REPOS = [
  {
    id: 'repo-1',
    name: 'toolbox-repo',
    path: '/path/to/toolbox',
    head_branch: 'main',
  },
  {
    id: 'repo-2',
    name: 'another-repo',
    path: '/path/to/another',
    head_branch: 'develop',
  },
]

const FAKE_SESSIONS = [
  {
    id: 'sess-running-1',
    kind: 'terminal',
    cli: 'claude',
    profile_id: 'prof-claude',
    repo_id: 'repo-1',
    repo: {
      id: 'repo-1',
      name: 'toolbox-repo',
      path: '/path/to/toolbox',
    },
    state: 'busy',
    exit_code: null,
    ended_reason: null,
    warnings: [],
    created_at: '2026-10-23T12:00:00Z',
  },
  {
    id: 'sess-ended-2',
    kind: 'terminal',
    cli: 'codex',
    profile_id: 'prof-codex',
    repo_id: 'repo-1',
    repo: {
      id: 'repo-1',
      name: 'toolbox-repo',
      path: '/path/to/toolbox',
    },
    state: 'ended',
    exit_code: 0,
    ended_reason: 'process_exited',
    warnings: ['kill_failed'],
    created_at: '2026-10-23T11:00:00Z',
  },
]

interface FakeAiFetchOpts {
  sessions?: typeof FAKE_SESSIONS
  profiles?: typeof FAKE_PROFILES
  repos?: typeof FAKE_LOCAL_REPOS
  onGetSessions?: () => Response
  onCreateSession?: (body: unknown) => Response
  onInterrupt?: (sid: string) => Response
  onClose?: (sid: string) => Response
  onDelete?: (sid: string) => Response
}

function createAiFetch(opts: FakeAiFetchOpts = {}) {
  const sessions = opts.sessions !== undefined ? [...opts.sessions] : [...FAKE_SESSIONS]
  const profiles = opts.profiles ?? FAKE_PROFILES
  const repos = opts.repos ?? FAKE_LOCAL_REPOS

  const calls: { method: string; path: string; body: unknown }[] = []

  const handler = async (req: Request) => {
    const url = new URL(req.url)
    const method = req.method
    const pathname = url.pathname

    let body: unknown = null
    if (method === 'POST' || method === 'PATCH' || method === 'PUT') {
      try {
        body = await req.clone().json()
      } catch {
        // body not json
      }
    }
    calls.push({ method, path: pathname, body })

    if (pathname === '/health') {
      return json({ status: 'ok', version: '0.1.0', pid: 4242, uptime_s: 10, alert: false })
    }
    if (pathname === '/api/ai/sessions' && method === 'GET') {
      if (opts.onGetSessions) return opts.onGetSessions()
      return json({ items: sessions })
    }
    if (pathname === '/api/ai' && method === 'GET') {
      return json({
        profiles,
        settings: {
          default_permission_tier: 'prompt',
          work_item_analysis_tier: 'prompt',
          model_presets: {},
        },
        jobs: [],
        revision: 1,
      })
    }
    if (pathname === '/api/ado' && method === 'GET') {
      return json({
        local_repos: repos,
        libraries: [],
        projects: [],
        revision: 1,
        active_library_id: 'lib-1',
        active_project_id: 'proj-1',
      })
    }
    if (pathname === '/api/settings' && method === 'GET') {
      return json({
        app_version: '0.1.0',
        data_dir: '/tmp',
        legacy_config_dir: '/tmp',
        revision: 1,
        schema_version: 1,
        store_state: 'ok',
        local_repos: repos,
        import: { state: 'none' },
      })
    }
    if (pathname === '/api/ai/sessions' && method === 'POST') {
      if (opts.onCreateSession) return opts.onCreateSession(body)
      const newSess = {
        id: 'sess-new-created',
        kind: 'terminal',
        cli: 'claude',
        profile_id: 'prof-claude',
        repo_id: 'repo-1',
        repo: repos[0] ?? { id: 'repo-1', name: 'toolbox-repo', path: '/path/to/toolbox' },
        state: 'busy',
        exit_code: null,
        ended_reason: null,
        warnings: [],
        created_at: new Date().toISOString(),
      }
      sessions.unshift(newSess)
      return json(newSess, 201)
    }
    if (pathname.startsWith('/api/ai/sessions/') && pathname.endsWith('/interrupt')) {
      const sid = pathname.split('/')[4]!
      if (opts.onInterrupt) return opts.onInterrupt(sid)
      return json({ status: 'interrupted' })
    }
    if (pathname.startsWith('/api/ai/sessions/') && pathname.endsWith('/close')) {
      const sid = pathname.split('/')[4]!
      if (opts.onClose) return opts.onClose(sid)
      return json({ status: 'closed' })
    }
    if (pathname.startsWith('/api/ai/sessions/') && method === 'DELETE') {
      const sid = pathname.split('/')[4]!
      if (opts.onDelete) return opts.onDelete(sid)
      return json({ status: 'deleted' })
    }

    return json({ detail: 'not found' }, 404)
  }

  return { fetch: handler as unknown as typeof fetch, calls }
}

describe('S5-D 会话列表与 WS 事件驱动', () => {
  it('左栏列表展示真实会话，包含 CLI 缩写、仓库名、状态与退出码/告警', async () => {
    const fake = createAiFetch()
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 会话 1：运行中
    const row1 = b.wrapper.find('[data-testid="session-sess-running-1"]')
    expect(row1.exists()).toBe(true)
    expect(row1.text()).toContain('CL') // Claude 缩写
    expect(row1.text()).toContain('toolbox-repo')
    expect(row1.text()).toContain('运行中')

    // 会话 2：已结束，退出码 0，告警标记
    const row2 = b.wrapper.find('[data-testid="session-sess-ended-2"]')
    expect(row2.exists()).toBe(true)
    expect(row2.text()).toContain('CX') // Codex 缩写
    expect(row2.text()).toContain('已结束')
    expect(row2.text()).toContain('(0)') // 退出码
    expect(row2.find('.warning-badge').exists()).toBe(true) // 告警标志

    await b.done()
  })

  it('空态按设计稿呈现：没有会话提示与新建会话按钮', async () => {
    const fake = createAiFetch({ sessions: [] })
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const empty = b.wrapper.find('[data-testid="sessions-empty-state"]')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain('没有会话')
    expect(empty.text()).toContain('在本地仓库里启动 Claude、Codex 或 Antigravity')
    expect(b.wrapper.find('[data-testid="empty-new-session-btn"]').exists()).toBe(true)

    await b.done()
  })

  it('收到 ai.session WS 事件实时更新会话状态，无需刷新页面', async () => {
    const fake = createAiFetch()
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const row1Before = b.wrapper.get('[data-testid="session-sess-running-1"]')
    expect(row1Before.text()).toContain('运行中')

    // 后端通过 WS 推送 ai.session 事件，标记会话退出
    b.sock.emit(
      env(
        'ai.session',
        {
          session_id: 'sess-running-1',
          state: 'ended',
          ended_reason: 'process_exited',
          last_seq: 1,
        },
        { topic: 'ai' },
      ),
    )
    await flushPromises()

    const row1After = b.wrapper.get('[data-testid="session-sess-running-1"]')
    expect(row1After.text()).toContain('已结束')

    await b.done()
  })
})

describe('S5-D 新会话 Sheet 校验与幂等性', () => {
  it('打开新建 Sheet：不可运行的 profile 灰显并标注原因，仓库列表只列已配置仓库', async () => {
    const fake = createAiFetch()
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    await b.wrapper.get('[data-testid="new-session-btn"]').trigger('click')
    await flushPromises()

    const form = document.querySelector('[data-testid="new-session-form"]')
    expect(form).not.toBeNull()

    // profile select
    const profileSelect = document.querySelector(
      '[data-testid="profile-select"]',
    ) as HTMLSelectElement
    expect(profileSelect).not.toBeNull()
    const options = Array.from(profileSelect.querySelectorAll('option'))
    expect(options).toHaveLength(3)

    // Codex option resolved.ok = false -> disabled
    const codexOpt = options.find((o) => o.textContent?.includes('Codex'))!
    expect(codexOpt.disabled).toBe(true)
    expect(codexOpt.textContent).toContain('不可运行: 未在 PATH 找到 codex')

    // local_repos select
    const repoSelect = document.querySelector('[data-testid="repo-select"]') as HTMLSelectElement
    expect(repoSelect).not.toBeNull()
    const repoOptions = Array.from(repoSelect.querySelectorAll('option'))
    expect(repoOptions).toHaveLength(2)
    expect(repoOptions[0]!.textContent).toContain('toolbox-repo')
    expect(repoOptions[1]!.textContent).toContain('another-repo')

    // 不允许手动输入路径（无 text input 路径输入框）
    expect(document.querySelector('input[name="repo_path"]')).toBeNull()

    await b.done()
  })

  it('未配置本地仓库时显示前往设置添加的入口', async () => {
    const fake = createAiFetch({ repos: [] })
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    await b.wrapper.get('[data-testid="new-session-btn"]').trigger('click')
    await flushPromises()

    const jumpBtn = document.querySelector('[data-testid="jump-to-repos-btn"]') as HTMLButtonElement
    expect(jumpBtn).not.toBeNull()
    expect(jumpBtn.textContent).toContain('前往设置添加本地仓库')

    await b.done()
  })

  it('提交生成随机 request_id；防止双击重复提交保持幂等', async () => {
    const fake = createAiFetch()
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    await b.wrapper.get('[data-testid="new-session-btn"]').trigger('click')
    await flushPromises()

    const submitBtn = document.querySelector('button[type="submit"]') as HTMLButtonElement
    expect(submitBtn).not.toBeNull()
    submitBtn.click()
    await flushPromises()

    const postCall = fake.calls.find((c) => c.path === '/api/ai/sessions' && c.method === 'POST')
    expect(postCall).toBeDefined()
    const body = postCall!.body as Record<string, unknown>
    expect(body.kind).toBe('terminal')
    expect(typeof body.request_id).toBe('string')
    expect((body.request_id as string).length).toBeGreaterThan(10) // UUID
    expect(body.repo_id).toBe('repo-1')

    await b.done()
  })

  it('错误码 409 各分支与 503 呈现对应中文文案', async () => {
    const errorCases = [
      { code: 'ai_session_limit', text: '活动终端会话已达上限' },
      { code: 'cli_not_found', text: '未找到对应的 AI CLI 可执行文件' },
      { code: 'repo_missing', text: '本地仓库不存在' },
      { code: 'unsupported_cli', text: '不支持' },
    ]

    for (const ec of errorCases) {
      const fake = createAiFetch({
        onCreateSession: () => err(409, ec.code, 'Error detail'),
      })
      const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
      b.sock.emit(hello())
      await flushPromises()
      await flushPromises()

      await b.wrapper.get('[data-testid="new-session-btn"]').trigger('click')
      await flushPromises()

      const submitBtn = document.querySelector('button[type="submit"]') as HTMLButtonElement
      submitBtn.click()
      await flushPromises()

      const banner = document.querySelector('[data-testid="session-error-banner"]')
      expect(banner).not.toBeNull()
      expect(banner!.textContent).toContain(ec.text)

      await b.done()
    }

    // 503 ai_store_unavailable
    const fake503 = createAiFetch({
      onCreateSession: () => err(503, 'ai_store_unavailable', 'Store error'),
    })
    const b503 = await boot({ path: '/ai', fetchImpl: fake503.fetch })
    b503.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    await b503.wrapper.get('[data-testid="new-session-btn"]').trigger('click')
    await flushPromises()
    const submitBtn503 = document.querySelector('button[type="submit"]') as HTMLButtonElement
    submitBtn503.click()
    await flushPromises()

    const banner503 = document.querySelector('[data-testid="session-error-banner"]')
    expect(banner503).not.toBeNull()
    expect(banner503!.textContent).toContain('AI 存储不可用')
    await b503.done()
  })

  it('409 high_risk_ack_required 触发二次确认勾选框与中文提示', async () => {
    let callCount = 0
    const fake = createAiFetch({
      onCreateSession: (body: unknown) => {
        callCount++
        const b = body as { ack_high_risk?: boolean }
        if (!b.ack_high_risk) {
          return err(409, 'high_risk_ack_required', 'High risk ack required')
        }
        return json(
          {
            id: 'sess-high-risk',
            kind: 'terminal',
            cli: 'agy',
            repo: FAKE_LOCAL_REPOS[0],
            state: 'busy',
          },
          201,
        )
      },
    })
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    await b.wrapper.get('[data-testid="new-session-btn"]').trigger('click')
    await flushPromises()

    // 第一次提交：后端返回 high_risk_ack_required
    const submitBtn = document.querySelector('button[type="submit"]') as HTMLButtonElement
    submitBtn.click()
    await flushPromises()

    const banner = document.querySelector('[data-testid="session-error-banner"]')
    expect(banner?.textContent).toContain('高权限档位需要二次确认')

    const ackCheckbox = document.querySelector(
      '[data-testid="high-risk-ack-checkbox"]',
    ) as HTMLInputElement
    expect(ackCheckbox).not.toBeNull()

    // 勾选二次确认后再次提交
    ackCheckbox.checked = true
    ackCheckbox.dispatchEvent(new Event('change'))
    await flushPromises()

    submitBtn.click()
    await flushPromises()

    expect(callCount).toBe(2)
    await b.done()
  })
})

describe('S5-D 会话操作与右栏检查器', () => {
  it('中断操作调用 POST /api/ai/terminals/{sid}/interrupt', async () => {
    let interruptSid = ''
    const fake = createAiFetch({
      onInterrupt: (sid) => {
        interruptSid = sid
        return json({ status: 'interrupted' })
      },
    })
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 选中 running 会话
    await b.wrapper.get('[data-testid="session-sess-running-1"]').trigger('click')
    await flushPromises()

    const interruptBtn = b.wrapper.get('[data-testid="interrupt-btn"]')
    expect(interruptBtn.attributes('disabled')).toBeUndefined()
    await interruptBtn.trigger('click')
    await flushPromises()

    expect(interruptSid).toBe('sess-running-1')
    await b.done()
  })

  it('关闭操作经 Sheet 确认调用 POST /api/ai/sessions/{sid}/close', async () => {
    let closedSid = ''
    const fake = createAiFetch({
      onClose: (sid) => {
        closedSid = sid
        return json({ status: 'closed' })
      },
    })
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    await b.wrapper.get('[data-testid="session-sess-running-1"]').trigger('click')
    await flushPromises()

    await b.wrapper.get('[data-testid="close-btn"]').trigger('click')
    await flushPromises()

    // 弹出确认单在 document.body 中
    const confirmBtn = document.querySelector(
      '[data-testid="confirm-close-btn"]',
    ) as HTMLButtonElement
    expect(confirmBtn).not.toBeNull()
    confirmBtn.click()
    await flushPromises()

    expect(closedSid).toBe('sess-running-1')
    await b.done()
  })

  it('删除操作仅终态可见，经 Sheet 确认调用 DELETE /api/ai/sessions/{sid}', async () => {
    let deletedSid = ''
    const fake = createAiFetch({
      onDelete: (sid) => {
        deletedSid = sid
        return json({ status: 'deleted' })
      },
    })
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 选 running 会话：删除按钮不存在
    await b.wrapper.get('[data-testid="session-sess-running-1"]').trigger('click')
    await flushPromises()
    expect(b.wrapper.find('[data-testid="delete-btn"]').exists()).toBe(false)

    // 选 ended 会话：删除按钮可见
    await b.wrapper.get('[data-testid="session-sess-ended-2"]').trigger('click')
    await flushPromises()

    const deleteBtn = b.wrapper.find('[data-testid="delete-btn"]')
    expect(deleteBtn.exists()).toBe(true)
    await deleteBtn.trigger('click')
    await flushPromises()

    const confirmBtn = document.querySelector(
      '[data-testid="confirm-delete-btn"]',
    ) as HTMLButtonElement
    expect(confirmBtn).not.toBeNull()
    confirmBtn.click()
    await flushPromises()

    expect(deletedSid).toBe('sess-ended-2')
    await b.done()
  })

  it('右栏信息展示工具、仓库、状态、开始时间、结束原因与退出码；隐藏 chat 专属指标', async () => {
    const fake = createAiFetch()
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    await b.wrapper.get('[data-testid="session-sess-ended-2"]').trigger('click')
    await flushPromises()

    const inspector = b.wrapper.find('[data-testid="ai-terminal-inspector"]')
    expect(inspector.exists()).toBe(true)
    const text = inspector.text()
    expect(text).toContain('工具')
    expect(text).toContain('codex')
    expect(text).toContain('仓库')
    expect(text).toContain('toolbox-repo')
    expect(text).toContain('状态')
    expect(text).toContain('已结束')
    expect(text).toContain('结束原因')
    expect(text).toContain('进程退出')
    expect(text).toContain('退出码')
    expect(text).toContain('0')

    // 严禁显示 chat 专属指标
    expect(inspector.text()).not.toContain('上下文用量')
    expect(inspector.text()).not.toContain('本会话已允许')

    await b.done()
  })

  it('安全门禁：token 与终端输出不进 localStorage / sessionStorage / DOM', async () => {
    const fake = createAiFetch()
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 检查 localStorage 与 sessionStorage 任何键值均不含 fake-token
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)!
      expect(key).not.toContain('fake-token')
      expect(localStorage.getItem(key)).not.toContain('fake-token')
    }
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i)!
      expect(key).not.toContain('fake-token')
      expect(sessionStorage.getItem(key)).not.toContain('fake-token')
    }

    // DOM 中不暴露 token
    expect(document.body.innerHTML).not.toContain('fake-token')

    await b.done()
  })

  it('键盘可达性：Esc 可关闭新建会话 Sheet 与操作确认 Sheet', async () => {
    const fake = createAiFetch()
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 1. 打开新建会话 Sheet
    await b.wrapper.get('[data-testid="new-session-btn"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-testid="new-session-form"]')).not.toBeNull()

    // 按 Esc 关闭
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(document.querySelector('[data-testid="new-session-form"]')).toBeNull()

    // 2. 打开关闭会话确认 Sheet
    await b.wrapper.get('[data-testid="session-sess-running-1"]').trigger('click')
    await flushPromises()
    await b.wrapper.get('[data-testid="close-btn"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-testid="confirm-close-btn"]')).not.toBeNull()

    // 按 Esc 关闭
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(document.querySelector('[data-testid="confirm-close-btn"]')).toBeNull()

    await b.done()
  })
})

describe('S5-D1 第 2 轮回归测试 (S5D-T01, S5D-T02, S5D-T03)', () => {
  it('S5D-T01 回归：会话列表 GET 失败时不得回退 mock 假会话，显示错误态（含重试按钮）', async () => {
    const fake = createAiFetch({
      onGetSessions: () => err(503, 'ai_store_unavailable', 'DB_LOCKED'),
    })
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const body = document.body.innerHTML
    // 不得冒充 mock 会话
    expect(body).not.toContain('权限缓存未刷新')
    expect(body).not.toContain('web-portal (终端)')
    // 渲染错误态与重试按钮
    expect(document.querySelector('[data-testid="sessions-error-state"]')).not.toBeNull()
    expect(document.querySelector('[data-testid="retry-sessions-btn"]')).not.toBeNull()

    await b.done()
  })

  it('S5D-T02 回归：服务端原始 detail 字符串与校验信息不得原样显示，按 code 映射安全中文', () => {
    // 503 原始字符串 detail
    const err503 = toApiError(503, { detail: 'INTERNAL_RAW_CORRUPTED_SQLITE_PATH /var/data/ai.db' })
    expect(err503.code).toBe('ai_store_unavailable')
    expect(err503.message).toBe('AI 存储不可用（只读错误态）')
    expect(err503.message).not.toContain('SQLITE_PATH')

    // 422 Pydantic 参数校验包含敏感输入回显
    const err422 = toApiError(422, {
      detail: [{ loc: ['body', 'repo_id'], msg: 'invalid id', input: 'SECRET_REPO_TOKEN_123' }],
    })
    expect(err422.code).toBe('validation_error')
    expect(err422.message).toBe('输入参数格式不正确')
    expect(err422.message).not.toContain('SECRET_REPO_TOKEN_123')
  })

  it('S5D-T03 回归：ai.session 覆盖层与 GET 快照基于 last_seq 双向对账', async () => {
    let sessionSeq = 3
    let sessionState = 'busy'
    const fake = createAiFetch({
      onGetSessions: () =>
        json({
          items: [
            {
              id: 'sess-running-1',
              kind: 'terminal',
              cli: 'claude',
              profile_id: 'prof-claude',
              repo_id: 'repo-1',
              repo: { id: 'repo-1', name: 'toolbox-repo', path: '/path' },
              state: sessionState,
              last_seq: sessionSeq,
              created_at: '2026-10-23T12:00:00Z',
            },
          ],
        }),
    })
    const b = await boot({ path: '/ai', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    const getRowText = () =>
      document.querySelector('[data-testid="session-sess-running-1"]')?.textContent ?? ''

    expect(getRowText()).toContain('运行中')

    // 1. 发送更新的 WS 事件 (seq 9 -> ended)
    b.sock.emit(
      env(
        'ai.session',
        {
          session_id: 'sess-running-1',
          state: 'ended',
          ended_reason: 'process_exited',
          last_seq: 9,
        },
        { topic: 'ai' },
      ),
    )
    await flushPromises()
    expect(getRowText()).toContain('已结束')

    // 2. 模拟陈旧在途 GET 返回 (seq 4 < 9)，不回滚状态
    sessionSeq = 4
    sessionState = 'busy'
    await b.wrapper.vm.$nextTick()
    await flushPromises()
    expect(getRowText()).toContain('已结束')

    // 3. 模拟随后的刷新拿到了更高的 seq (seq 12)，覆盖旧状态
    sessionSeq = 12
    sessionState = 'busy'
    // 触发刷新
    b.sock.emit(
      env(
        'ai.session',
        {
          session_id: 'sess-running-1',
          state: 'busy',
          last_seq: 12,
        },
        { topic: 'ai' },
      ),
    )
    await flushPromises()
    expect(getRowText()).toContain('运行中')

    await b.done()
  })
})
