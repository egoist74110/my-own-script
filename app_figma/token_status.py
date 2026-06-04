"""Figma token 的过期状态:以本地"设置日期+有效期"估算剩余天数为准,在线探活只做加分确认。

- 剩余天数:来自 app_figma.store 记录的 token_set_at / expiry_days(用户在 App 保存 token 时记)。
- 在线探活:GET https://api.figma.com/v1/me 带 X-Figma-Token。
  ⚠️ 只把 **200** 当作"确认有效"的加分项;**绝不**用非 200 判"失效"——因为按"读取设计稿勾
  File content 权限即可"生成的 token 只有文件权限,调 /v1/me(需用户权限)会返回 403,
  而 Figma 对"无效 token"和"权限不够的有效 token"都返回 403,无法区分。早期版本用它判失效,
  导致完全有效的读图 token 被误报"已失效"。
"""

from __future__ import annotations

import datetime as _dt
import math
import urllib.error
import urllib.request

from app_figma.secrets import get_figma_token, is_figma_configured
from app_figma.store import figma_expiry_date


FIGMA_ME_URL = "https://api.figma.com/v1/me"


def _probe_token_online(token: str, timeout: float = 6.0) -> bool | None:
    """只回答"能不能在线确认有效":True=200 确认有效;None=无法确认(403/网络等,不下结论)。

    不返回 False —— 见模块 docstring,403 在 Figma 是歧义的,不能据此判失效。
    """
    req = urllib.request.Request(FIGMA_ME_URL, headers={"X-Figma-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return None


def figma_token_status(probe: bool = True) -> dict:
    """keys: configured(bool), level('ok'|'warn'|'error'|'unknown'), label(str),
    days_left(int|None), expires_at(datetime|None), online(bool|None)

    判级**完全以本地到期日期为准**;在线探活仅在确认有效时加一句备注。
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

    online = _probe_token_online(get_figma_token() or "") if probe else None
    out["online"] = online
    confirmed = " · 在线校验有效" if online else ""

    if exp is None:
        # 老 token:本功能上线前保存的,没记设置日期,估不出剩余。提示重新保存以开始计时。
        out["level"] = "ok"
        out["label"] = "已配置（未记录有效期，重新保存一次可开始倒计时）" + confirmed
        return out

    date_str = exp.strftime("%Y-%m-%d")
    if days_left is not None and days_left <= 0:
        out["level"] = "error"
        out["label"] = f"已过期（设定到期日 {date_str}），请重新生成并保存"
    elif days_left is not None and days_left <= 7:
        out["level"] = "warn"
        out["label"] = f"{out['days_left']} 天后过期（{date_str}）—— 该续期了"
    else:
        out["level"] = "ok"
        out["label"] = f"剩 {out['days_left']} 天（{date_str}）{confirmed}"
    return out


__all__ = ["figma_token_status"]
