"""S7 subprocess boundary doubles; no real service executables are used."""

import asyncio
import os
import socket
import sys

import pytest

from toolbox_backend.adapters.ai_process import SupervisedProcess
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.services.services import ServicesService


@pytest.fixture
async def process_capability(tmp_path):
    try:
        owner = await SupervisedProcess.start(
            [sys.executable, "-c", "pass"], str(tmp_path), stdio=True
        )
    except RuntimeError as exc:
        if str(exc) == "start_failed:PermissionError:1":
            pytest.skip("not_run: sandbox denies supervised process groups (PermissionError:1)")
        raise
    await owner.close()


def random_port():
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("not_run: sandbox denies loopback bind")
        return sock.getsockname()[1]


def make_service(tmp_path, monkeypatch, *, mode="listen", cloud="domains", timeout=1):
    port = random_port()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    code_config = tmp_path / "code.yaml"
    code_config.write_text(f"auth: password\nbind-addr: 127.0.0.1:{port}\npassword: unread-value\n")
    common = (
        f"#!{sys.executable}\n"
        + """import json,os,signal,socket,sys,time
"""
    )
    code = (
        common
        + f"port={port}\nmode={mode!r}\nroot={str(tmp_path)!r}\n"
        + """
with open(root+'/code-argv-env.json','w') as f: json.dump({'argv':sys.argv,'env':dict(os.environ)},f)
with open(root+'/code-pid','w') as f: f.write(str(os.getpid()))
if mode == 'exit': sys.exit(2)
if mode in {'ignore','grandchild'}: signal.signal(signal.SIGTERM, signal.SIG_IGN)
if mode == 'grandchild':
    child=os.fork()
    if not child:
        with open(root+'/grandchild-pid','w') as f: f.write(str(os.getpid()))
        while True: time.sleep(1)
if mode != 'timeout':
    sock=socket.socket(); sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    sock.bind(('127.0.0.1',port)); sock.listen(16); sock.settimeout(0.1)
while True:
    if mode == 'timeout': time.sleep(.1)
    else:
        try: conn,_=sock.accept(); conn.close()
        except TimeoutError: pass
"""
    )
    cloud_code = (
        common
        + f"mode={cloud!r}\nroot={str(tmp_path)!r}\n"
        + """
with open(root+'/cloud-'+str(os.getpid())+'-pid','w') as f: f.write(str(os.getpid()))
with open(root+'/cloud-argv-env.json','w') as f: json.dump({'argv':sys.argv,'env':dict(os.environ)},f)
if mode == 'exit': sys.exit(3)
if mode == 'ignore': signal.signal(signal.SIGTERM, signal.SIG_IGN)
if mode == 'domains':
    print('https://first.trycloudflare.com',flush=True)
    print('https://last.trycloudflare.com',flush=True)
    print('https://spoof.trycloudflare.com.evil.com',flush=True)
    print('prefix https://fake.trycloudflare.com',flush=True)
    print('Authorization: Bearer FAKE-LOG-SECRET-123',flush=True)
while True: time.sleep(.1)
"""
    )
    for name, text in [
        ("code-server", code),
        ("cloudflared", cloud_code),
        ("ifconfig", common + "print('en0: flags=0\\n    inet 192.168.20.5')\n"),
    ]:
        path = bin_dir / name
        path.write_text(text)
        path.chmod(0o700)
    for name in ["node", "npx", "npm", "lsof"]:
        path = bin_dir / name
        path.write_text(common + 'raise RuntimeError("forbidden executable")\n')
        path.chmod(0o700)
    monkeypatch.setenv("PATH", str(bin_dir))
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    store = ConfigStore(data)
    service = ServicesService(store, code_server_config_path=code_config, path_extras=[])
    service.settings.code_server.start_timeout_s = timeout
    return service, store, port, bin_dir, code_config


async def settled(service, *, tunnel=None, timeout=20):
    async with asyncio.timeout(timeout):
        while True:
            snap = await service.snapshot()
            view = (
                snap.code_server
                if tunnel is None
                else (
                    snap.cloudflared.global_
                    if tunnel == "global"
                    else next(t for t in snap.cloudflared.tunnels if t.id == tunnel)
                )
            )
            if view.state not in {"starting", "stopping"}:
                return view
            await asyncio.sleep(0.05)


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False


async def gone(pid):
    async with asyncio.timeout(6):
        for _ in range(120):
            if not alive(pid):
                return
            await asyncio.sleep(0.05)
        assert not alive(pid)
