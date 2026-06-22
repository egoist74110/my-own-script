"""MCP stdio server 进程回收工具,解决"客户端会话结束后子进程不被回收"导致的泄漏。

两种用法:
- :func:`spawn_supervised` —— 给"wrapper 形态"用(本来 os.execvp 一个 npx/node 子进程)。
  改成 spawn 子进程并监管:客户端关掉 stdin / 给 SIGTERM / 或父进程消失(孤儿)时,
  连同子进程所在进程组一并回收,绝不留僵尸。stdio 直接继承,无代理层、无额外延迟。
- :func:`install_orphan_reaper` —— 给"纯 Python server 形态"用(自己读 sys.stdin 跑循环)。
  起一个守护线程,父进程一旦消失(被 reparent 到 init/launchd)就自杀。

为什么需要:MCP 客户端(Claude/Codex/Antigravity)正常退出时应 SIGTERM 掉 stdio server,
但会话被强杀 / 客户端不回收时,server 会变孤儿常驻。stdin EOF 是最可靠的"客户端走了"
信号,孤儿检测是兜底。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from typing import Optional, Sequence


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    """只给子进程所在进程组发信号，**不 wait**。

    关键:信号处理器和孤儿监视线程都不能调用 ``proc.wait()`` —— 主线程已经阻塞在
    ``proc.wait()`` 上,对同一子进程并发/重入 waitpid 会卡死(实测 bug)。收尾的 wait
    只在主线程做。
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except Exception:
        try:
            proc.send_signal(sig)
        except Exception:
            pass


def _orphan_watcher(on_orphan, interval: float = 2.0) -> None:
    """父进程从"非 1"变成 1(被 reparent 到 init/launchd)即判定孤儿,触发回调。

    初始 ppid 就是 1 的情况(直接被 launchd 拉起)无法判断,不启用,避免误杀。
    """
    initial_ppid = os.getppid()
    if initial_ppid == 1:
        return
    while True:
        try:
            if os.getppid() == 1:
                on_orphan()
                return
        except Exception:
            return
        time.sleep(interval)


def spawn_supervised(
    argv: Sequence[str],
    *,
    env: Optional[dict] = None,
    cwd: Optional[str] = None,
) -> int:
    """spawn 子进程(继承本进程 stdio)并监管其生命周期,返回子进程退出码。

    回收触发点:子进程自己退出 / 收到 SIGTERM·SIGINT / 本进程变孤儿。
    """
    proc = subprocess.Popen(
        list(argv),
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        cwd=cwd,
        env=env,
        start_new_session=True,  # 自成进程组,回收时连 npx→node 整棵树一起带走
    )

    def _signal_handler(_signum, _frame):
        # 信号处理器里只发信号,不 wait(主线程在 wait,重入会卡死),发完直接退出。
        _signal_group(proc, signal.SIGTERM)
        os._exit(143)

    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except Exception:
        pass  # 非主线程等少见场景,信号注册失败不致命

    # 孤儿监视线程:父进程消失就给子进程发 SIGTERM;子进程一死,主线程的 proc.wait()
    # 自然返回,函数正常收尾退出。线程同样不调 wait。
    threading.Thread(
        target=_orphan_watcher, args=(lambda: _signal_group(proc, signal.SIGTERM),),
        daemon=True,
    ).start()

    try:
        rc = proc.wait()
    except KeyboardInterrupt:
        _signal_group(proc, signal.SIGTERM)
        rc = 143
    # 兜底:走到这子进程理应已退;若没退(被孤儿线程 SIGTERM 后赖着),补一刀 SIGKILL。
    if proc.poll() is None:
        _signal_group(proc, signal.SIGKILL)
    return rc


def install_orphan_reaper() -> None:
    """给纯 Python stdio server 用:父进程消失即自杀(兜底 stdin-EOF 之外的孤儿场景)。"""
    threading.Thread(
        target=_orphan_watcher, args=(lambda: os._exit(0),), daemon=True
    ).start()


__all__ = ["spawn_supervised", "install_orphan_reaper"]
