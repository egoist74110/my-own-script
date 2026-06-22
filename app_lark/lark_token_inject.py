"""把 app 登录拿到的 Lark user_access_token 作为静态 Bearer 注入各 AI 工具的 MCP 配置。

背景:lark-mcp 跑 ``--oauth``,每个连上来的客户端本来都得自己走一遍浏览器 OAuth 才能拿 bearer
——app 在自己这边登录拿到的 token 从不交给客户端,于是"在程序里登过了,Claude/Antigravity 还要再登"。
而 lark-mcp 的 ``verifyAccessToken(bearer)`` 只是拿 bearer 去 store 里精确查 ``tokens[bearer]``
(不绑 client、不卡 scope),所以只要把 app 的 UAT 写进各工具配置的 Authorization header,客户端
就能免授权直连。配合已注入的 verifyAccessToken/supersession 补丁,这个静态 bearer 过期后也会被
底层自动续期、长期有效。

只动各工具的 MCP 配置文件,写前都做备份 + 原子替换;每个工具独立成败,互不影响。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from app_lark.store import DEFAULT_OAUTH_PORT, lark_mcp_http_url, load_lark_settings
from app_lark.token_status import get_active_user_access_token


def _http_url() -> str:
    s = load_lark_settings()
    return lark_mcp_http_url(int(s.oauth_port or DEFAULT_OAUTH_PORT))


@dataclass
class InjectResult:
    tool: str
    ok: bool
    detail: str


def _backup(path: Path) -> None:
    """写前备份(沿用各工具自己的 .bak 习惯,带时间戳不覆盖历史)。"""
    if path.exists():
        ts = time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + f".bak.larktoken-{ts}"))
        except Exception:
            pass


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".larktoken.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception as e:
        raise RuntimeError(f"现有 JSON 无法解析,未敢改动:{e}")


# ---------------- Claude Code (~/.claude.json) ----------------
def _inject_claude(url: str, token: str) -> InjectResult:
    path = Path.home() / ".claude.json"
    try:
        data = _load_json(path)
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
            data["mcpServers"] = servers
        servers["lark"] = {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}
        _backup(path)
        _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return InjectResult("Claude Code", True, f"已写入 {path}(mcpServers.lark.headers)")
    except Exception as e:
        return InjectResult("Claude Code", False, f"失败:{e}")


# ---------------- Antigravity CLI (~/.gemini/settings.json) ----------------
# 谷歌废弃 Gemini CLI 后，Antigravity CLI（agy）仍沿用 ~/.gemini 这个 home，
# 也仍读 ~/.gemini/settings.json 的 mcpServers，所以注入目标不变，只是叫法改了。
def _inject_gemini(url: str, token: str) -> InjectResult:
    path = Path.home() / ".gemini" / "settings.json"
    try:
        data = _load_json(path)
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
            data["mcpServers"] = servers
        servers["lark"] = {"httpUrl": url, "headers": {"Authorization": f"Bearer {token}"}}
        _backup(path)
        _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return InjectResult("Antigravity CLI", True, f"已写入 {path}(mcpServers.lark.headers)")
    except Exception as e:
        return InjectResult("Antigravity CLI", False, f"失败:{e}")


# ---------------- Codex (~/.codex/config.toml) ----------------
def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _upsert_codex_section(text: str, header: str, body: str) -> str:
    """在 TOML 文本里就地替换/追加一个 ``[section]`` 块(只动这一段,其余字节不变)。"""
    block = f"{header}\n{body}"
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == header), None)
    if start is None:
        sep = "" if text.endswith("\n\n") or text == "" else ("\n" if text.endswith("\n") else "\n\n")
        return text + sep + block + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    new_lines = lines[:start] + block.splitlines() + lines[end:]
    out = "\n".join(new_lines)
    return out + "\n" if text.endswith("\n") else out


def _inject_codex(url: str, token: str) -> InjectResult:
    path = Path.home() / ".codex" / "config.toml"
    try:
        text = path.read_text("utf-8") if path.exists() else ""
        body = (
            f'url = "{_toml_escape(url)}"\n'
            f'http_headers = {{ Authorization = "Bearer {_toml_escape(token)}" }}'
        )
        new_text = _upsert_codex_section(text, "[mcp_servers.lark]", body)
        # 改完先自检能解析,坏了就不落盘
        tomllib.loads(new_text)
        _backup(path)
        _atomic_write_text(path, new_text)
        return InjectResult("Codex", True, f"已写入 {path}([mcp_servers.lark].http_headers)")
    except Exception as e:
        return InjectResult("Codex", False, f"失败:{e}")


def inject_bearer_to_all_tools(tools: tuple[str, ...] = ("claude", "gemini", "codex")) -> dict:
    """把当前登录态的 UAT 作为 Bearer 注入指定工具的 MCP 配置。

    返回 dict:ok(bool 是否至少一个成功)、token_label(str)、stale(bool 当前 token 注入即失效)、
    results(list[InjectResult])、message(str 总结)。
    """
    info = get_active_user_access_token()
    token = info.get("token")
    out: dict = {
        "ok": False,
        "token_label": info.get("label", ""),
        "stale": bool(info.get("stale")),
        "results": [],
        "message": "",
    }
    if not token:
        out["message"] = info.get("label") or "拿不到可用的 Lark 登录态(请先在 app 里登录)"
        return out

    url = _http_url()
    writers = {"claude": _inject_claude, "gemini": _inject_gemini, "codex": _inject_codex}
    results = [writers[t](url, token) for t in tools if t in writers]
    out["results"] = results
    out["ok"] = any(r.ok for r in results)

    oks = [r.tool for r in results if r.ok]
    fails = [f"{r.tool}({r.detail})" for r in results if not r.ok]
    parts = []
    if oks:
        parts.append("已注入:" + "、".join(oks))
    if fails:
        parts.append("失败:" + "; ".join(fails))
    if out["stale"]:
        parts.append("⚠️ 当前 token 已过期且无 refresh_token,注入了也会很快失效——请先用「重新登录」拿到带 refresh_token 的新 token 再注入")
    parts.append("注入后需重启对应 AI 工具(或新开会话)让其按新配置免授权直连")
    out["message"] = "。".join(parts)
    return out


__all__ = ["inject_bearer_to_all_tools", "InjectResult"]
