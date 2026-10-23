// S5-D：终端 WebSocket 纯函数协议与帧解析单测
import { describe, expect, it } from 'vitest'
import {
  AI_ERROR_MESSAGES,
  clampCols,
  clampRows,
  createAttachFrame,
  createAuthFrame,
  createInputFrames,
  createResizeFrame,
  formatEndedReason,
  formatSessionState,
  parseBinaryFrame,
} from '@/features/ai/terminal-protocol'

describe('S5-D 终端协议纯函数 (terminal-protocol)', () => {
  describe('createAuthFrame & createAttachFrame', () => {
    it('生成符合契约的 auth 帧', () => {
      const frame = createAuthFrame('test-secret-token')
      expect(JSON.parse(frame)).toEqual({
        type: 'auth',
        token: 'test-secret-token',
      })
    })

    it('生成符合契约的 attach 帧，包含 after_offset', () => {
      const frame0 = createAttachFrame(0)
      expect(JSON.parse(frame0)).toEqual({
        type: 'attach',
        after_offset: 0,
      })

      const frameBig = createAttachFrame(1024n)
      expect(JSON.parse(frameBig)).toEqual({
        type: 'attach',
        after_offset: 1024,
      })
    })

    it('S5D-T09 回归：超过 2^53 的 BigInt 水位精确传递，不因 Number 转换丢失精度', () => {
      const bigExact = 2n ** 53n + 1n
      const frame = createAttachFrame(bigExact)
      expect(frame).toBe(`{"type":"attach","after_offset":${bigExact.toString()}}`)
    })
  })

  describe('createInputFrames 输入分片 (<= 16 KiB)', () => {
    it('空字符串输入生成单个空数据帧', () => {
      const frames = createInputFrames('')
      expect(frames).toHaveLength(1)
      expect(JSON.parse(frames[0]!)).toEqual({ type: 'input', data: '' })
    })

    it('普通短字符串输入生成单帧且 base64 正确', () => {
      const text = 'ls -la\n'
      const frames = createInputFrames(text)
      expect(frames).toHaveLength(1)
      const parsed = JSON.parse(frames[0]!)
      expect(parsed.type).toBe('input')
      const decoded = Buffer.from(parsed.data, 'base64').toString('utf-8')
      expect(decoded).toBe(text)
    })

    it('超过 16 KiB (16384 字节) 的大量输入分片且每片 <= 16 KiB', () => {
      // 创建 40,000 字节的字符串
      const largeText = 'A'.repeat(40_000)
      const frames = createInputFrames(largeText)
      // 40000 / 16384 = 2 满帧 (16384) + 1 尾帧 (7232)
      expect(frames).toHaveLength(3)

      let reassembled = ''
      for (const f of frames) {
        const parsed = JSON.parse(f)
        expect(parsed.type).toBe('input')
        const buf = Buffer.from(parsed.data, 'base64')
        expect(buf.length).toBeLessThanOrEqual(16384)
        reassembled += buf.toString('utf-8')
      }
      expect(reassembled).toBe(largeText)
    })

    it('多字节 UTF-8 中文字符分片完整还原', () => {
      const chineseText = '你好，世界！'.repeat(3000) // ~54,000 字节
      const frames = createInputFrames(chineseText)
      expect(frames.length).toBeGreaterThan(1)

      const chunks: Buffer[] = []
      for (const f of frames) {
        const parsed = JSON.parse(f)
        const buf = Buffer.from(parsed.data, 'base64')
        expect(buf.length).toBeLessThanOrEqual(16384)
        chunks.push(buf)
      }
      const combined = Buffer.concat(chunks).toString('utf-8')
      expect(combined).toBe(chineseText)
    })
  })

  describe('clampRows & clampCols 终端尺寸夹取', () => {
    it('clampRows 限制在 5..300 之间', () => {
      expect(clampRows(0)).toBe(5)
      expect(clampRows(4)).toBe(5)
      expect(clampRows(5)).toBe(5)
      expect(clampRows(24)).toBe(24)
      expect(clampRows(300)).toBe(300)
      expect(clampRows(301)).toBe(300)
      expect(clampRows(9999)).toBe(300)
      expect(clampRows(NaN)).toBe(24)
      expect(clampRows(Number.POSITIVE_INFINITY)).toBe(300)
      expect(clampRows(Number.NEGATIVE_INFINITY)).toBe(5)
      expect(clampRows(24.8)).toBe(24)
    })

    it('clampCols 限制在 20..500 之间', () => {
      expect(clampCols(0)).toBe(20)
      expect(clampCols(19)).toBe(20)
      expect(clampCols(20)).toBe(20)
      expect(clampCols(80)).toBe(80)
      expect(clampCols(500)).toBe(500)
      expect(clampCols(501)).toBe(500)
      expect(clampCols(9999)).toBe(500)
      expect(clampCols(NaN)).toBe(80)
      expect(clampCols(Number.POSITIVE_INFINITY)).toBe(500)
      expect(clampCols(Number.NEGATIVE_INFINITY)).toBe(20)
      expect(clampCols(80.9)).toBe(80)
    })

    it('createResizeFrame 生成带有夹取后的 rows/cols 帧', () => {
      const frame = createResizeFrame(1, 1000)
      expect(JSON.parse(frame)).toEqual({
        type: 'resize',
        rows: 5,
        cols: 500,
      })
    })
  })

  describe('parseBinaryFrame 二进制帧解析与 offset 去重/续接', () => {
    function makeFrame(offset: bigint, text: string): Uint8Array {
      const textBytes = new TextEncoder().encode(text)
      const buffer = new Uint8Array(8 + textBytes.length)
      const view = new DataView(buffer.buffer)
      view.setBigUint64(0, offset, false) // 大端
      buffer.set(textBytes, 8)
      return buffer
    }

    it('帧长度不足 8 字节时返回 null payload 并保持当前水位', () => {
      const shortBuffer = new Uint8Array([1, 2, 3, 4])
      const res = parseBinaryFrame(shortBuffer, 100n)
      expect(res.payload).toBeNull()
      expect(res.nextWatermark).toBe(100n)
    })

    it('正好 8 字节空负载帧正确解析 offset', () => {
      const emptyFrame = new Uint8Array(8)
      new DataView(emptyFrame.buffer).setBigUint64(0, 50n, false)
      const res = parseBinaryFrame(emptyFrame, 20n)
      expect(res.offset).toBe(50n)
      expect(res.payload).toBeNull()
      expect(res.nextWatermark).toBe(50n)
    })

    it('正常单帧完整接收并推进水位', () => {
      const frame = makeFrame(0n, 'Hello Terminal')
      const res = parseBinaryFrame(frame, 0n)
      expect(res.offset).toBe(0n)
      expect(res.payload).not.toBeNull()
      expect(new TextDecoder().decode(res.payload!)).toBe('Hello Terminal')
      expect(res.nextWatermark).toBe(14n)
    })

    it('完全重复的数据帧 (frameEnd <= watermark) 完全去重丢弃', () => {
      // 假设当前水位已达 20n，收到 offset=0n, 长度=14n 的旧帧
      const duplicateFrame = makeFrame(0n, 'Hello Terminal')
      const res = parseBinaryFrame(duplicateFrame, 20n)
      expect(res.offset).toBe(0n)
      expect(res.payload).toBeNull()
      expect(res.nextWatermark).toBe(20n)
    })

    it('部分重叠的数据帧截取未消费的尾部并推进水位', () => {
      // 假设当前水位已达 10n，收到 offset=5n, 长度=10n ("0123456789") 的帧
      // 该帧覆盖 [5, 15)，其中 [5, 10) 已收，[10, 15) 为新数据 ("56789")
      const overlappingFrame = makeFrame(5n, '0123456789')
      const res = parseBinaryFrame(overlappingFrame, 10n)
      expect(res.offset).toBe(5n)
      expect(res.payload).not.toBeNull()
      expect(new TextDecoder().decode(res.payload!)).toBe('56789')
      expect(res.nextWatermark).toBe(15n)
    })

    it('支持 ArrayBuffer 与 Uint8Array 两种输入格式', () => {
      const frame = makeFrame(100n, 'ArrayBufferTest')
      const resFromArrayBuffer = parseBinaryFrame(frame.buffer as ArrayBuffer, 100n)
      expect(resFromArrayBuffer.payload).not.toBeNull()
      expect(new TextDecoder().decode(resFromArrayBuffer.payload!)).toBe('ArrayBufferTest')

      const resFromUint8 = parseBinaryFrame(frame, 100n)
      expect(resFromUint8.payload).not.toBeNull()
      expect(new TextDecoder().decode(resFromUint8.payload!)).toBe('ArrayBufferTest')
    })
  })

  describe('formatSessionState & formatEndedReason & AI_ERROR_MESSAGES', () => {
    it('状态与结束原因中文映射正确', () => {
      expect(formatSessionState('starting')).toBe('启动中')
      expect(formatSessionState('idle')).toBe('空闲')
      expect(formatSessionState('busy')).toBe('运行中')
      expect(formatSessionState('awaiting_approval')).toBe('待审批')
      expect(formatSessionState('closing')).toBe('关闭中')
      expect(formatSessionState('ended')).toBe('已结束')
      expect(formatSessionState('failed')).toBe('失败')
      expect(formatSessionState('unknown_state')).toBe('unknown_state')

      expect(formatEndedReason('user_closed')).toBe('用户关闭')
      expect(formatEndedReason('process_exited')).toBe('进程退出')
      expect(formatEndedReason('interrupted_on_exit')).toBe('退出时中断')
      expect(formatEndedReason('backend_restart')).toBe('后端重启')
      expect(formatEndedReason('start_failed')).toBe('启动失败')
      expect(formatEndedReason('limit')).toBe('超出限额')
      expect(formatEndedReason(null)).toBe('无')
    })

    it('错误码中文映射覆盖所有常见 409 与 503 码', () => {
      expect(AI_ERROR_MESSAGES['ai_session_limit']).toContain('上限')
      expect(AI_ERROR_MESSAGES['cli_not_found']).toContain('未找到')
      expect(AI_ERROR_MESSAGES['repo_missing']).toContain('本地仓库')
      expect(AI_ERROR_MESSAGES['unsupported_cli']).toContain('不支持')
      expect(AI_ERROR_MESSAGES['high_risk_ack_required']).toContain('高权限')
      expect(AI_ERROR_MESSAGES['ai_store_unavailable']).toContain('不可用')
    })
  })
})
