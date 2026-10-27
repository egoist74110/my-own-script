// S9-C 单测：设置页“关于与更新”卡（UpdateCard 与 useUpdate 组合式）
// 假 invoke/listen 测试各 state 渲染、按钮矩阵、动作调用与二次确认、事件推送、非 Tauri 降级、XSS 防御、安全检查与卸载取消订阅
import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UpdateCard from '@/features/settings/UpdateCard.vue'
import {
  UPDATE_ERROR_MESSAGES,
  updateErrorMessage,
  type UpdateErrorCode,
  type UpdateStatus,
  type UpdateSources,
} from '@/features/settings/useUpdate'

interface FakeTauri {
  invoke: ReturnType<typeof vi.fn>
  listen: ReturnType<typeof vi.fn>
  unlisten: ReturnType<typeof vi.fn>
  calls: Array<{ cmd: string; args?: Record<string, unknown> }>
  listeners: Array<(event: { payload: UpdateStatus }) => void>
  emitStatus: (status: Partial<UpdateStatus>) => void
  sources: UpdateSources
}

function createFakeTauri(initial: Partial<UpdateStatus> = {}): FakeTauri {
  let current: UpdateStatus = {
    state: 'idle',
    current_version: '1.0.0',
    available_version: null,
    notes: null,
    progress: null,
    error_code: null,
    checked_at: 1761552000, // 2025-10-27T08:00:00Z
    ...initial,
  }

  const calls: Array<{ cmd: string; args?: Record<string, unknown> }> = []
  const listeners: Array<(event: { payload: UpdateStatus }) => void> = []

  const unlisten = vi.fn(() => {
    listeners.length = 0
  })

  const invoke = vi.fn(async (cmd: string, args?: Record<string, unknown>) => {
    calls.push({ cmd, args })
    if (cmd === 'update_status') {
      return JSON.parse(JSON.stringify(current))
    }
    if (cmd === 'update_check') {
      current.state = 'checking'
      return JSON.parse(JSON.stringify(current))
    }
    if (cmd === 'update_install') {
      current.state = 'downloading'
      return JSON.parse(JSON.stringify(current))
    }
    if (cmd === 'update_cancel') {
      return JSON.parse(JSON.stringify(current))
    }
    if (cmd === 'update_restart') {
      return
    }
    throw new Error(`unknown command: ${cmd}`)
  })

  const listen = vi.fn(async (event: string, handler: (e: { payload: unknown }) => void) => {
    if (event === 'update://status') {
      listeners.push(handler as (e: { payload: UpdateStatus }) => void)
    }
    return unlisten
  })

  function emitStatus(patch: Partial<UpdateStatus>) {
    current = { ...current, ...patch }
    for (const l of [...listeners]) {
      l({ payload: JSON.parse(JSON.stringify(current)) })
    }
  }

  return {
    invoke,
    listen,
    unlisten,
    calls,
    listeners,
    emitStatus,
    sources: {
      getTauriInvoke: () => invoke,
      getTauriListen: () =>
        listen as unknown as ReturnType<NonNullable<UpdateSources['getTauriListen']>>,
    },
  }
}

