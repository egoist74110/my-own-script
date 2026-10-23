// S5-D 独立测试（测试员）：终端协议纯函数的故障与边界用例。
// 用例依据 next/backend/README.md「S5-A」终端 WS 与 WORK_PACKAGES「S5-D」推导，不复用施工者的 unit 用例。
import { describe, expect, it } from 'vitest'
import {
  createAttachFrame,
  createInputFrames,
  clampCols,
  clampRows,
  createResizeFrame,
  parseBinaryFrame,
} from '@/features/ai/terminal-protocol'

function frame(offset: bigint, payload: string | Uint8Array): Uint8Array {
  const body = typeof payload === 'string' ? new TextEncoder().encode(payload) : payload
  const out = new Uint8Array(8 + body.length)
  new DataView(out.buffer).setBigUint64(0, offset, false)
  out.set(body, 8)
  return out
}

const text = (b: Uint8Array | null | undefined) => (b ? new TextDecoder().decode(b) : null)

/** 把一串帧按到达顺序喂给解析器，返回实际写入终端的文本与最终水位。 */
function feed(frames: Uint8Array[], start = 0n) {
  let wm = start
  const written: string[] = []
  for (const f of frames) {
    const r = parseBinaryFrame(f, wm)
    wm = r.nextWatermark
    if (r.payload && r.payload.length > 0) written.push(text(r.payload)!)
  }
  return { written: written.join(''), watermark: wm }
}

describe('S5-D 独立：二进制输出帧解析（offset 去重与截取）', () => {
  it('长度不足 8 字节的帧不写入且不推进水位', () => {
    for (const len of [0, 1, 7]) {
      const r = parseBinaryFrame(new Uint8Array(len), 42n)
      expect(r.payload).toBeNull()
      expect(r.nextWatermark).toBe(42n)
    }
  })

  it('只有 8 字节 offset 的帧（0 长度负载）：不写入；水位只前进不后退', () => {
    const ahead = parseBinaryFrame(frame(10n, ''), 5n)
    expect(ahead.payload).toBeNull()
    expect(ahead.nextWatermark).toBe(10n)
    const behind = parseBinaryFrame(frame(3n, ''), 5n)
    expect(behind.payload).toBeNull()
    expect(behind.nextWatermark).toBe(5n)
  })

  it('offset 与水位相等：整段写入，水位推进到末尾', () => {
    const r = parseBinaryFrame(frame(7n, 'abc'), 7n)
    expect(text(r.payload)).toBe('abc')
    expect(r.nextWatermark).toBe(10n)
  })

  it('完全重复（已完整接收过的段）：不写入、水位不变', () => {
    const r = parseBinaryFrame(frame(0n, 'hello'), 5n)
    expect(r.payload).toBeNull()
    expect(r.nextWatermark).toBe(5n)
  })

  it('与已收区间部分重叠：只写入未消费的后半段', () => {
    // 已收 [0,5)；帧覆盖 [3,9)，应只写 [5,9) 即 "cdef"（帧内容 "abcdef"）
    const r = parseBinaryFrame(frame(3n, 'abcdef'), 5n)
    expect(text(r.payload)).toBe('cdef')
    expect(r.nextWatermark).toBe(9n)
  })

  it('offset 跳跃（服务端从保留起点返回）：接受并写入，水位跟随', () => {
    // 环形缓冲已丢弃 [0,100)，服务端从 100 开始回放
    const r = parseBinaryFrame(frame(100n, 'tail'), 0n)
    expect(text(r.payload)).toBe('tail')
    expect(r.nextWatermark).toBe(104n)
  })

  it('乱序到达：迟到的旧帧不会被二次写入（不产生重复字节）', () => {
    const early = frame(10n, 'JKLMN') // [10,15)
    const late = frame(0n, '0123456789') // [0,10)，迟到
    const { written, watermark } = feed([early, late, frame(15n, 'OPQ')])
    // 迟到段被整段视为已消费（水位已到 15）：不写入，也不重复
    expect(written).toBe('JKLMNOPQ')
    expect(watermark).toBe(18n)
    expect(written.split('J').length - 1).toBe(1)
  })

  it('同一字节在多次重放中绝不写入两次（断线后服务端从更早 offset 重放）', () => {
    // 第三、四帧与已收内容重叠：第四帧 [8,12) 中 [8,10) 已收，只应追加 "d!"
    const frames = [frame(0n, 'hello'), frame(5n, 'world'), frame(0n, 'hello'), frame(8n, 'rld!')]
    const { written, watermark } = feed(frames)
    expect(written).toBe('helloworldd!')
    expect(watermark).toBe(12n)
  })

  it('超大 offset（接近 uint64 上限）：水位使用 BigInt 精确推进，不溢出', () => {
    const max = 2n ** 64n - 1n
    const r = parseBinaryFrame(frame(max - 2n, 'xyz'), max - 2n)
    expect(text(r.payload)).toBe('xyz')
    expect(r.nextWatermark).toBe(max + 1n)
  })

  it('接受 Uint8Array 视图（带 byteOffset 的 subarray）时按视图解析', () => {
    const big = new Uint8Array(40)
    big.set(frame(2n, 'AB'), 5)
    const view = big.subarray(5, 5 + 10)
    const r = parseBinaryFrame(view, 2n)
    expect(text(r.payload)).toBe('AB')
    expect(r.nextWatermark).toBe(4n)
  })

  it('ArrayBuffer 输入与 Uint8Array 输入结果一致', () => {
    const f = frame(0n, 'same')
    const a = parseBinaryFrame(f.buffer.slice(0) as ArrayBuffer, 0n)
    const b = parseBinaryFrame(f, 0n)
    expect(text(a.payload)).toBe(text(b.payload))
    expect(a.nextWatermark).toBe(b.nextWatermark)
  })
})

