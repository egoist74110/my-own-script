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


# ---------- 每个 AI 的专属 Telegram 机器人 Token ----------
# 给某个 AI（AiCliProfile.id，如 claude_code）配独立机器人时，Bot Token 存这里。
# @用户名等非密信息存 ui_settings 的 ai.bots。
def ai_bot_token_key(ai_id: str) -> str:
    return f"ai_bot_token:{ai_id}"


def get_ai_bot_token(ai_id: str) -> str | None:
    return keyring.get_password(APP_ID, ai_bot_token_key(ai_id))


def set_ai_bot_token(ai_id: str, token: str) -> None:
    keyring.set_password(APP_ID, ai_bot_token_key(ai_id), token)


def delete_ai_bot_token(ai_id: str) -> None:
    try:
        keyring.delete_password(APP_ID, ai_bot_token_key(ai_id))
    except Exception:
        pass


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


# ---------- dsh web 登录密钥 ----------
# dsh web 本身没有密码登录，由 app_ado/dsh_gateway.py 做 Basic Auth 把关；
# 密钥只进钥匙串（红线），首次启动服务时自动生成。
def dsh_password_key() -> str:
    return "dsh_web_password"


def get_dsh_password() -> str | None:
    return keyring.get_password(APP_ID, dsh_password_key())


def set_dsh_password(pw: str) -> None:
    keyring.set_password(APP_ID, dsh_password_key(), pw)


def clear_dsh_password() -> None:
    try:
        keyring.delete_password(APP_ID, dsh_password_key())
    except Exception:
        pass


# dsh 隧道 token（Cloudflare 命名隧道，主控制台 Networking > Tunnels 创建，免费计划可用、
# 无需绑卡；token 只进钥匙串，红线同 dsh 密钥）。面板「隧道」按钮优先用它（固定域名、稳）。
def dsh_tunnel_token_key() -> str:
    return "dsh_web_tunnel_token"


def get_dsh_tunnel_token() -> str | None:
    return keyring.get_password(APP_ID, dsh_tunnel_token_key())


def set_dsh_tunnel_token(token: str) -> None:
    keyring.set_password(APP_ID, dsh_tunnel_token_key(), token)


def clear_dsh_tunnel_token() -> None:
    try:
        keyring.delete_password(APP_ID, dsh_tunnel_token_key())
    except Exception:
        pass


# 命名隧道自定义主机名（路由 CNAME，如 dsh.<域名>）；面板「复制域名」优先显示它，
# 没设就显示从 token 推导的 <tunnel-id>.cfargotunnel.com。
def dsh_tunnel_domain_key() -> str:
    return "dsh_web_tunnel_domain"


def get_dsh_tunnel_domain() -> str | None:
    return (keyring.get_password(APP_ID, dsh_tunnel_domain_key()) or "").strip() or None


def set_dsh_tunnel_domain(domain: str) -> None:
    keyring.set_password(APP_ID, dsh_tunnel_domain_key(), domain)


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
