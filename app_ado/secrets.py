from __future__ import annotations

import keyring

from app_ado.store import APP_ID


def pat_key(library_id: str) -> str:
    return f"azuredevops_pat:{library_id}"


def get_pat(library_id: str) -> str | None:
    return keyring.get_password(APP_ID, pat_key(library_id))


def set_pat(library_id: str, pat: str) -> None:
    keyring.set_password(APP_ID, pat_key(library_id), pat)


def telegram_token_key() -> str:
    return "telegram_bot_token"


def get_telegram_token() -> str | None:
    return keyring.get_password(APP_ID, telegram_token_key())


def set_telegram_token(token: str) -> None:
    keyring.set_password(APP_ID, telegram_token_key(), token)


# ---------- Harmony SASE VPN 登录凭证 ----------
# 远程自动登录需要的几样东西：workspace 名、数据驻留区、邮箱、密码。
# 全部进系统钥匙串（keyring，service=APP_ID）。MFA 令牌**绝不**存，每次现取。
_VPN_FIELDS = ("workspace", "residency", "email", "password")


def _vpn_key(field: str) -> str:
    return f"harmony_vpn:{field}"


def get_vpn_config() -> dict[str, str | None]:
    """返回 {workspace, residency, email, password}，缺的为 None。"""
    return {f: keyring.get_password(APP_ID, _vpn_key(f)) for f in _VPN_FIELDS}


def set_vpn_config(*, workspace: str, residency: str, email: str, password: str) -> None:
    vals = {"workspace": workspace, "residency": residency, "email": email, "password": password}
    for f, v in vals.items():
        keyring.set_password(APP_ID, _vpn_key(f), v)


def vpn_config_complete() -> bool:
    cfg = get_vpn_config()
    return all(cfg.get(f) for f in _VPN_FIELDS)


# ---------- TOTP 种子（从 Ente 导出一次后存这里，登录时本地算 6 位码）----------
# 注意：存了种子 = 本机同时持有「密码 + MFA 两个因子」，MFA 不再额外加固本机。
# 这是用户为远程便利的明确取舍。种子只在 keyring，导出文件读完即删。
def _totp_key() -> str:
    return "harmony_vpn:totp_secret"


def get_totp_secret() -> str | None:
    return keyring.get_password(APP_ID, _totp_key())


def set_totp_secret(secret: str) -> None:
    keyring.set_password(APP_ID, _totp_key(), secret)


def clear_totp_secret() -> None:
    try:
        keyring.delete_password(APP_ID, _totp_key())
    except Exception:
        pass


# 从 Ente 导出里筛 Harmony 那条用的关键词（issuer/label 含此词即匹配）。
# 令牌多时用它精确定位，默认 "Perimeter"。
def _totp_filter_key() -> str:
    return "harmony_vpn:totp_filter"


def get_totp_filter() -> str:
    return keyring.get_password(APP_ID, _totp_filter_key()) or "Perimeter"


def set_totp_filter(keyword: str) -> None:
    keyring.set_password(APP_ID, _totp_filter_key(), keyword)
