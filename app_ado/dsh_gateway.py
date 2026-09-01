"""dsh web 的 Basic Auth 网关（纯标准库，独立常驻进程）。

dsh web 本身没有密码登录。本网关在 dsh 前面加一道认证，把请求透传到上游。

关键前提（实测 dsh 前端 `dsh-client-connection/lib/client.js`）：
  dsh web 有两类请求：
    - `/api/events.mux`、`/api/events.host` 是 **WebSocket**（客户端 `doFetch` 对 GET 走
      `new WebSocket`，dsh 对非升级请求回 `426 Upgrade Required`）；
    - `/api/host.describe`、`/api/workspace.list` 等 unary 是 **fetch POST**（`callUnary`）。
  浏览器开 WebSocket **发不了 Authorization 头**（Chrome 也不把 Basic Auth 凭据带到 WS 上），
  而且**手机浏览器常常不把原生日志框的 Basic Auth 缓存到同源 XHR/fetch**（桌面 Chrome 会、
  手机常不会）——于是 WS 和 unary POST 都可能缺认证 → UI 就绪失败（要求 `host.describe` 成功
  + 两条流打开）→ 界面空白。

为什么必须用 cookie：
  **同源 cookie 是浏览器一定会带的**——同源 fetch 默认 `credentials:'same-origin'` 会带，
  同源 WebSocket 握手也会带。所以网关在 Basic Auth（页面那次）通过时下发一个 cookie
  （`dsh_auth`），之后 WS 握手 + 同源 fetch 自动带它过认证，手机也稳。Cloudflare 只挡
  「带 Authorization 头的 WS 升级」，而这里 WS 带的是同源 cookie（浏览器行为），不是
  Authorization 头，正常放行。

认证规则：
  - WebSocket（events.mux/host）→ 只认 `Cookie: dsh_auth=<token>`（WS 带不了 Authorization）；
  - 普通 HTTP → `Authorization: Basic <user>:<key>` 正确（**下发** cookie）或有效 cookie；
  - 都不满足 → `401 + WWW-Authenticate: Basic`，浏览器弹原生日志框。

cookie token = HMAC(本进程随机 secret, "dsh-auth")。secret 每次进程启动随机生成，
所以 cookie **不含 key**、且网关重启后旧 cookie 自动失效（用户重新输一次 key 即可）。

由 app_ado/services_panel.py 的 dsh_start() 经 `_spawn_detached` 拉起，
密钥经 --key 参数传入（不落盘）。用法：

    python app_ado/dsh_gateway.py --listen 0.0.0.0:3081 \
        --upstream 127.0.0.1:3080 --key <key>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import socket
import socketserver
import sys
import threading

REALM = "dsh"
COOKIE_NAME = "dsh_auth"
_MAX_HEAD = 1 << 20  # 1MB，够装下任何正常请求头/响应头
_MAX_BODY = 8 << 20  # 8MB，dsh web 的 unary POST 都很小；SSE GET 无 body


def _split(hostport: str) -> tuple[str, int]:
    host, _, port = hostport.rpartition(":")
    return (host or "127.0.0.1", int(port))


def _auth_ok(header: bytes | None, key: str) -> bool:
    if not header or not header.startswith(b"Basic "):
        return False
    try:
        decoded = base64.b64decode(header[len("Basic "):]).decode("utf-8", "replace")
    except Exception:
        return False
    # user 任意（浏览器会填什么算什么），只认密码部分 = key
    pw = decoded.rsplit(":", 1)[-1]
    return hmac.compare_digest(pw, key)


def _cookie_token(secret: bytes) -> bytes:
    """本进程的会话 token（不含 key）：HMAC(secret, 'dsh-auth')。"""
    return hmac.new(secret, b"dsh-auth", hashlib.sha256).hexdigest().encode()


def _cookie_ok(head: bytes, secret: bytes) -> bool:
    """请求头里是否带了有效的 `dsh_auth` cookie。"""
    for line in head.split(b"\r\n"):
        low = line.lower()
        if low.startswith(b"cookie:"):
            val = line.split(b":", 1)[1].strip()
            for part in val.split(b";"):
                part = part.strip()
                if part.startswith(COOKIE_NAME.encode() + b"="):
                    return hmac.compare_digest(part[len(COOKIE_NAME) + 1:], _cookie_token(secret))
    return False


def _head_value(head: bytes, name: bytes) -> bytes | None:
    """从请求头取某字段的值（大小写不敏感），取不到返回 None。"""
    for line in head.split(b"\r\n"):
        if line.lower().startswith(name + b":"):
            return line.split(b":", 1)[1].strip()
    return None


def _is_ws_upgrade(head: bytes) -> bool:
    """请求头是否要求 WebSocket 升级（Upgrade: websocket）。

    dsh web 的 `/api/events.mux`、`/api/events.host` 就是 WebSocket（客户端 `doFetch`
    对 GET 走 `new WebSocket`），dsh 对非升级请求回 426。浏览器 WS 握手带不了
    Authorization 头，但**会带同源 cookie**，所以 WS 分支只认 cookie。
    """
    for line in head.split(b"\r\n"):
        low = line.lower()
        if low.startswith(b"upgrade:") and b"websocket" in low:
            return True
    return False


def _rewrite_for_upstream(head: bytes, upstream: tuple[str, int]) -> bytes:
    """转发前改写请求头，让它通过 dsh 的 trusted-host 围栏（client-connection 插件）。

    dsh 对每个 /api 请求与 WS 升级做三重校验：
      1) `Host` 必须是回环地址（或部署时声明的 trustedHosts——CLI 只派生 LAN IP 字面量，
         隧道域名不在其中）；
      2) `Sec-Fetch-Site: cross-site` 直接拒；
      3) 带 `Origin` 时必须与 `Host` 完全一致（浏览器 Origin 是 `https://隧道域名`，必不符）。
    不过关 → HTTP 403 "forbidden"、WS 直接拒 → 前端拿不到任何数据（UI 停在 Loading plugins）。

    网关已用 key/cookie 把过每一道关，从 dsh 视角这就是「回环上的已认证请求」。所以：
    `Host` 改写成上游地址（回环，过第 1 条），`Origin` 整个剥掉（无 Origin 即视为同源，
    过第 3 条）；`Sec-Fetch-Site` 原样保留（浏览器同源请求就是 same-origin，真 cross-site
    该拒）。这是标准反向代理手法，不改任何请求体。
    """
    lines = head.split(b"\r\n")
    kept = [ln for ln in lines if not ln.lower().startswith(b"host:") and not ln.lower().startswith(b"origin:")]
    host_line = b"Host: " + (f"{upstream[0]}:{upstream[1]}").encode()
    if kept:
        kept.insert(1, host_line)  # 请求行之后
    else:
        kept.append(host_line)
    return b"\r\n".join(kept)


def _pipe(a: socket.socket, b: socket.socket) -> None:
    """a→b 单向透传；读尽或出错后半关 b 的写端（保住对端 FIN 语义）。"""
    try:
        while True:
            chunk = a.recv(65536)
            if not chunk:
                break
            b.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            b.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _send_401(conn: socket.socket) -> None:
    try:
        conn.sendall(
            b"HTTP/1.1 401 Unauthorized\r\n"
            b'WWW-Authenticate: Basic realm="' + REALM.encode() + b'", charset="UTF-8"\r\n'
            b"Content-Length: 0\r\n"
            b"Connection: close\r\n\r\n"
        )
    except OSError:
        pass
    conn.close()


class _Handler(socketserver.BaseRequestHandler):
    key: str  # 由服务端注入
    secret: bytes
    upstream: tuple[str, int]

    def _read_until(self, conn: socket.socket, delim: bytes, cap: int) -> bytes:
        data = b""
        while delim not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return data
            data += chunk
            if len(data) > cap:
                return data
        return data

    def handle(self) -> None:
        conn: socket.socket = self.request
        conn.settimeout(30)
        # 一条连接循环处理多个请求（HTTP keep-alive）。**必须**如此：Cloudflare 隧道会
        # 复用 origin 连接池，若一个请求处理完就卡住连接（等上游 EOF），新请求会积压在
        # 死连接上 → 隧道 502 / WS 升级失败 → 前端拿不到任何数据（UI 停在 Loading plugins）。
        while True:
            try:
                raw = self._read_until(conn, b"\r\n\r\n", _MAX_HEAD)
            except OSError:
                break
            if b"\r\n\r\n" not in raw:  # 连接在头读完前就断了
                break
            head, _, body = raw.partition(b"\r\n\r\n")
            is_ws = _is_ws_upgrade(head)

            # 认证：
            #   WebSocket（events.mux/host）→ 只能靠 cookie（浏览器 WS 握手带不了
            #     Authorization 头，但会带同源 cookie）；
            #   普通 HTTP → Basic Auth（并下发 cookie）或有效 cookie；都没有 → 401
            if is_ws:
                if not _cookie_ok(head, self.secret):
                    _send_401(conn)
                    return
                issue_cookie = False
            else:
                auth = _head_value(head, b"authorization")
                if _auth_ok(auth, self.key):
                    issue_cookie = True
                elif _cookie_ok(head, self.secret):
                    issue_cookie = False
                else:
                    _send_401(conn)
                    return

            if is_ws:
                # WebSocket：转发 upgrade 头，然后双向管道（101 握手 + 帧双向流）
                try:
                    up = socket.create_connection(self.upstream, timeout=10)
                except OSError:
                    try:
                        conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    except OSError:
                        pass
                    return
                conn.settimeout(None)
                up.settimeout(None)
                try:
                    up.sendall(_rewrite_for_upstream(head, self.upstream) + b"\r\n\r\n")
                except OSError:
                    up.close()
                    return
                t1 = threading.Thread(target=_pipe, args=(conn, up), daemon=True)
                t2 = threading.Thread(target=_pipe, args=(up, conn), daemon=True)
                t1.start()
                t2.start()
                t1.join()
                t2.join()
                up.close()
                return

            # 读完整个请求体（dsh web 的 unary POST 很小）
            cl = _head_value(head, b"content-length")
            if cl:
                try:
                    need = int(cl) - len(body)
                except ValueError:
                    break
                while need > 0:
                    try:
                        chunk = conn.recv(65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    body += chunk
                    need -= len(chunk)
                    if len(body) > _MAX_BODY:
                        break

            try:
                up = socket.create_connection(self.upstream, timeout=10)
                up.sendall(_rewrite_for_upstream(head, self.upstream) + b"\r\n\r\n" + body)
            except OSError:
                try:
                    conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                except OSError:
                    pass
                return

            # 读上游响应头；Basic Auth 通过时在此塞一个 Set-Cookie
            try:
                resp = self._read_until(up, b"\r\n\r\n", _MAX_HEAD)
            except OSError:
                up.close()
                break
            resp_head, _, resp_body = resp.partition(b"\r\n\r\n")
            if not resp_head:
                up.close()
                break
            if issue_cookie:
                setc = (
                    f"Set-Cookie: {COOKIE_NAME}="
                    f"{_cookie_token(self.secret).decode()}; Path=/; HttpOnly; SameSite=Lax"
                )
                resp_head = resp_head + b"\r\n" + setc.encode()

            try:
                conn.sendall(resp_head + b"\r\n\r\n" + resp_body)
            except OSError:
                up.close()
                break

            clv = _head_value(resp_head, b"content-length")
            if clv is None:
                # 无 Content-Length（chunked / SSE 长流等）：泵到上游 EOF，连接随之结束
                conn.settimeout(None)
                up.settimeout(None)
                _pipe(up, conn)
                up.close()
                break
            try:
                need = int(clv) - len(resp_body)
            except ValueError:
                up.close()
                break
            complete = True
            sent = 0
            while sent < need:
                try:
                    chunk = up.recv(min(65536, need - sent))
                except OSError:
                    complete = False
                    break
                if not chunk:
                    complete = False
                    break
                try:
                    conn.sendall(chunk)
                except OSError:
                    complete = False
                    break
                sent += len(chunk)
            up.close()
            if not complete:
                break
            # 响应完整。双方都 keep-alive 就留在连接上等下一个请求；否则收尾
            if b"connection: close" in head.lower() or b"connection: close" in resp_head.lower():
                break
            conn.settimeout(60)  # 空闲 60s 无新请求则收尾
        conn.close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def _handle_request_noblock(self):  # noqa: N802
        # 吞掉 accept 侧异常（如启动期间端口竞态），不让线程池炸掉
        try:
            super()._handle_request_noblock()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="dsh web Basic Auth gateway")
    ap.add_argument("--listen", default="0.0.0.0:3081")
    ap.add_argument("--upstream", default="127.0.0.1:3080")
    ap.add_argument("--key", required=True)
    args = ap.parse_args()

    listen_host, listen_port = _split(args.listen)
    upstream = _split(args.upstream)
    secret = os.urandom(32)  # 本进程会话凭据（cookie token 由此派生，不含 key）

    handler = type("BoundHandler", (_Handler,), {"key": args.key, "secret": secret, "upstream": upstream})
    server = _Server((listen_host, listen_port), handler)
    print(f"[dsh_gateway] listening on {listen_host}:{listen_port} -> {upstream[0]}:{upstream[1]} (cookie auth)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