describe('S5-D 独立：attach 水位与断线续接', () => {
  it('断线重连的 after_offset 等于已写入末尾（不是 0，也不是多加一）', () => {
    const { watermark } = feed([frame(0n, 'abc'), frame(3n, 'defg')])
    expect(JSON.parse(createAttachFrame(watermark))).toEqual({ type: 'attach', after_offset: 7 })
  })

  it('attach 帧的 after_offset 为普通 JSON 整数，不带小数', () => {
    expect(createAttachFrame(0n)).toBe('{"type":"attach","after_offset":0}')
    expect(createAttachFrame(12)).toBe('{"type":"attach","after_offset":12}')
  })

  it('超过 2^53 的水位不得被四舍五入（后端按精确整数读取 after_offset）', () => {
    // 已知缺陷候选：createAttachFrame 使用 Number(...)，2^53+1 会丢失 1
    const exact = 2n ** 53n + 1n
    expect(createAttachFrame(exact)).toBe(`{"type":"attach","after_offset":${exact.toString()}}`)
  })
})

describe('S5-D 独立：输入分片（解码 ≤16 KiB）', () => {
  const decodeFrames = (frames: string[]): Uint8Array => {
    const parts = frames.map((f) => {
      const obj = JSON.parse(f) as { type: string; data: string }
      expect(obj.type).toBe('input')
      return Buffer.from(obj.data, 'base64')
    })
    const total = parts.reduce((n, p) => n + p.length, 0)
    const out = new Uint8Array(total)
    let at = 0
    for (const p of parts) {
      out.set(p, at)
      at += p.length
    }
    return out
  }

  it('恰好 16 KiB：单帧，解码长度 16384', () => {
    const frames = createInputFrames('a'.repeat(16384))
    expect(frames).toHaveLength(1)
    expect(Buffer.from((JSON.parse(frames[0]!) as { data: string }).data, 'base64').length).toBe(
      16384,
    )
  })

  it('16 KiB + 1 字节：拆成两帧，每帧解码 ≤16384，拼接后等于原文', () => {
    const src = 'b'.repeat(16385)
    const frames = createInputFrames(src)
    expect(frames).toHaveLength(2)
    for (const f of frames) {
      const len = Buffer.from((JSON.parse(f) as { data: string }).data, 'base64').length
      expect(len).toBeLessThanOrEqual(16384)
    }
    expect(new TextDecoder().decode(decodeFrames(frames))).toBe(src)
  })

  it('多字节 UTF-8 字符跨分片边界：拼接解码后与原文一致（无乱码）', () => {
    // 中文字符 3 字节；16384 % 3 == 1，边界必然切在字符中间
    const src = '中'.repeat(6000)
    const frames = createInputFrames(src)
    expect(frames.length).toBeGreaterThan(1)
    expect(new TextDecoder('utf-8', { fatal: true }).decode(decodeFrames(frames))).toBe(src)
  })

  it('4 字节 emoji 跨边界：拼接后原文一致', () => {
    const src = '😀'.repeat(5000) // 4 字节一个，边界切在码点中间的组合也要覆盖
    const frames = createInputFrames(src, 16384)
    const bytes = decodeFrames(frames)
    expect(new TextDecoder('utf-8', { fatal: true }).decode(bytes)).toBe(src)
    for (const f of frames) {
      expect(
        Buffer.from((JSON.parse(f) as { data: string }).data, 'base64').length,
      ).toBeLessThanOrEqual(16384)
    }
  })

  it('大于 16 KiB 的混合字符串：每帧都不超限且拼接等于原文', () => {
    const src = `${'x'.repeat(16383)}中${'y'.repeat(20000)}😀`
    const frames = createInputFrames(src)
    for (const f of frames) {
      expect(
        Buffer.from((JSON.parse(f) as { data: string }).data, 'base64').length,
      ).toBeLessThanOrEqual(16384)
    }
    expect(new TextDecoder('utf-8', { fatal: true }).decode(decodeFrames(frames))).toBe(src)
  })

  it('空输入：不产生非法帧（拼接解码结果为空）', () => {
    const frames = createInputFrames('')
    expect(new TextDecoder().decode(decodeFrames(frames))).toBe('')
  })
})

