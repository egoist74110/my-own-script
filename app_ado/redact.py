"""Telegram 等错误文本脱敏：进入日志/状态/异常消息/回发用户之前统一清理。

只抹掉敏感值（bot URL 中的 token、认证头值、已知当前 token 字面值），
保留状态码、方法、非敏感路径、异常类型与服务端 description。
"""

from __future__ import annotations

import re
from urllib.parse import quote
from typing import Iterable

# /bot<digits>:<token>/ （token 字符集：字母数字 _ -；容忍 URL 编码的 %3A）
_BOT_URL_RE = re.compile(r"/bot\d+(?::|%3[Aa])[A-Za-z0-9_\-]+(?=/|\b|$)")
# Authorization / Proxy-Authorization / X-...-Token 之类头值（含 JSON/repr 引号形式）
_AUTH_HEADER_RE = re.compile(
    r"""(?ix)
    (?P<k>["']?(?:proxy-)?authorization["']?\s*[:=]\s*["']?|["']?x-[a-z0-9-]*(?:token|secret|key)["']?\s*[:=]\s*["']?)
    (?:[A-Za-z][A-Za-z0-9_-]*\s+(?=[^\s"',;}\]]))?
    (?P<v>[^\s"',;}\]]+)
    """
)
_MASK = "***"


def redact_text(text: object, *known_tokens: str | None) -> str:
    """返回脱敏后的字符串。缺 token（None/空串）不报错。"""
    try:
        s = text if isinstance(text, str) else str(text)
    except Exception:  # noqa: BLE001
        s = "<unprintable>"
    s = _BOT_URL_RE.sub("/bot" + _MASK, s)
    s = _AUTH_HEADER_RE.sub(lambda m: m.group("k") + _MASK, s)
    toks: Iterable[str | None] = known_tokens
    # 长的先替换，避免短 token 是长 token 前缀时留下残片
    for t in sorted({t for t in toks if t and isinstance(t, str)}, key=len, reverse=True):
        for variant in {t, quote(t, safe=''), quote(t, safe='-_')}:
            s = s.replace(variant, _MASK)
    return s


def redact_exception(exc: BaseException, *known_tokens: str | None) -> str:
    """异常 -> 脱敏文本；保留异常类型，并展开 __cause__/__context__ 链中的文本。"""
    parts: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen and len(parts) < 6:
        seen.add(id(cur))
        parts.append(f"{type(cur).__name__}: {cur}" if str(cur) else type(cur).__name__)
        cur = cur.__cause__ or cur.__context__
    # 首项保持与 str(exc) 兼容（调用方依赖 "409"/"timed out" 等子串）：首项只用 str(exc)
    head = redact_text(str(exc), *known_tokens)
    if len(parts) <= 1:
        return head
    chain = " <- ".join(redact_text(p, *known_tokens) for p in parts[1:])
    return f"{head} [{chain}]"
