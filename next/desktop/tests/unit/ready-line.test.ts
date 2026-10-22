import { describe, expect, it } from 'vitest'
import { parseReadyLine } from '../../scripts/ready-line.mjs'

describe('dev-web READY 行解析', () => {
  it('合法行', () => {
    expect(parseReadyLine('TOOLBOX_READY {"v":1,"port":51000,"token":"t","pid":99}\n')).toEqual({
      port: 51000,
      token: 't',
      pid: 99,
    })
  })
  it('非法行返回 null', () => {
    for (const l of [
      '',
      'hello',
      'TOOLBOX_READY nope',
      'TOOLBOX_READY {"v":2,"port":1,"token":"t","pid":1}',
      'TOOLBOX_READY {"v":1,"port":0,"token":"t","pid":1}',
      'TOOLBOX_READY {"v":1,"port":1,"token":"","pid":1}',
      'TOOLBOX_READY {"v":1,"port":1,"token":"t"}',
    ]) {
      expect(parseReadyLine(l)).toBeNull()
    }
  })
})
