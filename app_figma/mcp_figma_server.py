"""Figma MCP server 入口:wrapper 形态 —— 从 keyring 读 Figma API Token,
然后 exec 官方 figma-developer-mcp(Framelink) 走 stdio。

可直接被 Claude Code / Codex / Gemini CLI 当作 MCP server 命令调用。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app_figma.secrets import get_figma_token
from app_lark.node_bootstrap import augment_path_env, find_npx
from app_lark.proc_supervise import spawn_supervised


def _die(msg: str, code: int = 2) -> None:
    sys.stderr.write(f"[figma-mcp wrapper] {msg}\n")
    sys.exit(code)


def main() -> None:
    token = (get_figma_token() or "").strip()
    if not token:
        _die("未配置 Figma API Token。请在 UI > MCP配置 > Figma MCP 卡里填写并保存。")

    # 先把 PATH 扩成「bootstrap + 系统常见 Node 位置」，这样 execvp(npx) 跑起来
    # 之后 npx 的 shebang `#!/usr/bin/env node` 也能找到 node。
    # 不做这一步，macOS .app 在 launchd 起来时 PATH 只剩 /usr/bin:/bin:... 会报
    # `env: node: No such file or directory`。
    augment_path_env()

    npx_path = find_npx()
    if npx_path is None:
        _die(
            "未找到 Node.js 运行时。请到 UI > MCP配置 > Figma MCP 卡里点「开启 Figma MCP」"
            "走「安装」流程，或自行安装 Node.js 后再启动。",
            code=4,
        )
    npx = str(npx_path)

    argv = [
        npx,
        "-y",
        "figma-developer-mcp",
        "--stdio",
    ]

    # token 经环境变量 FIGMA_API_KEY 传(figma-developer-mcp 支持),不放进命令行参数——
    # 否则 `ps aux` 任何用户都能看到明文 token。env 默认不出现在 ps 列表里,安全得多。
    child_env = dict(os.environ)
    child_env["FIGMA_API_KEY"] = token

    # 不用 os.execvp:改成监管式 spawn,客户端断开/本进程变孤儿时连 npx→node 一起回收,
    # 避免会话结束后 figma-developer-mcp 常驻泄漏。
    sys.exit(spawn_supervised(argv, env=child_env))


if __name__ == "__main__":
    main()
