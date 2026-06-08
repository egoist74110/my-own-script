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


_CONCURRENCY_PRELOAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figma_mcp_concurrency.js")


def _inject_concurrency_guard(env: dict[str, str]) -> dict[str, str]:
    """给 figma-developer-mcp 子进程注入并发/限流 preload(NODE_OPTIONS=--require)。

    在子进程里把 globalThis.fetch 包一层:对 api.figma.com 的请求做并发闸(默认串行 1)、
    最小间隔与 429/5xx 退避重试,根治「一次多个 tool call 并发打爆 Figma 限流」。详见
    ``figma_mcp_concurrency.js``。文件缺失或已注入过则跳过,不影响启动。
    """
    if not os.path.isfile(_CONCURRENCY_PRELOAD):
        return env
    require_arg = f"--require {_CONCURRENCY_PRELOAD}"
    prev = (env.get("NODE_OPTIONS") or "").strip()
    if _CONCURRENCY_PRELOAD not in prev:
        env["NODE_OPTIONS"] = f"{prev} {require_arg}".strip() if prev else require_arg
    return env


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

    # figma-developer-mcp 对 api.figma.com 既不限并发也不退避重试:AI 一次发多个 tool call
    # → 并发 N 个请求打到 Figma REST → 命中按 token 的成本限流(尤其 /images)→ 429 整批失败。
    # 注入 preload 在子进程里把 fetch 包一层做并发闸 + 退避重试。详见 figma_mcp_concurrency.js。
    _inject_concurrency_guard(child_env)

    # 不用 os.execvp:改成监管式 spawn,客户端断开/本进程变孤儿时连 npx→node 一起回收,
    # 避免会话结束后 figma-developer-mcp 常驻泄漏。
    sys.exit(spawn_supervised(argv, env=child_env))


if __name__ == "__main__":
    main()
