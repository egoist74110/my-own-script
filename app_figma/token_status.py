"""Figma token 的过期状态:本地按"设置日期+有效期"估算剩余天数 + /v1/me 在线探活。

- 剩余天数:来自 app_figma.store 记录的 token_set_at / expiry_days。
- 在线有效性:GET https://api.figma.com/v1/me 带 X-Figma-Token。200=有效，
  403/401=失效或被吊销。网络异常则只回退到"按天数估算"。
"""

from __future__ import annotations

import datetime as _dt
import math
import urllib.error
import urllib.request

from app_figma.secrets import get_figma_token, is_figma_configured
from app_figma.store import figma_expiry_date


FIGMA_ME_URL = "https://api.figma.com/v1/me"


def _probe_token_valid(token: str, timeout: float = 6.0) -> bool | None:
    """True=有效, False=失效(403/401), None=网络/未知(不下结论)。"""
    req = urllib.request.Request(FIGMA_ME_URL, headers={"X-Figma-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False
        return None
    except Exception:
        return None


def figma_token_status(probe: bool = True) -> dict:
    """keys: configured(bool), level('ok'|'warn'|'error'|'unknown'), label(str),
    days_left(int|None), expires_at(datetime|None), online(bool|None)
    """
    out: dict = {
        "configured": False,
        "level": "unknown",
        "label": "未配置",
        "days_left": None,
        "expires_at": None,
        "online": None,
    }
    if not is_figma_configured():
        return out
    out["configured"] = True

    exp = figma_expiry_date()
    out["expires_at"] = exp
    days_left = None
    if exp is not None:
        days_left = (exp - _dt.datetime.now()).total_seconds() / 86400.0
        # 向上取整:新设 90 天的 token 当天就显示"剩 90 天"，临期判断也偏保守
        out["days_left"] = math.ceil(days_left) if days_left >= 0 else -math.ceil(-days_left)

    online = _probe_token_valid(get_figma_token() or "") if probe else None
    out["online"] = online

    # 在线探活权重最高:明确失效就是失效
    if online is False:
        out["level"] = "error"
        out["label"] = "Token 已失效或被吊销（Figma 接口返回未授权）"
        return out

    if exp is None:
        # 老 token:本功能上线前保存的，没记设置日期，估不出剩余
        out["level"] = "ok" if online else "warn"
        suffix = "（在线校验：有效）" if online else "（未记录设置日期，无法估算剩余；重新保存一次可开始计时）"
        out["label"] = f"已配置{suffix}"
        return out

    date_str = exp.strftime("%Y-%m-%d")
    if days_left is not None and days_left <= 0:
        out["level"] = "error"
        out["label"] = f"已过期（设定到期日 {date_str}）"
    elif days_left is not None and days_left <= 7:
        out["level"] = "warn"
        out["label"] = f"{out['days_left']} 天后过期（{date_str}）—— 该续期了"
    else:
        out["level"] = "ok"
        n = out["days_left"]
        tail = " · 在线校验有效" if online else ""
        out["label"] = f"剩 {n} 天（{date_str}）{tail}"
    return out


__all__ = ["figma_token_status"]