describe('S5-D 独立：resize 夹取', () => {
  it('rows 边界：4→5，5→5，300→300，301→300，0 与负数→5', () => {
    expect(clampRows(4)).toBe(5)
    expect(clampRows(5)).toBe(5)
    expect(clampRows(300)).toBe(300)
    expect(clampRows(301)).toBe(300)
    expect(clampRows(0)).toBe(5)
    expect(clampRows(-1)).toBe(5)
    expect(clampRows(-100000)).toBe(5)
  })

  it('cols 边界：19→20，20→20，500→500，501→500', () => {
    expect(clampCols(19)).toBe(20)
    expect(clampCols(20)).toBe(20)
    expect(clampCols(500)).toBe(500)
    expect(clampCols(501)).toBe(500)
    expect(clampCols(0)).toBe(20)
    expect(clampCols(-7)).toBe(20)
  })

  it('NaN 夹取到合法区间内（不发出越界值）', () => {
    const r = clampRows(Number.NaN)
    const c = clampCols(Number.NaN)
    expect(r).toBeGreaterThanOrEqual(5)
    expect(r).toBeLessThanOrEqual(300)
    expect(c).toBeGreaterThanOrEqual(20)
    expect(c).toBeLessThanOrEqual(500)
  })

  it('极大值 1e9 夹到上限', () => {
    expect(clampRows(1e9)).toBe(300)
    expect(clampCols(1e9)).toBe(500)
  })

  it('+Infinity 夹到上限（极大值的一种）', () => {
    // 已知缺陷候选：clampRows 对非有限数回落到默认 24，而不是上限 300
    expect(clampRows(Number.POSITIVE_INFINITY)).toBe(300)
    expect(clampCols(Number.POSITIVE_INFINITY)).toBe(500)
  })

  it('-Infinity 夹到下限', () => {
    // 已知缺陷候选：-Infinity 同样回落到默认值而不是下限 5 / 20
    expect(clampRows(Number.NEGATIVE_INFINITY)).toBe(5)
    expect(clampCols(Number.NEGATIVE_INFINITY)).toBe(20)
  })

  it('小数向下取整后再夹取', () => {
    expect(clampRows(24.9)).toBe(24)
    expect(clampCols(80.2)).toBe(80)
  })

  it('resize 帧使用夹取后的值', () => {
    expect(JSON.parse(createResizeFrame(1e9, -1e9))).toEqual({
      type: 'resize',
      rows: 300,
      cols: 20,
    })
  })
})
