"""Harmony SASE 本地连接控制 + 自愈阶梯。

三种掉线场景，从轻到重自动升级，只有最后一档（登录失效）才需要令牌：

    档 0  已连着            → 检测到 10.254.x，直接返回
    档 A  程序崩了/没开      → open -a 重开（app 自动连）
    档 B  开着但断连         → 重启 app（quit+open，自动连）——避开易碎的菜单栏点击
    档 C  登录失效           → 浏览器 SSO 重新登录（要令牌），回调后自动连

A/B 试完仍连不上（超时）→ 说明 session 死了 → 自动落到 C。
调用方（CLI / TG / UI）只管喊一次 ensure_connected，由它自己探测并升级。
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable

from app_ado.vpn_ip import get_vpn_ip

APP_NAME = "Harmony SASE"
APP_PROC_MATCH = "Harmony SASE.app/Contents/MacOS"  # pgrep -f 用，避免误杀本脚本

LogFn = Callable[[str], None]
TokenFn = Callable[[], "str | None"]


# ----------------------------- 进程 / app 控制 -----------------------------

def app_running() -> bool:
    """Harmony SASE 主程序是否在跑（不含 root helper）。"""
    r = subprocess.run(["pgrep", "-f", APP_PROC_MATCH], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def open_app(log: LogFn = print) -> None:
    log(f"打开 {APP_NAME}…")
    subprocess.run(["open", "-a", APP_NAME], check=False)


def quit_app(log: LogFn = print) -> None:
    """优雅退出；不行就按进程名 kill（不碰 root helper）。"""
    subprocess.run(
        ["osascript", "-e", f'quit app "{APP_NAME}"'], check=False,
        capture_output=True, text=True,
    )
    time.sleep(1.5)
    if app_running():
        log("优雅退出没生效，改用 pkill…")
        subprocess.run(["pkill", "-f", APP_PROC_MATCH], check=False)
        time.sleep(1.0)


# 更新提示：Harmony 偶尔弹英文「是否更新」横幅（按钮 Install/Update），挡住自动连接导致卡死。
# 难点：Harmony 是 background-only 的 Electron 菜单栏应用，主窗对辅助功能(AX)**完全不可见**
# （进程只有菜单栏、0 个 window 节点），窗口内按钮 AX 既扫不到也点不到——实测验证过。
# 唯一稳的办法：截屏 + macOS Vision OCR 找 Install/Update 文字 + 合成鼠标点击。实现见 vpn_update.py。
# 需要「屏幕录制」权限（截屏）+「辅助功能」权限（合成点击）。
def click_update_prompt(log: LogFn = print) -> "str | None":
    """发现 Harmony 更新提示就点其 Install/Update 按钮。返回点了的按钮文字或 None。"""
    if not app_running():
        return None
    try:
        from app_ado.vpn_update import click_update_prompt as _do
        return _do(log)
    except Exception as e:  # noqa: BLE001
        log(f"[update] 更新检测不可用：{e}")
        return None


def resolve_window(log: LogFn = print) -> "tuple | None":
    """换出大窗 + 一次 OCR 处理两件事：有更新提示就点 Install；否则若显示 Connect 就点它连上。

    返回 ("update"|"connect", 按钮文字) 或 None。比浏览器登录轻得多——session 还在、
    只是没自动连时，点一下窗口里的 Connect 就好。
    """
    if not app_running():
        return None
    try:
        from app_ado.vpn_update import resolve_stuck
        return resolve_stuck(log)
    except Exception as e:  # noqa: BLE001
        log(f"[window] 窗口自愈不可用：{e}")
        return None


def wait_connected(timeout: float = 30.0, log: LogFn = print, *, watch_window: bool = True) -> "str | None":
    """轮询直到拿到 VPN IP 或超时。返回 IP 或 None。

    watch_window：途中周期性换出大窗 OCR 自愈——有更新提示就点 Install（并把等待延长到
    ≥180s，因更新下载+重启耗时，免得被误判超时落到登录档）；否则若显示 Connect 就点它连上。
    """
    deadline = time.time() + timeout
    last_chk = 0.0
    extended = False
    while time.time() < deadline:
        ip = get_vpn_ip()
        if ip:
            return ip
        now = time.time()
        if watch_window and now - last_chk > 4:
            last_chk = now
            r = resolve_window(log)
            if r and r[0] == "update" and not extended:
                deadline = now + 180.0
                extended = True
        time.sleep(1.5)
    return None


def restart_app(log: LogFn = print) -> None:
    """重启 app 触发自动重连（quit→等退干净→open）。"""
    if app_running():
        quit_app(log)
        for _ in range(10):
            if not app_running():
                break
            time.sleep(0.5)
    open_app(log)


def status() -> dict:
    """当前状态快照：{connected, ip, app_running}。"""
    ip = get_vpn_ip()
    return {"connected": bool(ip), "ip": ip, "app_running": app_running()}


# ----------------------------- 自愈阶梯 -----------------------------

def ensure_connected(
    token_provider: TokenFn,
    log: LogFn = print,
    *,
    rung_timeout: float = 30.0,
    allow_login: bool = True,
) -> bool:
    """从轻到重把 VPN 连上。返回是否最终连上。

    token_provider 只在落到「登录失效」那档时才会被调用。
    allow_login=False 可只跑 A/B（不触发浏览器登录，测试用）。
    """
    # 档 0：已连着
    ip = get_vpn_ip()
    if ip:
        log(f"✅ 已连着 VPN：{ip}")
        return True

    # 档 A / B：保证 app 以「干净启动」态运行，靠它自己自动连
    if not app_running():
        log("档A：程序没在跑 → 重开")
        open_app(log)
    else:
        log("档B：程序在跑但没连上 → 重启触发自动重连")
        restart_app(log)

    ip = wait_connected(rung_timeout, log)
    if ip:
        log(f"✅ 重连成功：{ip}")
        return True

    # 档 C：重启都连不上 → session 多半失效 → 浏览器重新登录（要令牌）
    if not allow_login:
        log("⏱ A/B 未连上，且 allow_login=False，停。")
        return False

    log("档C：重启仍未连上 → 判定登录失效，走浏览器 SSO 重新登录")
    try:
        from app_ado.secrets import get_vpn_config, vpn_config_complete
        from app_ado.vpn_login import login_flow, playwright_available
    except Exception as e:  # noqa: BLE001
        log(f"无法加载登录模块：{e}")
        return False

    if not playwright_available():
        log("未安装 Playwright，无法自动登录。先：.venv/bin/python -m pip install playwright")
        return False
    if not vpn_config_complete():
        log("还没配置登录信息（服务页 → VPN 配置）。")
        return False

    cfg = get_vpn_config()
    auto_token, seeded = _auto_token_provider(token_provider, log)
    # 有种子 → 全程无人值守可 headless（不弹窗）；没种子要手输则用有头浏览器
    # login_flow 内部：没出现 MFA 页时（缓存会话有效/浏览器被记住）会直接捕获回调连上，不碰令牌
    return login_flow(cfg, auto_token, log=log, headless=seeded)


def _auto_token_provider(token_provider: TokenFn, log: LogFn):
    """返回 (provider, seeded)。优先用 Ente 种子本地算码，没有才回退到传入 provider。"""
    try:
        from app_ado.vpn_totp import has_secret
    except Exception:
        return token_provider, False
    seeded = has_secret()

    def provider() -> "str | None":
        if seeded:
            try:
                from app_ado.vpn_totp import current_code

                log("用 Ente 种子本地算出令牌（免输入）")
                return current_code()
            except Exception as e:  # noqa: BLE001
                log(f"本地算令牌失败，回退手输：{e}")
        return token_provider()

    return provider, seeded


def relogin(token_provider: TokenFn, log: LogFn = print) -> bool:
    """强制走浏览器 SSO 重新登录（无视当前是否已连）。用于验证/强制刷新会话。"""
    from app_ado.secrets import get_vpn_config, vpn_config_complete
    from app_ado.vpn_login import login_flow, playwright_available

    if not playwright_available():
        log("未安装 Playwright。先：.venv/bin/python -m pip install playwright")
        return False
    if not vpn_config_complete():
        log("还没配置登录信息（服务页 → VPN 配置）。")
        return False
    cfg = get_vpn_config()
    auto_token, seeded = _auto_token_provider(token_provider, log)
    return login_flow(cfg, auto_token, log=log, headless=seeded, check_existing=False)


# ----------------------------- CLI -----------------------------

def main() -> None:
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(status())
    elif cmd == "on":
        ok = ensure_connected(
            token_provider=lambda: input("请输入 6 位令牌：").strip(),
            log=print,
        )
        print("结果：", "✅ 已连上" if ok else "❌ 未连上")
    elif cmd == "test-ab":
        # 只测 A/B 两档（不触发登录、不要令牌）
        ok = ensure_connected(token_provider=lambda: None, log=print, allow_login=False)
        print("A/B 结果：", "✅ 连上" if ok else "❌ 没连上（可能 session 已失效，需走登录）")
    elif cmd == "restart":
        restart_app(print)
        ip = wait_connected(30, print)
        print("重启后：", ip or "未连上")
    elif cmd == "check-update":
        name = click_update_prompt(print)
        print("结果：", f"已点「{name}」" if name else "当前没有更新提示")
    elif cmd == "connect":
        # 大窗显示 Connect 时点它连上（轻量自愈，不走浏览器登录）
        from app_ado.vpn_update import click_connect_button
        name = click_connect_button(print) if app_running() else None
        print("结果：", f"已点「{name}」" if name else "没找到 Connect 按钮")
        if name:
            ip = wait_connected(30, print)
            print("连接后：", ip or "仍未连上")
    elif cmd == "resolve":
        r = resolve_window(print)
        print("结果：", r or "更新/连接 都没有可点的")
    elif cmd == "relogin":
        ok = relogin(token_provider=lambda: input("请输入 6 位令牌：").strip(), log=print)
        print("结果：", "✅ 已连上" if ok else "❌ 未连上")
    else:
        print("用法：python -m app_ado.vpn_control "
              "[status|on|test-ab|restart|check-update|connect|resolve|relogin]")


if __name__ == "__main__":
    main()
