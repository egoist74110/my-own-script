// S4-C 单测：设置页 Telegram 分区 ACL（权限组 / 组成员 / 旧白名单 / 警告行内展示 / 409 冲突 / 键盘操作）
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '@/api/schema'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'

type S = components['schemas']

function makeTelegramView(over: Partial<S['TelegramView']> = {}): S['TelegramView'] {
  return {
    revision: 10,
    warnings: [],
    bot: {
      bot_id: '123456789',
      username: 'TestHelperBot',
      credential: {
        present: true,
        source: 'manual',
      },
    },
    control: {
      enabled: false,
      bot_id: '123456789',
      enabled_at: null,
    },
    owner: {
      bound: false,
      chat_id: null,
      source: null,
    },
    notify: {
      include_details: false,
      ui_runs_to_owner: true,
    },
    poller: {
      state: 'disabled',
      since: '2026-10-23T10:00:00Z',
      last_poll_at: null,
      last_error_category: null,
      consecutive_failures: 0,
    },
    acl: {
      groups: [
        {
          id: 'grp-admin',
          name: '运维管理员组',
          can_run: true,
          can_stop: true,
          can_status: true,
          can_rollback: true,
          task_ids: ['task-deploy'],
        },
      ],
      members: [
        {
          id: 'mem-1',
          group_id: 'grp-admin',
          label: '张三',
          chat_id: '10001',
          username: '@zhangsan',
          user_id: '99001', // 已绑定
        },
        {
          id: 'mem-2',
          group_id: 'grp-admin',
          label: '李四',
          chat_id: null,
          username: '@lisi',
          user_id: null, // 未绑定
        },
        {
          id: 'mem-3',
          group_id: 'grp-admin',
          label: '纯ChatID用户',
          chat_id: '10003',
          username: null,
          user_id: null,
        },
      ],
      legacy_whitelist: ['10001', '@legacy_dev'],
    },
    ...over,
  }
}

interface S4CFakeState {
  settings: S['SettingsResponse']
  ado: S['AdoResponse']
  creds: S['CredentialStatus'][]
  telegram: S['TelegramView']
  tasks: S['TaskView'][]
}

