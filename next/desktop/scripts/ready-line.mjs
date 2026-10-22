// 解析后端握手行：`TOOLBOX_READY {"v":1,"port":<int>,"token":"<str>","pid":<int>}`
const PREFIX = 'TOOLBOX_READY '

/** @param {string} line */
export function parseReadyLine(line) {
  const text = line.replace(/\r?\n$/, '')
  if (!text.startsWith(PREFIX)) return null
  let obj
  try {
    obj = JSON.parse(text.slice(PREFIX.length))
  } catch {
    return null
  }
  if (
    typeof obj !== 'object' ||
    obj === null ||
    obj.v !== 1 ||
    !Number.isInteger(obj.port) ||
    obj.port < 1 ||
    obj.port > 65535 ||
    typeof obj.token !== 'string' ||
    obj.token.length === 0 ||
    !Number.isInteger(obj.pid)
  ) {
    return null
  }
  return { port: obj.port, token: obj.token, pid: obj.pid }
}
