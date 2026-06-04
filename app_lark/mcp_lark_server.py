"""Lark MCP server 入口:wrapper 形态 —— 从项目配置/keyring 读凭据,
然后 exec 官方 @larksuiteoapi/lark-mcp 走 stdio。

可直接被 Claude Code / Codex / Gemini CLI 当作 MCP server 命令调用。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app_lark.node_bootstrap import augment_path_env, find_npx
from app_lark.proc_supervise import spawn_supervised
from app_lark.secrets import get_app_secret
from app_lark.store import (
    DEFAULT_DOMAIN,
    DEFAULT_OAUTH_PORT,
    DEFAULT_TOOLS,
    is_logged_in,
    load_lark_settings,
)


def _die(msg: str, code: int = 2) -> None:
    sys.stderr.write(f"[lark-mcp wrapper] {msg}\n")
    sys.exit(code)


def main() -> None:
    s = load_lark_settings()

    app_id = (s.app_id or "").strip()
    if not app_id:
        _die("未配置 App ID。请在 UI > MCP配置 > Lark MCP 卡里填写并保存。")

    secret = get_app_secret(app_id)
    if not secret:
        _die(f"找不到 App Secret(App ID={app_id})。请在 UI 里填写后保存到 keyring。")

    if not is_logged_in(app_id):
        _die("未登录。搜索 / 深度文档读取需要 user_access_token,请在 UI > MCP配置 > Lark MCP 点 \"登录\" 完成 OAuth 授权后再启动。", code=3)

    # 先把 PATH 扩成「bootstrap + 系统常见 Node 位置」，这样 execvp(npx) 跑起来
    # 之后 npx 的 shebang `#!/usr/bin/env node` 也能找到 node。
    # 不做这一步，macOS .app 在 launchd 起来时 PATH 只剩 /usr/bin:/bin:... 会报
    # `env: node: No such file or directory`。
    augment_path_env()

    npx_path = find_npx()
    if npx_path is None:
        _die(
            "未找到 Node.js 运行时。请到 UI > MCP配置 > Lark MCP 卡里点「开启 Lark MCP」"
            "走「安装」流程，或自行安装 Node.js 后再启动。",
            code=4,
        )
    npx = str(npx_path)

    # 强制 user_access_token:搜索 / 深度文档读取走 UAT,tenant 模式部分接口直接 404
    token_mode = "user_access_token"
    port = int(s.oauth_port or DEFAULT_OAUTH_PORT)

    argv = [
        npx,
        "-y",
        "@larksuiteoapi/lark-mcp",
        "mcp",
        "-a", app_id,
        "-s", secret,
        "-d", (s.domain or DEFAULT_DOMAIN).strip(),
        "-t", (s.tools or DEFAULT_TOOLS).strip(),
        "-m", "stdio",
        "--token-mode", token_mode,
        "-l", (s.language or "zh").strip(),
        "--oauth",
        "-p", str(port),
    ]

    # 监管式 spawn(替代 os.execvp):会话结束/孤儿时连 npx→node 一起回收。
    # 注:推荐改用 App 托管的共享 HTTP 单实例(见 lark_mcp_flow);此 stdio 入口仅作兼容回退。
    sys.exit(spawn_supervised(argv))


if __name__ == "__main__":
    main()
