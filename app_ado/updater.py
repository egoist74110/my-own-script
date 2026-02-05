from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UpdateStatus:
    behind: int
    ahead: int
    head: str
    remote: str


def _run(cmd: list[str], cwd: Path, *, timeout: int = 10) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Never block on interactive git prompts in GUI context.
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    # Ensure SSH-based remotes fail fast (no passphrase / no prompts)
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=5")
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=env, timeout=timeout)
    except FileNotFoundError as e:
        raise RuntimeError(f"找不到命令：{cmd[0]}（可能是从 .app 启动时 PATH 不包含 git）") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"命令超时（{timeout}s）：{' '.join(cmd)}") from e


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def check_git_clean(cwd: Path) -> tuple[bool, str]:
    cp = _run(["git", "status", "--porcelain"], cwd)
    if cp.returncode != 0:
        return False, (cp.stderr or cp.stdout or "git status failed")
    return (cp.stdout.strip() == ""), cp.stdout.strip()


def fetch(cwd: Path) -> None:
    cp = _run(["git", "fetch", "origin"], cwd, timeout=10)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr or cp.stdout or "git fetch failed")


def get_update_status(cwd: Path, branch: str = "main") -> UpdateStatus:
    # Ensure this is a git repo
    cp0 = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd)
    if cp0.returncode != 0 or cp0.stdout.strip() != "true":
        raise RuntimeError("当前目录不是 Git 仓库，无法检查更新")

    # Ensure remote refs exist
    fetch(cwd)

    cp1 = _run(["git", "rev-parse", "HEAD"], cwd)
    if cp1.returncode != 0:
        raise RuntimeError(cp1.stderr or cp1.stdout or "git rev-parse HEAD failed")
    head = cp1.stdout.strip()

    cp2 = _run(["git", "rev-parse", f"origin/{branch}"], cwd)
    if cp2.returncode != 0:
        raise RuntimeError(cp2.stderr or cp2.stdout or f"git rev-parse origin/{branch} failed")
    remote = cp2.stdout.strip()

    # behind/ahead counts
    cp3 = _run(["git", "rev-list", "--count", f"HEAD..origin/{branch}"], cwd)
    if cp3.returncode != 0:
        raise RuntimeError(cp3.stderr or cp3.stdout or "git rev-list behind failed")
    behind = int(cp3.stdout.strip() or "0")

    cp4 = _run(["git", "rev-list", "--count", f"origin/{branch}..HEAD"], cwd)
    if cp4.returncode != 0:
        raise RuntimeError(cp4.stderr or cp4.stdout or "git rev-list ahead failed")
    ahead = int(cp4.stdout.strip() or "0")

    return UpdateStatus(behind=behind, ahead=ahead, head=head, remote=remote)


def pull_ff_only(cwd: Path, branch: str = "main") -> str:
    cp = _run(["git", "pull", "--ff-only", "origin", branch], cwd)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr or cp.stdout or "git pull --ff-only failed")
    return cp.stdout.strip()


def pip_sync(cwd: Path) -> str:
    # On mac we use requirements-mac.txt
    req = cwd / "requirements-mac.txt"
    if not req.exists():
        return "skip pip: requirements-mac.txt not found"
    cp = _run([sys.executable, "-m", "pip", "install", "-r", str(req)], cwd)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr or cp.stdout or "pip install failed")
    return cp.stdout.strip()


def restart_self() -> None:
    os.execv(sys.executable, [sys.executable] + sys.argv)
