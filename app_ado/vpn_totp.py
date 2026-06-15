"""从 Ente Auth 导出文件里取 Harmony 的 TOTP 种子，之后本地算 6 位码。

为什么这么干：Ente 端到端加密、又是 Flutter（界面无辅助功能元素），没法直接读。
唯一稳的路子是用 Ente 自带「导出验证码（明文）」导一次——里面是明文 otpauth:// URI。
我们只抽出 Harmony/Perimeter81 那一条的种子存进钥匙串，**读完立刻删导出文件**
（那文件包含你所有账号的 2FA 种子，绝不能留）。之后每次登录用 pyotp 在本地算码，
令牌来源全自动、连输入都省了。

用法（CLI）：
    python -m app_ado.vpn_totp import <ente导出文件路径>   # 抽种子、存、删文件
    python -m app_ado.vpn_totp code                        # 打印当前 6 位码（调试）
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

from app_ado.secrets import get_totp_secret, set_totp_secret

# 匹配 Harmony / Perimeter81 / SaferVPN（旧名）的关键词（issuer 或 label）
_MATCH_KEYWORDS = ("perimeter", "harmony", "safervpn", "p81")


def _iter_otpauth_uris(text: str):
    """从导出文本里逐行抽出 otpauth:// URI（Ente 明文导出每行一个）。"""
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("otpauth://"):
            yield line


def _parse_uri(uri: str) -> dict:
    """解析 otpauth URI → {issuer, label, secret, period, digits, algorithm}。"""
    p = urllib.parse.urlparse(uri)
    q = urllib.parse.parse_qs(p.query)
    label = urllib.parse.unquote(p.path.lstrip("/"))
    issuer = (q.get("issuer", [""])[0] or "").strip()
    if not issuer and ":" in label:
        issuer = label.split(":", 1)[0].strip()
    return {
        "issuer": issuer,
        "label": label,
        "secret": (q.get("secret", [""])[0] or "").replace(" ", ""),
        "period": int(q.get("period", ["30"])[0]),
        "digits": int(q.get("digits", ["6"])[0]),
        "algorithm": (q.get("algorithm", ["SHA1"])[0] or "SHA1").upper(),
    }


def _matches_harmony(entry: dict) -> bool:
    hay = f"{entry['issuer']} {entry['label']}".lower()
    return any(k in hay for k in _MATCH_KEYWORDS)


def find_harmony_entries(text: str, keyword: str | None = None) -> list[dict]:
    """返回导出文本里所有疑似 Harmony 的 TOTP 条目。

    keyword 给定则只用它筛（用户配置的关键词，默认 Perimeter）；否则用内置关键词集。
    """
    entries = [_parse_uri(u) for u in _iter_otpauth_uris(text)]
    if keyword:
        kw = keyword.lower()
        return [e for e in entries
                if e["secret"] and kw in f"{e['issuer']} {e['label']}".lower()]
    return [e for e in entries if e["secret"] and _matches_harmony(e)]


def import_from_export(path: str | Path, *, delete: bool = True) -> dict:
    """读 Ente 导出文件 → 抽 Harmony 种子 → 存钥匙串 → 删文件。

    返回 {ok, msg, issuer?}。无论成败，delete=True 时都尽力删掉导出文件
    （里面有你所有 2FA 种子）。
    """
    path = Path(path).expanduser()
    if not path.is_file():
        return {"ok": False, "msg": f"找不到导出文件：{path}"}

    try:
        from app_ado.secrets import get_totp_filter

        keyword = get_totp_filter()
        text = path.read_text(encoding="utf-8", errors="replace")
        candidates = find_harmony_entries(text, keyword=keyword)

        if not candidates:
            n = sum(1 for _ in _iter_otpauth_uris(text))
            return {
                "ok": False,
                "msg": f"用关键词「{keyword}」在导出里没匹配到条目（共 {n} 条 otpauth）。"
                       "换个关键词：python -m app_ado.vpn_totp import <file> <关键词>，"
                       "或把那条的 issuer 名告诉我。",
            }
        # 多条匹配时取第一条，但回报数量让用户确认
        entry = candidates[0]
        if entry["algorithm"] != "SHA1" or entry["digits"] != 6:
            # pyotp 支持，但 Harmony 标准就是 SHA1/6/30，提示一下异常
            pass
        set_totp_secret(entry["secret"])
        msg = f"已存 Harmony 种子（issuer={entry['issuer'] or entry['label']}）"
        if len(candidates) > 1:
            msg += f"；注意匹配到 {len(candidates)} 条，取了第一条"
        return {"ok": True, "msg": msg, "issuer": entry["issuer"] or entry["label"]}
    finally:
        if delete:
            try:
                path.unlink()
            except Exception:
                pass


def current_code() -> str | None:
    """用存好的种子算当前 6 位码；没种子返回 None。"""
    secret = get_totp_secret()
    if not secret:
        return None
    import pyotp

    return pyotp.TOTP(secret).now()


def has_secret() -> bool:
    return bool(get_totp_secret())


# ----------------------------- CLI -----------------------------

def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "code"
    if cmd == "import":
        if len(sys.argv) < 3:
            print("用法：python -m app_ado.vpn_totp import <ente导出文件路径> [关键词]")
            return
        if len(sys.argv) >= 4:  # 临时关键词，顺便存为默认
            from app_ado.secrets import set_totp_filter

            set_totp_filter(sys.argv[3])
        r = import_from_export(sys.argv[2])
        print(("✅ " if r["ok"] else "❌ ") + r["msg"])
    elif cmd == "code":
        c = current_code()
        print(c if c else "（还没存种子，先 import）")
    else:
        print("用法：python -m app_ado.vpn_totp [import <file>|code]")


if __name__ == "__main__":
    main()