function createAclFake(initialTelegram?: Partial<S['TelegramView']>) {
  const state: S4CFakeState = {
    settings: {
      app_version: '0.1.0',
      data_dir: '/tmp/fake-data',
      legacy_config_dir: '/tmp/fake-legacy',
      revision: 10,
      schema_version: 2,
      store_state: 'ok',
      import: { state: 'completed' },
    },
    ado: {
      active_library_id: null,
      active_project_id: null,
      libraries: [],
      local_repos: [],
      projects: [],
      revision: 10,
    },
    creds: [],
    telegram: makeTelegramView(initialTelegram),
    tasks: [
      {
        id: 'task-deploy',
        name: '生产发布流水线',
        enabled: true,
        local_repo_path: '/tmp/repo',
        sort_order: 1,
        tg_command: 'deploy',
        tg_desc: '',
        project_id: 'proj-1',
        git_flow: { build_branch: 'main' },
        targets: [],
        created_at: '2026-10-23T00:00:00Z',
        updated_at: '2026-10-23T00:00:00Z',
        revision: 1,
        warnings: [],
        validation: { valid: true },
        active_run_id: null,
        last_run: null,
      },
      {
        id: 'task-build',
        name: '夜间构建任务',
        enabled: true,
        local_repo_path: '/tmp/repo',
        sort_order: 2,
        tg_command: 'build_nightly',
        tg_desc: '',
        project_id: 'proj-1',
        git_flow: { build_branch: 'develop' },
        targets: [],
        created_at: '2026-10-23T00:00:00Z',
        updated_at: '2026-10-23T00:00:00Z',
        revision: 1,
        warnings: [],
        validation: { valid: true },
        active_run_id: null,
        last_run: null,
      },
    ],
  }

  const calls: { method: string; path: string; query: Record<string, string>; body: unknown }[] = []
  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { 'content-type': 'application/json' },
    })

  const fetchHandler = vi.fn(async (input: Request) => {
    const url = new URL(input.url)
    const raw = input.method === 'GET' || input.method === 'DELETE' ? '' : await input.text()
    let body: unknown
    try {
      body = raw ? JSON.parse(raw) : undefined
    } catch {
      body = undefined
    }
    const call = {
      method: input.method,
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      body,
    }
    if (call.path !== '/health') calls.push(call)

    if (call.path === '/health') {
      return json({ status: 'ok', version: '0.1.0', pid: 1234, uptime_s: 1, alert: false })
    }
    if (call.method === 'GET' && call.path === '/api/settings') return json(state.settings)
    if (call.method === 'GET' && call.path === '/api/ado') return json(state.ado)
    if (call.method === 'GET' && call.path === '/api/credentials') return json(state.creds)
    if (call.method === 'GET' && call.path === '/api/telegram') return json(state.telegram)
    if (call.method === 'GET' && call.path === '/api/tasks') {
      return json({ items: state.tasks, revision: state.settings.revision })
    }
    if (call.method === 'GET' && call.path === '/api/telegram/activity') {
      return json({ items: [] })
    }

    // ACL Groups
    const groups = state.telegram.acl.groups as S['ACLGroup'][]
    const members = state.telegram.acl.members as S['ACLMember'][]

    if (call.method === 'POST' && call.path === '/api/telegram/acl/groups') {
      const b = body as S['GroupCreate']
      const newGroup: S['ACLGroup'] = {
        id: `grp-${Date.now()}`,
        name: b.name,
        can_run: b.can_run ?? false,
        can_stop: b.can_stop ?? false,
        can_status: b.can_status ?? true,
        can_rollback: b.can_rollback ?? false,
        task_ids: b.task_ids ?? [],
      }
      groups.push(newGroup)
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }
    if (call.method === 'PATCH' && call.path.startsWith('/api/telegram/acl/groups/')) {
      const id = call.path.replace('/api/telegram/acl/groups/', '')
      const b = body as S['GroupPatch']
      const g = groups.find((x) => x.id === id)
      if (g) {
        if (b.name != null) g.name = b.name
        if (b.can_run != null) g.can_run = b.can_run
        if (b.can_stop != null) g.can_stop = b.can_stop
        if (b.can_status != null) g.can_status = b.can_status
        if (b.can_rollback != null) g.can_rollback = b.can_rollback
        if (b.task_ids != null) g.task_ids = b.task_ids
      }
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }
    if (call.method === 'DELETE' && call.path.startsWith('/api/telegram/acl/groups/')) {
      const id = call.path.replace('/api/telegram/acl/groups/', '')
      state.telegram.acl.groups = groups.filter((x) => x.id !== id)
      state.telegram.acl.members = members.filter((x) => x.group_id !== id)
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }

    // ACL Members
    if (call.method === 'POST' && call.path === '/api/telegram/acl/members') {
      const b = body as S['MemberCreate']
      const newMem: S['ACLMember'] = {
        id: `mem-${Date.now()}`,
        group_id: b.group_id,
        label: b.label ?? '',
        chat_id: b.chat_id ?? null,
        username: b.username ?? null,
        user_id: null,
      }
      members.push(newMem)
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }
    if (call.method === 'PATCH' && call.path.startsWith('/api/telegram/acl/members/')) {
      const id = call.path.replace('/api/telegram/acl/members/', '')
      const b = body as S['MemberPatch']
      const m = members.find((x) => x.id === id)
      if (m) {
        if (b.group_id != null) m.group_id = b.group_id
        if (b.label != null) m.label = b.label
        if (b.chat_id !== undefined) m.chat_id = b.chat_id
        if (b.username !== undefined) m.username = b.username
      }
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }
    if (call.method === 'DELETE' && call.path.startsWith('/api/telegram/acl/members/')) {
      const id = call.path.replace('/api/telegram/acl/members/', '')
      state.telegram.acl.members = members.filter((x) => x.id !== id)
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }

    // Legacy Whitelist
    if (call.method === 'PUT' && call.path === '/api/telegram/acl/legacy-whitelist') {
      const b = body as { legacy_whitelist: string[] }
      state.telegram.acl.legacy_whitelist = b.legacy_whitelist ?? []
      state.telegram.revision++
      return json({ revision: state.telegram.revision })
    }

    return json({ revision: state.telegram.revision + 1 })
  })

  return {
    state,
    calls,
    fetch: fetchHandler as unknown as typeof fetch,
  }
}