describe('S9-C UpdateCard & useUpdate', () => {
  beforeEach(() => {
    delete (globalThis as Record<string, unknown>).__TAURI_INTERNALS__
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  describe('各 state 渲染', () => {
    it('disabled 渲染：update_not_configured 原因', async () => {
      const fake = createFakeTauri({
        state: 'disabled',
        error_code: 'update_not_configured',
      })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-card"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="update-disabled-reason"]').text()).toContain(
        '未配置更新源',
      )
      expect(wrapper.find('[data-testid="update-current-version"]').text()).toBe('1.0.0')

      // 所有操作按钮禁用
      const checkBtn = wrapper.find('[data-testid="update-check-btn"]')
      expect(checkBtn.attributes('disabled')).toBeDefined()
      expect(wrapper.find('[data-testid="update-install-btn"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="update-cancel-btn"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="update-restart-btn"]').exists()).toBe(false)
    })

    it('disabled 渲染：update_unsupported_dev 原因', async () => {
      const fake = createFakeTauri({
        state: 'disabled',
        error_code: 'update_unsupported_dev',
      })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-disabled-reason"]').text()).toContain(
        '开发态不支持更新',
      )
      expect(wrapper.find('[data-testid="update-check-btn"]').attributes('disabled')).toBeDefined()
    })

    it('idle 渲染', async () => {
      const fake = createFakeTauri({ state: 'idle' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-card"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="update-state-text"]').text()).toMatch(/空闲|就绪/)
      expect(
        wrapper.find('[data-testid="update-check-btn"]').attributes('disabled'),
      ).toBeUndefined()
    })

    it('checking 渲染', async () => {
      const fake = createFakeTauri({ state: 'checking' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toContain('正在检查更新')
      expect(wrapper.find('[data-testid="update-check-btn"]').attributes('disabled')).toBeDefined()
      expect(wrapper.find('[data-testid="update-cancel-btn"]').exists()).toBe(true)
      expect(
        wrapper.find('[data-testid="update-cancel-btn"]').attributes('disabled'),
      ).toBeUndefined()
    })

    it('up_to_date 渲染', async () => {
      const fake = createFakeTauri({ state: 'up_to_date' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toContain('已是最新')
      expect(
        wrapper.find('[data-testid="update-check-btn"]').attributes('disabled'),
      ).toBeUndefined()
    })

    it('available 渲染：展示可用版本与更新说明（保留换行）', async () => {
      const fake = createFakeTauri({
        state: 'available',
        available_version: '1.2.0',
        notes: '第一行说明\n第二行说明\n• 修复若干问题',
      })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toContain('发现新版本')
      expect(wrapper.find('[data-testid="update-available-version"]').text()).toContain('1.2.0')
      const notesEl = wrapper.find('[data-testid="update-notes"]')
      expect(notesEl.exists()).toBe(true)
      expect(notesEl.text()).toContain('第一行说明')
      expect(notesEl.text()).toContain('第二行说明')
      expect(notesEl.text()).toContain('• 修复若干问题')

      expect(wrapper.find('[data-testid="update-install-btn"]').exists()).toBe(true)
      expect(
        wrapper.find('[data-testid="update-install-btn"]').attributes('disabled'),
      ).toBeUndefined()
    })

    it('downloading 渲染：含进度与总量', async () => {
      const fake = createFakeTauri({
        state: 'downloading',
        progress: { downloaded: 5242880, total: 10485760 },
      })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toContain('正在下载更新')
      const progressEl = wrapper.find('[data-testid="update-progress-bar"]')
      expect(progressEl.exists()).toBe(true)
      expect(progressEl.attributes('role')).toBe('progressbar')
      expect(progressEl.attributes('aria-valuenow')).toBe('50')

      const progressText = wrapper.find('[data-testid="update-progress-text"]').text()
      expect(progressText).toContain('5 MB')
      expect(progressText).toContain('10 MB')

      expect(wrapper.find('[data-testid="update-check-btn"]').attributes('disabled')).toBeDefined()
      expect(wrapper.find('[data-testid="update-cancel-btn"]').exists()).toBe(true)
      expect(
        wrapper.find('[data-testid="update-cancel-btn"]').attributes('disabled'),
      ).toBeUndefined()
    })

    it('downloading 渲染：total 为 null 时只显示已下载', async () => {
      const fake = createFakeTauri({
        state: 'downloading',
        progress: { downloaded: 2097152, total: null },
      })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      const progressEl = wrapper.find('[data-testid="update-progress-bar"]')
      expect(progressEl.exists()).toBe(true)
      expect(progressEl.attributes('role')).toBe('progressbar')

      const progressText = wrapper.find('[data-testid="update-progress-text"]').text()
      expect(progressText).toContain('2 MB')
      expect(progressText).not.toContain('null')
      expect(progressText).not.toContain('/')
    })

    it('ready 渲染：已安装待重启', async () => {
      const fake = createFakeTauri({ state: 'ready' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toMatch(/待重启|已安装/)
      expect(wrapper.find('[data-testid="update-restart-btn"]').exists()).toBe(true)
      expect(
        wrapper.find('[data-testid="update-restart-btn"]').attributes('disabled'),
      ).toBeUndefined()
    })

    it('error 渲染：全部 8 个 error_code 映射到中文文案', async () => {
      const errorCodes: UpdateErrorCode[] = [
        'update_not_configured',
        'update_unsupported_dev',
        'update_busy',
        'update_check_failed',
        'update_download_failed',
        'update_signature_invalid',
        'update_install_failed',
        'update_cancelled',
      ]

      for (const code of errorCodes) {
        const fake = createFakeTauri({
          state: 'error',
          error_code: code,
        })
        const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
        await flushPromises()

        const expectedText = UPDATE_ERROR_MESSAGES[code]
        expect(wrapper.find('[data-testid="update-error-text"]').text()).toContain(expectedText)
        expect(updateErrorMessage(code)).toBe(expectedText)
      }
    })

    it('checked_at 渲染：显示上次检查本地时间', async () => {
      const fake = createFakeTauri({
        checked_at: 1761552000,
      })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      const checkedEl = wrapper.find('[data-testid="update-checked-at"]')
      expect(checkedEl.exists()).toBe(true)
      expect(checkedEl.text()).toContain('上次检查：')
      expect(checkedEl.text()).toMatch(/\d{4}-\d{2}-\d{2}/)
    })
  })

  describe('按钮可用性与操作调用', () => {
    it('点击“检查更新”调用 update_check', async () => {
      const fake = createFakeTauri({ state: 'idle' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      await wrapper.find('[data-testid="update-check-btn"]').trigger('click')
      await flushPromises()

      expect(fake.calls.some((c) => c.cmd === 'update_check')).toBe(true)
    })

    it('点击“下载并安装”调用 update_install（仅 available 时可用）', async () => {
      const fake = createFakeTauri({ state: 'available', available_version: '1.1.0' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      const installBtn = wrapper.find('[data-testid="update-install-btn"]')
      expect(installBtn.exists()).toBe(true)
      await installBtn.trigger('click')
      await flushPromises()

      expect(fake.calls.some((c) => c.cmd === 'update_install')).toBe(true)
    })

    it('点击“取消”调用 update_cancel（仅 checking / downloading 时可用）', async () => {
      const fake = createFakeTauri({ state: 'checking' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      const cancelBtn = wrapper.find('[data-testid="update-cancel-btn"]')
      expect(cancelBtn.exists()).toBe(true)
      await cancelBtn.trigger('click')
      await flushPromises()

      expect(fake.calls.some((c) => c.cmd === 'update_cancel')).toBe(true)
    })

    it('点击“重启以完成更新”需二次确认弹窗说明关闭后端并重启，确认后才调用 update_restart', async () => {
      const fake = createFakeTauri({ state: 'ready' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      // 初始无弹窗，未调用 update_restart
      expect(wrapper.find('[data-testid="update-restart-confirm-box"]').exists()).toBe(false)
      expect(fake.calls.some((c) => c.cmd === 'update_restart')).toBe(false)

      // 点击重启按钮弹出二次确认
      await wrapper.find('[data-testid="update-restart-btn"]').trigger('click')
      await flushPromises()

      const confirmBox = wrapper.find('[data-testid="update-restart-confirm-box"]')
      expect(confirmBox.exists()).toBe(true)
      expect(confirmBox.text()).toContain('关闭后端')
      expect(confirmBox.text()).toContain('重启')

      // 点击取消，弹窗关闭，未调用 restart
      await wrapper.find('[data-testid="update-restart-cancel-btn"]').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-testid="update-restart-confirm-box"]').exists()).toBe(false)
      expect(fake.calls.some((c) => c.cmd === 'update_restart')).toBe(false)

      // 再次打开并点击确认重启
      await wrapper.find('[data-testid="update-restart-btn"]').trigger('click')
      await flushPromises()
      await wrapper.find('[data-testid="update-restart-confirm-btn"]').trigger('click')
      await flushPromises()

      expect(fake.calls.some((c) => c.cmd === 'update_restart')).toBe(true)
    })
  })

  describe('事件驱动与响应式更新', () => {
    it('订阅 update://status 事件推送驱动界面状态更新', async () => {
      const fake = createFakeTauri({ state: 'idle' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toMatch(/空闲|就绪/)

      // 后端推送 available
      fake.emitStatus({
        state: 'available',
        available_version: '2.0.0',
        notes: '重大更新发布',
      })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toContain('发现新版本')
      expect(wrapper.find('[data-testid="update-available-version"]').text()).toContain('2.0.0')
      expect(wrapper.find('[data-testid="update-notes"]').text()).toContain('重大更新发布')

      // 后端推送 downloading
      fake.emitStatus({
        state: 'downloading',
        progress: { downloaded: 1048576, total: 2097152 },
      })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toContain('正在下载更新')
      expect(wrapper.find('[data-testid="update-progress-bar"]').attributes('aria-valuenow')).toBe(
        '50',
      )

      // 后端推送 ready
      fake.emitStatus({ state: 'ready' })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-state-text"]').text()).toMatch(/待重启|已安装/)
      expect(wrapper.find('[data-testid="update-restart-btn"]').exists()).toBe(true)
    })
  })

  describe('非 Tauri 环境降级', () => {
    it('非 Tauri 环境降级为 disabled，文案“仅桌面应用内可用”，且无未处理 rejection', async () => {
      delete (globalThis as Record<string, unknown>).__TAURI_INTERNALS__

      const wrapper = mount(UpdateCard, {
        props: {
          sources: {
            getTauriInvoke: () => null,
            getTauriListen: () => null,
          },
        },
      })
      await flushPromises()

      expect(wrapper.find('[data-testid="update-card"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="update-disabled-reason"]').text()).toContain(
        '仅桌面应用内可用',
      )

      // 所有按钮禁用
      const checkBtn = wrapper.find('[data-testid="update-check-btn"]')
      expect(checkBtn.attributes('disabled')).toBeDefined()
    })
  })

  describe('XSS 与安全防线', () => {
    it('notes 里的 <script> 和 HTML 被当作文本，不被执行或解析为 DOM 元素', async () => {
      const maliciousPayload =
        '<script id="xss-probe">window.__xss_flag = true</script><b id="html-probe">bold</b>'
      const fake = createFakeTauri({
        state: 'available',
        available_version: '1.0.1',
        notes: maliciousPayload,
      })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      // 不得解析出真实的 script 元素或 b 元素
      expect(wrapper.find('#xss-probe').exists()).toBe(false)
      expect(wrapper.find('#html-probe').exists()).toBe(false)
      expect((window as unknown as { __xss_flag?: boolean }).__xss_flag).toBeUndefined()

      // text 中保留原始字符字样
      const notesEl = wrapper.find('[data-testid="update-notes"]')
      expect(notesEl.text()).toContain('<script id="xss-probe">')
      expect(notesEl.text()).toContain('<b id="html-probe">bold</b>')
    })

    it('页面 DOM 中无 URL 输入框，无签名/endpoint 字样', async () => {
      const fake = createFakeTauri({ state: 'idle' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      // 不得出现任何 input 元素
      expect(wrapper.findAll('input')).toHaveLength(0)

      // 不得包含 endpoint 或敏感签名展示
      const html = wrapper.html()
      expect(html).not.toMatch(/endpoint/i)
      expect(html).not.toMatch(/https?:\/\//i)
      expect(html).not.toMatch(/updater_url|update_url/i)
    })
  })

  describe('可访问性与生命周期', () => {
    it('状态行包含 aria-live="polite"', async () => {
      const fake = createFakeTauri({ state: 'idle' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      const statusRegion = wrapper.find('[data-testid="update-status"]')
      expect(statusRegion.exists()).toBe(true)
      expect(statusRegion.attributes('aria-live')).toBe('polite')
    })

    it('卸载后取消订阅 update://status', async () => {
      const fake = createFakeTauri({ state: 'idle' })
      const wrapper = mount(UpdateCard, { props: { sources: fake.sources } })
      await flushPromises()

      expect(fake.listeners.length).toBeGreaterThan(0)
      wrapper.unmount()
      await flushPromises()

      expect(fake.unlisten).toHaveBeenCalled()
      expect(fake.listeners.length).toBe(0)
    })
  })
})
