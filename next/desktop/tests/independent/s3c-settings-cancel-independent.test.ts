import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { boot } from '../unit/boot'
import { createFake } from '../unit/settings-fake'
import { FakeSocket, hello, resetSeq } from '../unit/helpers'
import type { components } from '@/api/schema'

const pressEscape = () =>
  window.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
  )

beforeEach(() => {
  FakeSocket.reset()
  resetSeq()
  localStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('S3-C 独立设置 Sheet 取消行为', () => {
  it('library 与本地仓库删除都先经过 Sheet；Esc 后均不调用 DELETE', async () => {
    const fake = createFake()
    const repo: components['schemas']['LocalRepoView'] = {
      id: 'repo:a',
      name: '测试仓库',
      path: '/tmp/repo',
      exists: true,
      warnings: [],
    }
    fake.state.ado.local_repos = [repo]
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()

    const adoTab = b.wrapper.findAll('[role="tab"]').find((tab) => tab.text().startsWith('ADO'))
    expect(adoTab).toBeTruthy()
    await adoTab!.trigger('mousedown')
    await flushPromises()
    await b.wrapper.get('[data-testid="library-row-lib:b"]').trigger('click')
    await flushPromises()
    await b.wrapper.get('[data-testid="library-delete"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-testid="sheet"]')).not.toBeNull()
    pressEscape()
    await flushPromises()
    expect(document.querySelector('[data-testid="sheet"]')).toBeNull()
    expect(fake.calls.filter((call) => call.method === 'DELETE')).toHaveLength(0)

    const repoTab = b.wrapper
      .findAll('[role="tab"]')
      .find((tab) => tab.text().startsWith('本地仓库'))
    expect(repoTab).toBeTruthy()
    await repoTab!.trigger('mousedown')
    await flushPromises()
    await b.wrapper.get('[data-testid="repo-row-repo:a"]').trigger('click')
    await flushPromises()
    await b.wrapper.get('[data-testid="repo-delete"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-testid="sheet"]')).not.toBeNull()
    pressEscape()
    await flushPromises()
    expect(document.querySelector('[data-testid="sheet"]')).toBeNull()
    expect(fake.calls.filter((call) => call.method === 'DELETE')).toHaveLength(0)
    await b.done()
  })

  it('项目删除确认把焦点放入 Sheet；Esc 关闭后不调用删除接口', async () => {
    const fake = createFake()
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    const adoTab = b.wrapper.findAll('[role="tab"]').find((tab) => tab.text().startsWith('ADO'))
    expect(adoTab).toBeTruthy()
    await adoTab!.trigger('mousedown')
    await flushPromises()
    await b.wrapper.get('[data-testid="project-row-proj:a"]').trigger('click')
    await flushPromises()
    await b.wrapper.get('[data-testid="project-delete"]').trigger('click')
    await flushPromises()

    const sheet = document.querySelector('[data-testid="sheet"]')
    expect(sheet).not.toBeNull()
    expect(sheet?.contains(document.activeElement)).toBe(true)
    pressEscape()
    await flushPromises()
    expect(document.querySelector('[data-testid="sheet"]')).toBeNull()
    expect(fake.to('DELETE', '/api/ado/projects/proj:a')).toHaveLength(0)
    await b.done()
  })

  it('导入执行确认用 Sheet；Esc 关闭后不会调用 import execute', async () => {
    const fake = createFake()
    const b = await boot({ path: '/settings', fetchImpl: fake.fetch })
    b.sock.emit(hello())
    await flushPromises()
    await b.wrapper.get('[data-testid="import-preview"]').trigger('click')
    await flushPromises()
    await b.wrapper.get('[data-testid="import-confirm"]').trigger('click')
    await flushPromises()

    const sheet = document.querySelector('[data-testid="sheet"]')
    expect(sheet).not.toBeNull()
    expect(sheet?.contains(document.activeElement)).toBe(true)
    pressEscape()
    await flushPromises()
    expect(document.querySelector('[data-testid="sheet"]')).toBeNull()
    expect(fake.to('POST', '/api/settings/import/execute')).toHaveLength(0)
    await b.done()
  })
})
