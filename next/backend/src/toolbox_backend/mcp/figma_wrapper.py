"""Figma MCP stdio wrapper with Keychain secret injection and built-in process group supervision."""

from __future__ import annotations

import argparse
import contextlib
import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import CredentialStore, KeyringCredentials
from toolbox_backend.adapters.proc_supervisor import terminate_group
from toolbox_backend.logging_setup import register_secret
from toolbox_backend.mcp.runner import (
    mcp_environment,
    prepare_run_directory,
    redact_mcp,
    validate_data_dir,
)
from toolbox_backend.mcp.runtime import (
    RESOURCES_MCP_DIR,
    detect_node_runtime,
    figma_bin_js_path,
)


def _err(message: str) -> int:
    sys.stderr.write(redact_mcp(message).rstrip("\n") + "\n")
    sys.stderr.flush()
    return 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="figma_wrapper", add_help=False)
    parser.add_argument("--data-dir", required=True)
    return parser.parse_args(argv)


def _read_figma_token(credentials: CredentialStore | None) -> str | None:
    if credentials is not None:
        return credentials.get("figma_token")
    if "_MCP_MEM_FIGMA" in os.environ:
        val = os.environ.pop("_MCP_MEM_FIGMA", "")
        return val or None
    return KeyringCredentials().get("figma_token")


def main(
    argv: list[str] | None = None,
    *,
    credentials: CredentialStore | None = None,
) -> int:
    caller_cwd = Path.cwd()
    try:
        args = parse_args(argv)
    except BaseException:
        return _err("参数无效：需要 --data-dir")

    try:
        data_dir = validate_data_dir(args.data_dir)
        config = ConfigStore(data_dir)._read()
    except Exception:
        return _err("数据目录或配置无效")

    try:
        token = _read_figma_token(credentials)
    except Exception:
        return _err("读取 figma_token 失败")

    if not token:
        return _err("未配置 figma_token，请在设置中录入 Figma Token")
    register_secret(token)

    node_rt, _ = detect_node_runtime(data_dir, config.mcp.runtime.node)
    figma_bin = figma_bin_js_path(data_dir)
    if node_rt.source == "none" or not node_rt.path or not figma_bin.is_file():
        return _err("Figma MCP 运行组件未安装或不可用")

    try:
        run_cwd = prepare_run_directory(data_dir, "figma")
    except Exception:
        return _err("Figma MCP 运行目录不安全或非空")

    node_path = Path(node_rt.path)
    env = mcp_environment(path_extras=[node_path.parent])
    env.pop("_MCP_MEM_FIGMA", None)
    env["FIGMA_API_KEY"] = token
    env["FRAMELINK_TELEMETRY"] = "off"
    env["DO_NOT_TRACK"] = "1"
    env["FIGMA_MAX_CONCURRENCY"] = str(config.mcp.figma.max_concurrency)
    env["FIGMA_MIN_INTERVAL_MS"] = str(config.mcp.figma.min_interval_ms)
    env["FIGMA_MAX_RETRY"] = str(config.mcp.figma.max_retry)
    env["NODE_OPTIONS"] = f"--require {RESOURCES_MCP_DIR / 'figma_mcp_concurrency.js'}"

    cmd = [
        str(node_path),
        str(figma_bin),
        "--stdio",
        "--no-telemetry",
        "--image-dir",
        str(caller_cwd),
    ]

    parent_pid = os.getppid()
    stopping = threading.Event()

    def _handle_stop(*_args: object) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    try:
        child = subprocess.Popen(
            cmd,
            cwd=str(run_cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=sys.stdout,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        return _err("启动 Figma MCP 子进程失败")

    def _pump_stderr() -> None:
        assert child.stderr is not None
        try:
            for raw_line in child.stderr:
                text = raw_line.decode("utf-8", errors="replace")
                sys.stderr.write(redact_mcp(text))
                sys.stderr.flush()
        except OSError, ValueError:
            pass

    stderr_thread = threading.Thread(target=_pump_stderr, daemon=True)
    stderr_thread.start()

    stdin_fd = sys.stdin.fileno()
    next_parent_check = time.monotonic() + 0.5
    exit_code: int | None = None
    try:
        while not stopping.is_set():
            polled = child.poll()
            if polled is not None:
                exit_code = polled
                break
            now = time.monotonic()
            if now >= next_parent_check:
                if os.getppid() != parent_pid:
                    break
                next_parent_check = now + 0.5
            try:
                readable, _, _ = select.select([stdin_fd], [], [], 0.1)
            except OSError, ValueError:
                break
            if not readable:
                continue
            try:
                chunk = os.read(stdin_fd, 65536)
            except OSError:
                break
            if not chunk:
                # Signal 1: stdin EOF
                break
            if child.stdin is not None:
                try:
                    child.stdin.write(chunk)
                    child.stdin.flush()
                except BrokenPipeError, OSError:
                    break
    finally:
        if child.stdin is not None:
            with contextlib.suppress(OSError):
                child.stdin.close()
        code = terminate_group(child.pid, code=exit_code)
        if child.stderr is not None:
            with contextlib.suppress(OSError):
                child.stderr.close()

    if stopping.is_set():
        return 0
    return code if code is not None and code >= 0 else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError, KeyboardInterrupt:
        sys.exit(0)
