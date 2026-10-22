import { flushPromises } from '@vue/test-utils'
import { expect, vi } from 'vitest'
import { boot } from './boot'
import { hello } from './helpers'
import { summary, type WiFake } from './wi-fake'

export async function openWi(fake: WiFake) {
  const b = await boot({ path: '/work-items', fetchImpl: fake.fetch })
  b.sock.emit(hello())
  for (let i = 0; i < 4; i++) await flushPromises()
  return b
}
export type WiBoot = Awaited<ReturnType<typeof openWi>>

export const rowIds = (b: WiBoot) =>
  b.wrapper
    .findAll('[data-testid^=wi-row-]')
    .map((r) => Number(r.attributes('data-testid')!.slice(7)))

export async function settle(n = 4) {
  for (let i = 0; i < n; i++) await flushPromises()
}

export async function clickTab(b: WiBoot, tablist: string, label: string) {
  const t = b.wrapper
    .get(`[role=tablist][aria-label="${tablist}"]`)
    .findAll('[role=tab]')
    .find((x) => x.text().startsWith(label))
  expect(t, `tab ${label}`).toBeTruthy()
  await t!.trigger('mousedown', { button: 0 })
  await settle()
}

export async function openRow(b: WiBoot, id: number) {
  await b.wrapper.get(`[data-testid=wi-row-${id}]`).trigger('click')
  await settle()
}

/** 安装假的 URL.createObjectURL / revokeObjectURL（jsdom 没有）。 */
export function stubObjectUrls() {
  let n = 0
  const create = vi.fn(() => `blob:fake/${++n}`)
  const revoke = vi.fn()
  Object.defineProperty(URL, 'createObjectURL', {
    value: create,
    configurable: true,
    writable: true,
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    value: revoke,
    configurable: true,
    writable: true,
  })
  return {
    create,
    revoke,
    restore() {
      delete (URL as unknown as Record<string, unknown>).createObjectURL
      delete (URL as unknown as Record<string, unknown>).revokeObjectURL
    },
  }
}

export const manyItems = (n: number) =>
  Array.from({ length: n }, (_, i) =>
    summary(1000 + i, { assigned_to: i % 2 ? '示例甲' : null, title: `批量 ${i}` }),
  )
