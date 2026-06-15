"""Harmony SASE 远程自动登录（Playwright 驱动 Perimeter81 SSO）。

流程：workspace 选择 → 邮箱/密码 → MFA 6 位令牌 → 回调 HarmonySASE:// 深链 → app 自动连上。

设计要点：
- 用**持久化 Chrome profile**（config_dir/vpn_chrome_profile）+ 系统已装的 Chrome（channel="chrome"），
  不下载 Chromium；勾上 "Remember this browser" 后，一段时间内远程登录可少输甚至不输令牌。
- 回调深链 `HarmonySASE://...#access_token=...` 浏览器打不开，双保险拿到它：
  ① CDP 的 Page.frameRequestedNavigation 事件截 URL；② 真实 Chrome 会自然唤起 Harmony app。
  截到就自己 `open` 一下，确保 app 收到 token 自动连接。
- MFA 令牌通过 token_provider 回调拿（CLI 用 input()，将来 TG 用异步回填）；令牌只过内存，不落盘。
- 进度通过 log 回调上报（CLI 用 print，将来接 TG/UI）。

CLI（开发/手动用）：
    python -m app_ado.vpn_login setup    # 交互存 workspace/residency/邮箱/密码 到钥匙串
    python -m app_ado.vpn_login login    # 跑登录，提示输 6 位令牌
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Callable

from app_ado.secrets import get_vpn_config, set_vpn_config, vpn_config_complete
from app_ado.store import config_dir
from app_ado.vpn_ip import get_vpn_ip

SIGN_IN_URL = (
    "https://app.perimeter81.com/sign-in"
    "?redirectUrl=HarmonySASE://perimeter81.com/macos/callback&allowTenantSelect="
)
DEEPLINK_PREFIX = "HarmonySASE://"

RESIDENCY_OPTIONS = [
    "US Data Residency",
    "EU Data Residency",
    "India Data Residency",
    "Australia Data Residency",
    "CA Data Residency",
]

LogFn = Callable[[str], None]
TokenFn = Callable[[], str | None]


def _profile_dir() -> str:
    d = config_dir() / "vpn_chrome_profile"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def playwright_ensure_installed(log: LogFn = print) -> tuple[bool, str]:
    """选装：没装 Playwright 就用当前解释器 pip 装。

    用系统 Chrome（channel="chrome"）驱动，**不**下载 Chromium，所以只装 playwright 包即可。
    """
    if playwright_available():
        return True, ""
    log("正在安装 Playwright（首次使用，约几十 MB）…")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright"],
            capture_output=True, text=True, timeout=600,
        )
    except Exception as e:  # noqa: BLE001
        return False, f"安装异常：{e}"
    if playwright_available():
        return True, ""
    tail = (r.stderr or r.stdout or "")[-300:]
    return False, f"安装后仍不可用：{tail}"


def _dump_inputs(page, log: LogFn) -> None:
    """把当前页可见的 input/button 打出来（探 TOTP 页选择器用）。"""
    try:
        els = page.evaluate(
            """() => [...document.querySelectorAll('input,button')].map(el => {
                const r = el.getBoundingClientRect();
                if (r.width===0 && r.height===0) return null;
                return {tag: el.tagName.toLowerCase(), type: el.getAttribute('type')||'',
                  name: el.getAttribute('name')||'', ph: el.getAttribute('placeholder')||'',
                  aria: el.getAttribute('aria-label')||'', text: (el.innerText||'').trim().slice(0,24)};
            }).filter(Boolean)"""
        )
        for el in els:
            log("    " + str(el))
    except Exception as e:
        log(f"    (dump 失败: {e})")


def login_flow(
    cfg: dict,
    token_provider: TokenFn,
    log: LogFn = print,
    headless: bool = False,
    connect_timeout: float = 75.0,
    check_existing: bool = True,
) -> bool:
    """跑完整登录并等待 VPN 连上。返回是否连上（get_vpn_ip 有值）。"""
    from playwright.sync_api import sync_playwright

    if check_existing and get_vpn_ip():
        log("已经连着 VPN 了，无需登录。")
        return True

    captured: dict[str, str | None] = {"url": None}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            _profile_dir(),
            channel="chrome",
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # —— 回调深链捕获（CDP）——
        # 真实深链是**小写** harmonysase://...#id_token=...（不是 access_token）；
        # 大小写必须不敏感匹配，否则永远截不到。监听 scheduled+requested 两个事件更稳。
        def _on_nav(e):
            u = e.get("url", "")
            if u.lower().startswith(DEEPLINK_PREFIX.lower()) and not captured["url"]:
                captured["url"] = u
                log(f"[capture] 截到回调深链（CDP）：{u[:72]}…")

        try:
            cdp = ctx.new_cdp_session(page)
            cdp.send("Page.enable")
            cdp.on("Page.frameRequestedNavigation", _on_nav)
            cdp.on("Page.frameScheduledNavigation", _on_nav)
        except Exception as e:
            log(f"[capture] CDP 监听挂载失败（仍可靠自然唤起）：{e}")

        page.on("framenavigated", lambda f: f == page.main_frame and log(f"[nav] {f.url[:80]}"))

        # —— Step 1: workspace ——
        log("打开登录页…")
        page.goto(SIGN_IN_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("input[name='name']", timeout=25000)
        log(f"填 workspace：{cfg['workspace']}")
        page.fill("input[name='name']", cfg["workspace"])
        # 数据驻留区下拉（MUI Select）：当前默认就对就别动它；要改才点开选（选项是 li[role=menuitem]）
        residency = cfg.get("residency") or RESIDENCY_OPTIONS[0]
        try:
            trigger = page.locator("div[role='button']:has-text('Data Residency')").first
            current = (trigger.inner_text() or "").strip()
            if residency and residency not in current:
                trigger.click()
                page.wait_for_timeout(400)
                page.locator(f"li[role='menuitem']:has-text('{residency}')").first.click(timeout=4000)
                page.wait_for_timeout(300)
                log(f"选数据驻留区：{residency}")
            else:
                log(f"数据驻留区已是默认：{current}")
        except Exception as e:
            log(f"[residency] 选择失败（用页面默认）：{e}")
            try:
                page.keyboard.press("Escape")  # 关掉可能卡开的菜单，别挡住 Continue
            except Exception:
                pass
        page.click("button[type='submit']")

        # —— Step 2: 邮箱 / 密码 ——
        page.wait_for_selector("input[name='username']", timeout=25000)
        log(f"填邮箱/密码：{cfg['email']}")
        page.fill("input[name='username']", cfg["email"])
        page.fill("input[name='password']", cfg["password"])
        page.click("button[type='submit']")

        # —— Step 3: 等密码提交后落定（跳 auth.perimeter81.com/mf 出 MFA），或被记住浏览器直接回调 ——
        # 注意：**不**拿 get_vpn_ip 当 break 条件——强制 relogin 时旧连接还在会导致早 break、
        # 在密码页上误判令牌框。只认：截到回调深链 / 进了 /mf(auth) 页。
        log("密码已提交，等待 MFA 页 / 回调…")
        for _ in range(40):
            if captured["url"]:
                break
            url = page.url
            if "/mf" in url or "auth.perimeter81.com" in url:
                try:
                    page.wait_for_selector(
                        "input[name='code'], input[autocomplete='one-time-code']", timeout=5000
                    )
                except Exception:
                    pass
                break
            time.sleep(0.8)

        totp_sel = None
        if captured["url"]:
            log("密码提交后浏览器被记住、直接回调，跳过 MFA。")
        else:
            log(f"密码提交后落点：{page.url}")
            log("当前页可见控件：")
            _dump_inputs(page, log)
            # 找 6 位令牌框：明确排除 username/password，绝不误填到登录框
            for sel in (
                "input[name='code']",
                "input[autocomplete='one-time-code']",
                "input[placeholder*='digit']",
                "input[placeholder*='code']",
                "input[inputmode='numeric']",
                "input[type='tel']",
            ):
                try:
                    base = page.locator(sel)
                    if base.count() == 0:
                        continue
                    loc = base.first
                    if not loc.is_visible():
                        continue
                    nm = (loc.get_attribute("name") or "").lower()
                    tp = (loc.get_attribute("type") or "").lower()
                    if nm in ("username", "password") or tp == "password":
                        continue
                    totp_sel = sel
                    break
                except Exception:
                    continue

        if not totp_sel:
            log("没找到 MFA 令牌输入框——可能本次浏览器被记住、已跳过 MFA，或页面结构变了。")
        else:
            log(f"MFA 令牌框选择器：{totp_sel}")
            token = (token_provider() or "").strip()
            if not token:
                log("没拿到令牌，放弃。")
                ctx.close()
                return False
            page.fill(totp_sel, token)
            # 勾上 "Remember this browser"（下次少输令牌）
            try:
                cb = page.locator("input[type='checkbox']").first
                if cb.count() > 0 and not cb.is_checked():
                    cb.check()
                    log("已勾选 Remember this browser")
            except Exception:
                pass
            # 提交（优先点提交按钮，否则回车）
            try:
                page.click("button[type='submit']", timeout=3000)
            except Exception:
                page.locator(totp_sel).press("Enter")
            log("已提交令牌，等待回调与连接…")

        # —— Step 4: 等回调 / 连接 ——
        # 实测坑：冷启动时 app 的 harmonysase:// URL handler 还没注册好，第一发深链会被丢。
        # 所以：先 open -a 并**轮询等 app 真起来**，再**周期性重发深链**直到连上（重发幂等、安全）。
        from app_ado.vpn_control import app_running

        deadline = time.time() + connect_timeout
        launched = False
        last_fire = 0.0
        while time.time() < deadline:
            ip = get_vpn_ip()
            if ip:
                log(f"✅ 已连上 VPN：{ip}")
                ctx.close()
                return True
            if captured["url"]:
                if not launched:
                    if not app_running():
                        log("先确保 Harmony app 在跑…")
                        subprocess.run(["open", "-a", "Harmony SASE"], check=False)
                        for _ in range(15):
                            if app_running():
                                break
                            time.sleep(1)
                        time.sleep(3)  # 多给点时间注册 harmonysase:// handler
                    launched = True
                if time.time() - last_fire > 8:  # 冷启动早期可能被丢，周期性重发
                    log("把回调深链交给 app 唤起连接…")
                    subprocess.run(["open", captured["url"]], check=False)
                    last_fire = time.time()
            time.sleep(2)

        log("⏱ 等待超时，仍未检测到 VPN 地址。")
        ctx.close()
        return bool(get_vpn_ip())


# ----------------------------- CLI -----------------------------

def _cli_setup() -> None:
    import getpass

    print("配置 Harmony VPN 登录信息（存进系统钥匙串；密码不回显）")
    workspace = input("Workspace 名（如 888cggame）：").strip()
    print("数据驻留区： 1)US  2)EU  3)India  4)Australia  5)CA")
    idx = (input("选 [1-5，默认 1]：").strip() or "1")
    try:
        residency = RESIDENCY_OPTIONS[int(idx) - 1]
    except Exception:
        residency = RESIDENCY_OPTIONS[0]
    email = input("邮箱：").strip()
    password = getpass.getpass("密码：")
    set_vpn_config(workspace=workspace, residency=residency, email=email, password=password)
    print(f"已保存（workspace={workspace}, residency={residency}, email={email}）。")


def _cli_login() -> None:
    if not playwright_available():
        print("未安装 Playwright，请先：.venv/bin/python -m pip install playwright")
        return
    if not vpn_config_complete():
        print("还没配置登录信息，请先跑：python -m app_ado.vpn_login setup")
        return
    cfg = get_vpn_config()

    def token_provider() -> str:
        return input("请输入 Authenticator 6 位令牌：").strip()

    ok = login_flow(cfg, token_provider, log=print, headless=False)
    print("结果：", "✅ 已连上 VPN" if ok else "❌ 未连上")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    {"setup": _cli_setup, "login": _cli_login}.get(cmd, _cli_login)()


if __name__ == "__main__":
    main()