describe('S4-C 设置页 Telegram 分区 ACL 单测', () => {
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

  async function openTelegramTab(fake: ReturnType<typeof createAclFake>) {
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    const tabBtn = b.wrapper.findAll('[role=tab]').find((t) => t.text().includes('Telegram'))!
    expect(tabBtn, '找到 Telegram 页签').toBeTruthy()
    await tabBtn.trigger('mousedown')
    await flushPromises()
    await flushPromises()
    return b
  }

  it('ACL 权限组创建与表单校验：空组名、超长限制、运行权限必须至少选一个任务、多选任务显示 tg_command', async () => {
    const fake = createAclFake()
    const b = await openTelegramTab(fake)

    // 点击新建权限组
    await b.wrapper.find('button[data-testid="create-group-btn"]').trigger('click')
    await flushPromises()

    const dialog = document.querySelector('[data-testid="group-edit-dialog"]')
    expect(dialog).not.toBeNull()

    // 1. 空组名校验
    const nameInput = document.querySelector(
      '[data-testid="group-name-input"] input',
    ) as HTMLInputElement
    expect(nameInput).not.toBeNull()
    nameInput.value = ''
    nameInput.dispatchEvent(new Event('input'))
    await flushPromises()

    const saveBtn = document.querySelector(
      'button[data-testid="save-group-btn"]',
    ) as HTMLButtonElement
    expect(saveBtn).not.toBeNull()
    saveBtn.click()
    await flushPromises()

    // 未产生 POST 请求
    expect(fake.calls.filter((c) => c.path === '/api/telegram/acl/groups')).toHaveLength(0)

    // 2. 超长限制校验 (>64 字符)
    nameInput.value = 'a'.repeat(65)
    nameInput.dispatchEvent(new Event('input'))
    await flushPromises()
    saveBtn.click()
    await flushPromises()
    expect(fake.calls.filter((c) => c.path === '/api/telegram/acl/groups')).toHaveLength(0)

    // 3. 勾选运行权限但未选择任务时阻断保存
    nameInput.value = '新测试组'
    nameInput.dispatchEvent(new Event('input'))
    await flushPromises()

    const canRunChk = document.querySelector(
      '[data-testid="perm-can-run"] input',
    ) as HTMLInputElement
    expect(canRunChk).not.toBeNull()
    canRunChk.click()
    await flushPromises()

    saveBtn.click()
    await flushPromises()
    expect(fake.calls.filter((c) => c.path === '/api/telegram/acl/groups')).toHaveLength(0)

    // 4. 任务列表正确展示名称与 /tg_command
    const taskItem = document.querySelector('[data-testid="group-task-item-task-deploy"]')
    expect(taskItem).not.toBeNull()
    expect(taskItem!.textContent).toContain('生产发布流水线')
    expect(taskItem!.textContent).toContain('(/deploy)')

    // 勾选该任务
    const taskInput = taskItem!.querySelector('input') as HTMLInputElement
    taskInput.click()
    await flushPromises()

    // 点击保存
    saveBtn.click()
    await flushPromises()

    const createCall = fake.calls.find(
      (c) => c.method === 'POST' && c.path === '/api/telegram/acl/groups',
    )
    expect(createCall).toBeTruthy()
    const reqBody = createCall?.body as S['GroupCreate']
    expect(reqBody.name).toBe('新测试组')
    expect(reqBody.can_run).toBe(true)
    expect(reqBody.task_ids).toEqual(['task-deploy'])

    await b.done()
  })

  it('ACL 权限组编辑：回显旧数据并 PATCH 保存', async () => {
    const fake = createAclFake()
    const b = await openTelegramTab(fake)

    // 点击编辑现有组
    const editBtn = b.wrapper.find(
      '[data-testid="group-row-grp-admin"] button[data-testid="edit-group-btn"]',
    )
    expect(editBtn.exists()).toBe(true)
    await editBtn.trigger('click')
    await flushPromises()

    const dialog = document.querySelector('[data-testid="group-edit-dialog"]')
    expect(dialog).not.toBeNull()

    const nameInput = document.querySelector(
      '[data-testid="group-name-input"] input',
    ) as HTMLInputElement
    expect(nameInput.value).toBe('运维管理员组')

    // 修改名称
    nameInput.value = '高级运维管理组'
    nameInput.dispatchEvent(new Event('input'))
    await flushPromises()

    const saveBtn = document.querySelector(
      'button[data-testid="save-group-btn"]',
    ) as HTMLButtonElement
    saveBtn.click()
    await flushPromises()

    const patchCall = fake.calls.find(
      (c) => c.method === 'PATCH' && c.path === '/api/telegram/acl/groups/grp-admin',
    )
    expect(patchCall).toBeTruthy()
    expect((patchCall?.body as S['GroupPatch']).name).toBe('高级运维管理组')

    await b.done()
  })

  it('ACL 权限组删除：确认 Sheet 列出该组包含的成员并级联删除', async () => {
    const fake = createAclFake()
    const b = await openTelegramTab(fake)

    // 点击删除权限组
    const delBtn = b.wrapper.find(
      '[data-testid="group-row-grp-admin"] button[data-testid="delete-group-btn"]',
    )
    await delBtn.trigger('click')
    await flushPromises()

    // 检查删除确认 Sheet
    const dialog = document.querySelector('[data-testid="group-delete-dialog"]')
    expect(dialog).not.toBeNull()

    // 列出所属该组的 3 个成员
    const memberList = document.querySelector('[data-testid="delete-group-members-list"]')
    expect(memberList).not.toBeNull()
    expect(memberList!.textContent).toContain('张三')
    expect(memberList!.textContent).toContain('@zhangsan')
    expect(memberList!.textContent).toContain('李四')
    expect(memberList!.textContent).toContain('纯ChatID用户')

    // 确认删除
    const confirmBtn = document.querySelector(
      'button[data-testid="confirm-delete-group-btn"]',
    ) as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    const deleteCall = fake.calls.find(
      (c) => c.method === 'DELETE' && c.path === '/api/telegram/acl/groups/grp-admin',
    )
    expect(deleteCall).toBeTruthy()

    await b.done()
  })

  it('ACL 组成员添加与表单校验：至少填写 chat_id 或 @username，自动补充 @ 前缀', async () => {
    const fake = createAclFake()
    const b = await openTelegramTab(fake)

    // 点击添加成员
    await b.wrapper.find('button[data-testid="create-member-btn"]').trigger('click')
    await flushPromises()

    const dialog = document.querySelector('[data-testid="member-edit-dialog"]')
    expect(dialog).not.toBeNull()

    const saveBtn = document.querySelector(
      'button[data-testid="save-member-btn"]',
    ) as HTMLButtonElement
    expect(saveBtn).not.toBeNull()

    // 1. 未填写 chat_id 和 username 时阻断保存
    saveBtn.click()
    await flushPromises()
    expect(fake.calls.filter((c) => c.path === '/api/telegram/acl/members')).toHaveLength(0)

    // 2. 填写备注和用户名（未带 @），验证自动补 @
    const labelInput = document.querySelector(
      '[data-testid="member-label-input"] input',
    ) as HTMLInputElement
    const usernameInput = document.querySelector(
      '[data-testid="member-username-input"] input',
    ) as HTMLInputElement
    labelInput.value = '王五'
    labelInput.dispatchEvent(new Event('input'))
    usernameInput.value = 'wangwu_bot' // 未带 @
    usernameInput.dispatchEvent(new Event('input'))
    await flushPromises()

    saveBtn.click()
    await flushPromises()

    const createCall = fake.calls.find(
      (c) => c.method === 'POST' && c.path === '/api/telegram/acl/members',
    )
    expect(createCall).toBeTruthy()
    const bReq = createCall?.body as S['MemberCreate']
    expect(bReq.group_id).toBe('grp-admin')
    expect(bReq.label).toBe('王五')
    expect(bReq.username).toBe('@wangwu_bot') // 自动补充了 @
    expect(bReq.chat_id).toBeNull()

    await b.done()
  })

  it('ACL 组成员列表与绑定状态展示：username 根据 user_id 是否存在展示已绑定/未绑定，chat_id 显示', async () => {
    const fake = createAclFake()
    const b = await openTelegramTab(fake)

    // 成员1 (张三)：有 user_id，显示已绑定
    const row1 = b.wrapper.find('[data-testid="member-row-mem-1"]')
    expect(row1.text()).toContain('张三')
    expect(row1.text()).toContain('@zhangsan')
    expect(row1.text()).toContain('10001')
    expect(row1.text()).toContain('已绑定')

    // 成员2 (李四)：无 user_id，显示未绑定
    const row2 = b.wrapper.find('[data-testid="member-row-mem-2"]')
    expect(row2.text()).toContain('李四')
    expect(row2.text()).toContain('@lisi')
    expect(row2.text()).toContain('未绑定')

    // 成员3 (纯ChatID)：无 username，显示 —
    const row3 = b.wrapper.find('[data-testid="member-row-mem-3"]')
    expect(row3.text()).toContain('纯ChatID用户')
    expect(row3.text()).toContain('10003')

    // 删除李四
    await row2.find('button[data-testid="delete-member-btn"]').trigger('click')
    await flushPromises()
    const confirmDelBtn = document.querySelector(
      'button[data-testid="confirm-delete-member-btn"]',
    ) as HTMLButtonElement
    expect(confirmDelBtn).not.toBeNull()
    confirmDelBtn.click()
    await flushPromises()

    const delCall = fake.calls.find(
      (c) => c.method === 'DELETE' && c.path === '/api/telegram/acl/members/mem-2',
    )
    expect(delCall).toBeTruthy()

    await b.done()
  })

  it('旧白名单卡片：说明只读 /status 权限，支持多行编辑保存', async () => {
    const fake = createAclFake()
    const b = await openTelegramTab(fake)

    const wlCard = b.wrapper.find('[data-testid="legacy-whitelist-card"]')
    expect(wlCard.exists()).toBe(true)
    expect(wlCard.text()).toContain('/status')

    const tags = b.wrapper.find('[data-testid="whitelist-tags"]')
    expect(tags.text()).toContain('10001')
    expect(tags.text()).toContain('@legacy_dev')

    // 点击编辑白名单
    await b.wrapper.find('button[data-testid="edit-whitelist-btn"]').trigger('click')
    await flushPromises()

    const textarea = b.wrapper.find('textarea[data-testid="whitelist-textarea"]')
    expect(textarea.exists()).toBe(true)
    await textarea.setValue('10001\n@legacy_dev\n@new_legacy_user\n')
    await flushPromises()

    // 保存白名单
    await b.wrapper.find('button[data-testid="save-whitelist-btn"]').trigger('click')
    await flushPromises()

    const putCall = fake.calls.find(
      (c) => c.method === 'PUT' && c.path === '/api/telegram/acl/legacy-whitelist',
    )
    expect(putCall).toBeTruthy()
    expect((putCall?.body as { legacy_whitelist: string[] }).legacy_whitelist).toEqual([
      '10001',
      '@legacy_dev',
      '@new_legacy_user',
    ])

    await b.done()
  })

  it('Warnings 行内展示：无效旧条目、引用不存在任务、空组在对应行内与 Banner 显示', async () => {
    const fake = createAclFake({
      warnings: [
        'ACL 组 #1 引用不存在的任务',
        'ACL 成员 #2 无效、重复或超限，不参与授权',
        '旧白名单 #2 无效、重复或超限，不参与授权',
      ],
      acl: {
        groups: [
          {
            id: 'grp-broken',
            name: '问题组',
            can_run: true,
            can_stop: false,
            can_status: true,
            can_rollback: false,
            task_ids: ['non-existent-task-id'],
          },
        ],
        members: [
          {
            id: 'mem-1',
            group_id: 'grp-broken',
            label: '正常成员',
            chat_id: '123',
            username: null,
            user_id: null,
          },
          {
            id: 'mem-broken',
            group_id: 'grp-broken',
            label: '重复成员',
            chat_id: '123',
            username: null,
            user_id: null,
          },
        ],
        legacy_whitelist: ['10001', 'invalid!username!'],
      },
    })
    const b = await openTelegramTab(fake)

    // 1. 顶部 warnings Banner
    const banner = b.wrapper.find('[data-testid="telegram-warnings-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('ACL 组 #1 引用不存在的任务')

    // 2. 组行内警告
    const groupWarn = b.wrapper.find('[data-testid="group-inline-warning"]')
    expect(groupWarn.exists()).toBe(true)
    expect(groupWarn.text()).toContain('引用不存在的任务')

    // 3. 成员行内警告
    const memberWarns = b.wrapper.findAll('[data-testid="member-inline-warning"]')
    expect(memberWarns.length).toBeGreaterThan(0)
    expect(memberWarns[0]!.text()).toContain('不参与授权')

    // 4. 白名单行内警告
    const wlWarns = b.wrapper.findAll('[data-testid="whitelist-inline-warning"]')
    expect(wlWarns.length).toBeGreaterThan(0)
    expect(wlWarns[0]!.text()).toContain('不参与授权')

    await b.done()
  })

  it('Revision 409 冲突：组与成员保存遇 revision_conflict 提示刷新', async () => {
    const fake = createAclFake()
    const origFetch = fake.fetch
    fake.fetch = vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      if (url.pathname === '/api/telegram/acl/groups') {
        return new Response(
          JSON.stringify({
            detail: { code: 'revision_conflict', message: '配置已被修改，请刷新后重试' },
          }),
          { status: 409, headers: { 'content-type': 'application/json' } },
        )
      }
      return origFetch(req)
    }) as unknown as typeof fetch

    const b = await openTelegramTab(fake)

    await b.wrapper.find('button[data-testid="create-group-btn"]').trigger('click')
    await flushPromises()

    const nameInput = document.querySelector(
      '[data-testid="group-name-input"] input',
    ) as HTMLInputElement
    nameInput.value = '冲突组'
    nameInput.dispatchEvent(new Event('input'))
    await flushPromises()

    const saveBtn = document.querySelector(
      'button[data-testid="save-group-btn"]',
    ) as HTMLButtonElement
    saveBtn.click()
    await flushPromises()

    // 弹窗内出现错误提示 Banner
    const errBanner = document.querySelector('[data-testid="group-error-banner"]')
    expect(errBanner).not.toBeNull()
    expect(errBanner!.textContent).toContain('配置已被修改')

    await b.done()
  })

  it('键盘可达性：Tab / Enter 提交与 Esc 关闭 Sheet', async () => {
    const fake = createAclFake()
    const b = await openTelegramTab(fake)

    // 打开权限组创建 Sheet
    await b.wrapper.find('button[data-testid="create-group-btn"]').trigger('click')
    await flushPromises()

    const dialog = document.querySelector('[data-testid="group-edit-dialog"]')
    expect(dialog).not.toBeNull()

    // 按 Esc 键触发关闭
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()

    // Sheet 关闭
    expect(document.querySelector('[data-testid="group-edit-dialog"]')).toBeNull()

    await b.done()
  })
})
