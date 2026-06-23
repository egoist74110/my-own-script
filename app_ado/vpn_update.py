"""检测并点掉 Harmony 窗口内的「更新提示」（Install/Update 按钮）。

为什么不用辅助功能(AX)：
  Harmony SASE 是 background-only 的 Electron 菜单栏应用，主窗对 macOS 辅助功能**完全不可见**
  （进程只有 AXApplication + 两个 AXMenuBar，0 个 window 节点，entire contents 全为空）。
  窗口内的更新横幅是 Electron 渲染的，AX 既扫不到也点不到。实测验证过，此路不通。

唯一稳的办法（不依赖 AX、不用预先标定坐标）：
  截屏 → 用 macOS 自带 Vision OCR 找 "Install/Update/Restart…" 这类按钮文字 →
  把归一化坐标换算成屏幕点坐标 → Quartz 合成鼠标点击其中心。
  OCR 在屏幕哪里认到就点哪里，布局/位置变了也不怕。

前提权限（缺了就直接报错提示）：
  - 屏幕录制：截屏需要。系统设置 → 隐私与安全性 → 屏幕录制 → 勾选运行方
    （开发时是终端/Python；打包后是 app 本体）。
  - 辅助功能：合成点击需要（本项目其它自动化已用到）。

CLI（调试/标定用）：
    python -m app_ado.vpn_update perm     # 查屏幕录制权限，没有就弹系统授权框
    python -m app_ado.vpn_update scan      # 截屏+OCR，打印所有文字框 + 选中的目标（**不点**）
    python -m app_ado.vpn_update click     # 真点（找到 Install/Update 才点）
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable

LogFn = Callable[[str], None]

_APP_NAME = "Harmony SASE"
# open -a 换出大窗的节流时间戳（秒）。大主窗不是常驻的，自愈时菜单栏默认只有小 popover
# （图2，无更新信息），必须 open -a 把大窗（图1）换出来，OCR 才看得到 Install/Update 横幅。
_last_surface = [0.0]

# 命中即点的「正向」按钮关键词（小写、子串匹配）。
# 故意不放裸 "update"——它常出现在标题 "Update available" 里，会误点标题。
# 要点的是动作按钮：Install / Restart / Relaunch / Download / Update Now。
_POS = ("install", "restart", "relaunch", "download", "update now", "update &", "upgrade")
# 含这些词的一律跳过（稍后/取消/跳过类），别把更新关掉。
_NEG = ("later", "not now", "skip", "remind", "cancel", "dismiss", "close",
        "no thanks", "snooze", "ignore", "next time")
# 按钮文字一般很短；超过这个长度多半是正文/标题，不当按钮点。
_MAX_BTN_LEN = 24


# ----------------------------- 权限 -----------------------------

def has_screen_permission() -> bool:
    """屏幕录制权限是否已授予（不弹框）。"""
    try:
        import Quartz
        if hasattr(Quartz, "CGPreflightScreenCaptureAccess"):
            return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        pass
    # 老系统没这个 API：尝试截一张，能截到非空就算有
    return _grab_main() is not None


def request_screen_permission() -> bool:
    """弹出系统「屏幕录制」授权框（首次授权后通常需重启本进程才生效）。"""
    try:
        import Quartz
        if hasattr(Quartz, "CGRequestScreenCaptureAccess"):
            return bool(Quartz.CGRequestScreenCaptureAccess())
    except Exception:
        pass
    return False


# ----------------------------- 截屏 -----------------------------

def surface_app(*, force: bool = False, throttle: float = 12.0, wait: float = 1.6) -> None:
    """把 Harmony 大主窗换到前台再截屏。

    自愈时大窗常常没开（菜单栏只有小 popover，没更新信息），`open -a` 会把大窗换出来。
    throttle 秒内不重复 open，避免在轮询里反复抢焦点。force=True 立即换（标定/CLI 用）。
    """
    now = time.time()
    if not force and (now - _last_surface[0]) < throttle:
        return
    _last_surface[0] = now
    subprocess.run(["open", "-a", _APP_NAME], check=False)
    # 再显式置前：光 open -a 有时压不过别的前台窗（如 Chrome），更新横幅会被遮住 OCR 截不到
    subprocess.run(
        ["osascript", "-e",
         f'tell application "System Events" to tell process "{_APP_NAME}" to set frontmost to true'],
        check=False, capture_output=True,
    )
    time.sleep(wait)


def _active_displays():
    import Quartz
    err, ids, n = Quartz.CGGetActiveDisplayList(16, None, None)
    if err:
        return []
    return list(ids[:n])


def _grab_main():
    """截主显示器，成功返回 CGImage，失败/无权限返回 None。"""
    import Quartz
    img = Quartz.CGDisplayCreateImage(Quartz.CGMainDisplayID())
    return img or None


# ----------------------------- OCR -----------------------------

def _ocr(cgimg) -> list[dict]:
    """对一张 CGImage 跑 Vision OCR。返回 [{text, nx, ny, nw, nh}]，坐标是归一化(原点左下)。"""
    import Vision

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimg, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    try:
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    except Exception:
        pass
    try:
        req.setUsesLanguageCorrection_(False)
    except Exception:
        pass
    try:
        # 更新提示是英文，限定 en 更快更准（也避免被满屏中文带偏）
        req.setRecognitionLanguages_(["en-US"])
    except Exception:
        pass
    ok = handler.performRequests_error_([req], None)
    if not ok:
        return []
    out: list[dict] = []
    for obs in (req.results() or []):
        try:
            cand = obs.topCandidates_(1)
            if not cand:
                continue
            text = cand[0].string()
            bb = obs.boundingBox()  # 归一化，原点左下
            out.append({
                "text": text,
                "nx": bb.origin.x, "ny": bb.origin.y,
                "nw": bb.size.width, "nh": bb.size.height,
            })
        except Exception:
            continue
    return out


def _pick_target(items: list[dict]) -> dict | None:
    """从 OCR 文字里挑出该点的按钮。命中正向词、排除负向词、且文字短。

    多个候选时，优先「文字几乎就等于关键词」的（真按钮），否则取最短的。
    """
    cands = []
    for it in items:
        t = (it["text"] or "").strip()
        low = t.lower()
        if not t or len(t) > _MAX_BTN_LEN:
            continue
        if any(nk in low for nk in _NEG):
            continue
        if any(pk in low for pk in _POS):
            cands.append(it)
    if not cands:
        return None

    def score(it):
        t = it["text"].strip().lower()
        # 越接近纯关键词越像按钮：长度越短分越高
        return len(t)

    cands.sort(key=score)
    return cands[0]


def _pick_connect(items: list[dict]) -> dict | None:
    """挑出大窗里的「Connect / Reconnect」按钮（未连接时要点它连上）。

    必须严格排除 Disconnect（已连时的按钮）、Connected to（状态文字）、Change Network。
    只认几乎就等于 connect/reconnect 的短文字，避免误点。
    """
    cands = []
    for it in items:
        t = (it["text"] or "").strip()
        low = t.lower()
        if not t or len(t) > _MAX_BTN_LEN:
            continue
        if "disconnect" in low or "connected" in low or "change" in low:
            continue
        if low.replace(" ", "") in ("connect", "reconnect", "connectnow"):
            cands.append(it)
    if not cands:
        return None
    cands.sort(key=lambda it: len(it["text"].strip()))
    return cands[0]


# ----------------------------- 坐标换算 + 点击 -----------------------------

def _norm_to_screen(it: dict, display_id) -> tuple[float, float]:
    """归一化坐标(原点左下) → 全局屏幕点坐标(原点左上，CGEvent 用的就是这个)。"""
    import Quartz
    b = Quartz.CGDisplayBounds(display_id)
    cx = it["nx"] + it["nw"] / 2.0
    cy = it["ny"] + it["nh"] / 2.0
    px = b.origin.x + cx * b.size.width
    py = b.origin.y + (1.0 - cy) * b.size.height  # 翻 y 到左上原点
    return px, py


def _click(x: float, y: float) -> None:
    import Quartz
    pt = (x, y)
    for etype in (Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        ev = Quartz.CGEventCreateMouseEvent(None, etype, pt, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.04)


# ----------------------------- 对外入口 -----------------------------

def _find_button(picker, log: LogFn = print, *, surface: bool = True) -> tuple | None:
    """扫所有显示器，用 picker 从 OCR 文字里挑按钮。

    找到返回 (文字, x, y, display_id, 全部OCR文字)，否则 None。
    surface=True（默认）会先把 Harmony 大主窗换出来（节流），否则只 OCR 当前屏。
    """
    import Quartz

    if not has_screen_permission():
        log("[update] 没有「屏幕录制」权限，截不了屏。"
            "去 系统设置→隐私与安全性→屏幕录制 勾选运行方（或先跑 perm 授权）。")
        return None

    if surface:
        surface_app()

    for did in (_active_displays() or [Quartz.CGMainDisplayID()]):
        img = Quartz.CGDisplayCreateImage(did)
        if not img:
            continue
        items = _ocr(img)
        target = picker(items)
        if target:
            x, y = _norm_to_screen(target, did)
            return (target["text"].strip(), x, y, did, items)
    return None


def find_update_button(log: LogFn = print, *, surface: bool = True) -> tuple | None:
    return _find_button(_pick_target, log, surface=surface)


def find_connect_button(log: LogFn = print, *, surface: bool = True) -> tuple | None:
    return _find_button(_pick_connect, log, surface=surface)


def click_update_prompt(log: LogFn = print, *, dry_run: bool = False) -> str | None:
    """发现 Harmony 更新提示就点其 Install/Update 按钮。返回点了的按钮文字或 None。

    dry_run=True 只报告会点谁、不真点（标定用）。
    """
    found = find_update_button(log)
    if not found:
        return None
    text, x, y, _did, _items = found
    if dry_run:
        log(f"[update] (dry-run) 会点「{text}」@ ({x:.0f},{y:.0f})")
        return text
    _click(x, y)
    log(f"[update] 检测到更新提示，已点「{text}」@ ({x:.0f},{y:.0f})，等更新+重启…")
    return text


def click_connect_button(log: LogFn = print, *, dry_run: bool = False) -> str | None:
    """大窗显示 Connect（未连接）时点它连上。返回点了的按钮文字或 None。"""
    found = find_connect_button(log)
    if not found:
        return None
    text, x, y, _did, _items = found
    if dry_run:
        log(f"[connect] (dry-run) 会点「{text}」@ ({x:.0f},{y:.0f})")
        return text
    _click(x, y)
    log(f"[connect] 检测到未连接，已点「{text}」@ ({x:.0f},{y:.0f})")
    return text


def resolve_stuck(log: LogFn = print, *, dry_run: bool = False) -> tuple | None:
    """换出大窗 + 一次 OCR，优先处理更新提示（点 Install），否则点 Connect。

    返回 ("update"|"connect", 按钮文字) 或 None。比分别调两个 click_* 省一半截屏。
    """
    import Quartz

    if not has_screen_permission():
        log("[update] 没有「屏幕录制」权限，截不了屏。"
            "去 系统设置→隐私与安全性→屏幕录制 勾选运行方（或先跑 perm 授权）。")
        return None

    surface_app()
    for did in (_active_displays() or [Quartz.CGMainDisplayID()]):
        img = Quartz.CGDisplayCreateImage(did)
        if not img:
            continue
        items = _ocr(img)
        upd = _pick_target(items)
        if upd:
            x, y = _norm_to_screen(upd, did)
            text = upd["text"].strip()
            if not dry_run:
                _click(x, y)
            log(f"[update] 检测到更新提示，{'(dry)' if dry_run else '已点'}「{text}」，等更新+重启…")
            return ("update", text)
        con = _pick_connect(items)
        if con:
            x, y = _norm_to_screen(con, did)
            text = con["text"].strip()
            if not dry_run:
                _click(x, y)
            log(f"[connect] 检测到未连接，{'(dry)' if dry_run else '已点'}「{text}」连接…")
            return ("connect", text)
    return None


# ----------------------------- CLI -----------------------------

def _cli_scan(dry: bool) -> None:
    surface_app(force=True)  # 标定时一定先把大窗换出来
    found = find_update_button(print, surface=False)
    if not found:
        print("没找到 Install/Update 类按钮。")
        # 把每块屏认到的短文字打出来，方便看 OCR 到底读到了啥（Harmony 不一定在主屏）
        import Quartz
        for did in (_active_displays() or [Quartz.CGMainDisplayID()]):
            img = Quartz.CGDisplayCreateImage(did)
            if not img:
                continue
            items = _ocr(img)
            shorts = [i["text"].strip() for i in items if 0 < len(i["text"].strip()) <= _MAX_BTN_LEN]
            print(f"（display {did} OCR 短文字样本，共 {len(shorts)} 条）：", shorts[:40])
        return
    text, x, y, did, items = found
    print(f"目标按钮：「{text}」  屏幕点坐标 ({x:.0f},{y:.0f})  display={did}")
    if not dry:
        _click(x, y)
        print("已点。")


def main() -> None:
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "perm":
        if has_screen_permission():
            print("✅ 已有屏幕录制权限。")
        else:
            print("没有屏幕录制权限，弹系统授权框…（授权后可能要重开本进程/终端才生效）")
            request_screen_permission()
    elif cmd == "scan":
        _cli_scan(dry=True)
    elif cmd == "click":
        r = click_update_prompt(print, dry_run=False)
        print("结果：", f"已点「{r}」" if r else "没有可点的更新提示")
    elif cmd == "connect":
        r = click_connect_button(print, dry_run=False)
        print("结果：", f"已点「{r}」" if r else "没找到 Connect 按钮（可能已连/未开大窗）")
    elif cmd == "resolve":
        surface_app(force=True)
        r = resolve_stuck(print, dry_run=True)
        print("结果(dry-run)：", r or "更新/连接 都没有可点的")
    else:
        print("用法：python -m app_ado.vpn_update [perm|scan|click|connect|resolve]")


if __name__ == "__main__":
    main()
