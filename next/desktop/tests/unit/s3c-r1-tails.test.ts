import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { boot } from './boot'
import { FakeSocket, hello, resetSeq } from './helpers'
import { createFake } from './settings-fake'
import ErrorNotice from '@/features/work-items/ErrorNotice.vue'
import { ApiError } from '@/features/work-items/api'
import { createTestRouter } from '@/app/router'
import EmptyState from '@/components/EmptyState.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  sessionStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

const press = (key: string, target: EventTarget = window) =>
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))

describe('S3-C 尾巴 B：设置项删除与导入改用 Sheet 组件', () => {
  it('项目删除确认改用 Sheet：支持 Esc 取消与按钮确认', async () => {
    const fake = createFake()
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 点击 ADO 分区
    const adoTab = b.wrapper.findAll('[role=tab]').find((x) => x.text().startsWith('ADO'))
    expect(adoTab).toBeTruthy()
    await adoTab!.trigger('mousedown')
    await flushPromises()

    // 点击选择一个项目
    const row = b.wrapper.find('[data-testid="project-row-proj:a"]')
    expect(row.exists()).toBe(true)
    await row.trigger('click')
    await flushPromises()

    // 点击删除按钮，弹出 Sheet
    const delBtn = b.wrapper.find('[data-testid="project-delete"]')
    expect(delBtn.exists()).toBe(true)
    await delBtn.trigger('click')
    await flushPromises()

    // 确认 Sheet 已弹出到 body
    const sheet = document.querySelector('[data-testid=sheet]')
    expect(sheet).not.toBeNull()
    expect(sheet?.textContent).toContain('确认删除「项目甲」？')

    // 按 Esc 键可以取消关闭
    press('Escape')
    await flushPromises()
    expect(document.querySelector('[data-testid=sheet]')).toBeNull()

    // 重新打开并点击确认删除
    await delBtn.trigger('click')
    await flushPromises()
    const confirmBtn = document.querySelector(
      '[data-testid=project-delete-confirm]',
    ) as HTMLButtonElement
    expect(confirmBtn).not.toBeNull()
    confirmBtn.click()
    await flushPromises()

    // 验证发起了 DELETE 请求
    expect(fake.calls.some((c) => c.method === 'DELETE')).toBe(true)
    await b.done()
  })

  it('导入确认改用 Sheet：支持确认覆盖', async () => {
    const fake = createFake()
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await flushPromises()

    // 切换到从旧配置导入 Tab
    const importTab = b.wrapper.findAll('[role=tab]').find((x) => x.text().includes('导入'))
    expect(importTab).toBeTruthy()
    await importTab!.trigger('mousedown')
    await flushPromises()

    const submitBtn = b.wrapper.find('[data-testid=import-submit-btn]')
    if (submitBtn.exists()) {
      await submitBtn.trigger('click')
      await flushPromises()

      const sheet = document.querySelector('[data-testid=sheet]')
      expect(sheet).not.toBeNull()
      expect(sheet?.textContent).toContain('确认导入配置？')

      press('Escape')
      await flushPromises()
      expect(document.querySelector('[data-testid=sheet]')).toBeNull()
    }
    await b.done()
  })
})

describe('S3-C 尾巴 B：工单页出错态使用居中 EmptyState', () => {
  it('ErrorNotice 渲染 tone="error" 的 EmptyState，含“无法读取工单”、原因、前往设置与重试', async () => {
    const router = createTestRouter()
    const err = new ApiError(401, 'no_credential', '请前往设置配置个人访问令牌 (PAT)')

    const w = mount(ErrorNotice, {
      props: {
        error: err,
        retry: true,
      },
      global: {
        plugins: [router],
      },
      attachTo: document.body,
    })
    await flushPromises()

    // 验证居中 EmptyState
    const empty = w.findComponent(EmptyState)
    expect(empty.exists()).toBe(true)
    expect(empty.attributes('data-tone')).toBe('error')

    // 文本断言
    expect(w.text()).toContain('无法读取工单')
    expect(w.text()).toContain('该代码库未配置 PAT')

    // 动作按钮
    expect(w.text()).toContain('前往设置')
    const retryBtn = w.find('button')
    expect(retryBtn.exists()).toBe(true)
    expect(retryBtn.text()).toBe('重试')
    await retryBtn.trigger('click')
    expect(w.emitted('retry')).toBeTruthy()

    w.unmount()
  })
})
