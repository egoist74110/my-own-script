import json
import os
import signal
import subprocess
import sys

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.domain.settings import Config, Library, Project
from toolbox_backend.mcp.ado_server import AdoServer, handle_request


@pytest.fixture
def server(tmp_path):
    config = Config()
    config.ado.libraries = [Library(id="l", name="LIB", base_url="https://ado.invalid")]
    config.ado.projects = [Project(id="p", library_id="l", collection="C", project="P")]
    config.ado.active_library_id, config.ado.active_project_id = "l", "p"
    config.revision = 1
    ConfigStore(tmp_path)._write(config)
    credentials = MemoryCredentials()
    credentials.set("ado_pat:l", "fake-ado-pat-12345678")
    requests = []

    def response(req):
        requests.append(req)
        if req.url.path.endswith("/columns"):
            return httpx.Response(
                200, json={"value": [{"name": "Doing", "stateMappings": {"Bug": "Active"}}]}
            )
        if "/wiql" in req.url.path:
            return httpx.Response(200, json={"workItems": [{"id": i} for i in range(1, 205)]})
        if req.url.path.endswith("/workitems"):
            return httpx.Response(200, json={"value": [{"id": i} for i in range(1, 201)]})
        if "attachments" in req.url.path:
            return httpx.Response(200, content=b"hello")
        return httpx.Response(200, json={"id": 1, "fields": {"System.Title": "Hello"}, "value": []})

    return AdoServer(tmp_path, credentials, AdoRead(httpx.MockTransport(response))), requests


def unpack(value):
    assert not value.get("isError"), value
    return json.loads(value["content"][0]["text"])


def test_explicit_context_and_pat_and_disabled_create(server):
    s, _ = server
    assert "ado_create_work_item" not in [t["name"] for t in s.tools()]
    assert s.call("ado_create_work_item", {})["isError"]
    assert s.call("ado_get_work_item", {"work_item_id": 1})["isError"]
    s.credentials.values.clear()
    r = s.call("ado_get_work_item", {"library_id": "l", "project_id": "p", "work_item_id": 1})
    assert "请在设置中配置该库的 PAT" in r["content"][0]["text"]


def test_read_query_and_columns(server):
    s, requests = server
    args = {
        "library_name": " lib ",
        "project_name": "p",
        "work_item_id": 1,
        "wiql": "SELECT * FROM WorkItems",
        "team": "T",
        "board": "B",
        "column_name": "Doing",
    }
    assert unpack(s.call("ado_get_work_item", args))["work_item"]["id"] == 1
    unpack(s.call("ado_get_work_item_comments", args))
    r = unpack(s.call("ado_query_work_items", args))
    assert r["truncated"] and len(r["work_items"]) == 200
    unpack(s.call("ado_list_board_columns", args))
    unpack(s.call("ado_list_work_items_by_column", args))
    assert requests
    assert s.call("ado_query_work_items", {**args, "fields": ["bad/field"]})["isError"]


@pytest.mark.parametrize("version", ["2025-06-18", "2025-03-26", "2024-11-05", "evil"])
def test_protocol(server, version):
    s, _ = server
    r = handle_request(
        s,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": version}},
    )
    assert r["result"]["protocolVersion"] == ("2025-06-18" if version == "evil" else version)
    assert (
        handle_request(s, {"jsonrpc": "2.0", "id": 2, "method": "wat"})["error"]["code"] == -32601
    )


def test_create_blacklist_and_validate_only(server):
    s, requests = server
    c = s.store._read()
    c.mcp.ado.allow_create_work_item = True
    s.store._write(c)
    args = {
        "library_id": "l",
        "project_id": "p",
        "title": "New",
        "work_item_type": "Bug",
        "validate_only": True,
    }
    assert "ado_create_work_item" in [t["name"] for t in s.tools()]
    for key in (
        "System.Id",
        "System.Rev",
        "System.State",
        "System.Reason",
        "System.CreatedBy",
        "System.ChangedDate",
    ):
        assert s.call("ado_create_work_item", {**args, "extra_fields": {key: "evil"}})["isError"]
    unpack(s.call("ado_create_work_item", args))
    assert requests[-1].url.params["validateOnly"] == "true"
    assert requests[-1].headers["content-type"] == "application/json-patch+json"


def test_attachment_origin_size_symlink_and_cache(server, tmp_path):
    s, requests = server
    args = {
        "library_id": "l",
        "project_id": "p",
        "work_item_id": 1,
        "attachment_url": "https://ado.invalid/C/_apis/wit/attachments/abc?fileName=image.png",
    }
    r = unpack(s.call("ado_get_attachment", args))
    path = __import__("pathlib").Path(r["saved_path"])
    assert path.read_bytes() == b"hello" and path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert unpack(s.call("ado_get_attachment", args))["from_cache"]
    assert s.call("ado_get_attachment", {**args, "attachment_url": "http://ado.invalid/C/a"})[
        "isError"
    ]
    path.unlink()
    path.symlink_to(tmp_path / "elsewhere")
    assert s.call("ado_get_attachment", args)["isError"]


def test_policy_is_explicit_local_import(server, tmp_path):
    from toolbox_backend.mcp.policy import import_policy

    s, _ = server
    args = {
        "library_id": "l",
        "project_id": "p",
        "work_item_id": 1,
        "target_paths": ["secrets/a.py"],
    }
    assert s.call("ado_evaluate_change_policy", args)["isError"]
    source = tmp_path / "baseline.yaml"
    source.write_text("default_decision: allow\nforbidden_paths: [secrets]\n")
    import_policy(source, tmp_path)
    assert unpack(s.call("ado_evaluate_change_policy", args))["decision"] == "deny"


@pytest.mark.parametrize("bad", ["wide", "link", "file", "missing"])
def test_cli_rejects_unsafe_data_dir(tmp_path, bad):
    target = tmp_path / "data"
    target.mkdir(mode=0o700)
    if bad == "wide":
        target.chmod(0o755)
    if bad == "link":
        link = tmp_path / "link"
        link.symlink_to(target)
        target = link
    if bad == "file":
        target = tmp_path / "file"
        target.touch()
    if bad == "missing":
        target = tmp_path / "missing"
    r = subprocess.run(
        [sys.executable, "-m", "toolbox_backend.mcp.ado_server", "--data-dir", str(target)],
        capture_output=True,
        timeout=5,
    )
    assert r.returncode == 2


@pytest.mark.parametrize("ending", ["eof", "term", "int"])
def test_cli_stdio_protocol_and_exit(tmp_path, ending):
    p = subprocess.Popen(
        [sys.executable, "-m", "toolbox_backend.mcp.ado_server", "--data-dir", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for raw, code in [(b"not-json\n", -32700), (b"x" * (4 * 1024 * 1024 + 1) + b"\n", -32600)]:
            p.stdin.write(raw)
            p.stdin.flush()
            assert json.loads(p.stdout.readline())["error"]["code"] == code
        if ending == "eof":
            p.stdin.close()
        else:
            p.send_signal(signal.SIGTERM if ending == "term" else signal.SIGINT)
        assert p.wait(timeout=4) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=3)
        for stream in (p.stdin, p.stdout, p.stderr):
            stream.close()


def test_cache_lru_expiry_and_size_limit(tmp_path):
    import time

    from toolbox_backend.mcp.cache import AttachmentCache

    cache = AttachmentCache(tmp_path)

    def put(key, data):
        return cache.store(
            "l", 1, "https://ado.invalid/" + key, lambda: data, max_bytes=10, total_bytes=10
        )[0]

    first = put("a", b"123456")
    second = put("b", b"67890")
    assert not first.exists() and second.exists()
    os.utime(second, (time.time() - 15 * 86400,) * 2)
    third = put("c", b"123")
    assert not second.exists() and third.exists()
    with pytest.raises(ValueError):
        put("large", b"x" * 11)


def test_server_exits_when_parent_changes(tmp_path):
    import select

    bootstrap = """import subprocess,sys,time
p=subprocess.Popen([sys.executable,'-m','toolbox_backend.mcp.ado_server','--data-dir',sys.argv[1]])
print(p.pid,flush=True)
time.sleep(120)
"""
    parent = subprocess.Popen(
        [sys.executable, "-c", bootstrap, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child = None
    try:
        child = int(parent.stdout.readline())
        parent.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        parent.stdin.flush()
        assert json.loads(parent.stdout.readline())["result"] == {}
        parent.kill()
        parent.wait(timeout=3)
        assert select.select([parent.stdout], [], [], 3)[0]
        assert parent.stdout.read() == b""
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        if child:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for stream in (parent.stdin, parent.stdout, parent.stderr):
            stream.close()


def test_sigterm_interrupts_inflight_tool(tmp_path):
    boot = """import sys,time
from toolbox_backend.mcp import ado_server as m
def block(*_):
 print('busy',file=sys.stderr,flush=True)
 time.sleep(10)
m.AdoServer.call=block
sys.exit(m.main())
"""
    p = subprocess.Popen(
        [sys.executable, "-c", boot, "--data-dir", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        p.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}\n')
        p.stdin.flush()
        assert p.stderr.readline() == b"busy\n"
        p.terminate()
        assert p.wait(timeout=1) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=3)
        for stream in (p.stdin, p.stdout, p.stderr):
            stream.close()


def test_policy_import_is_atomic_before_fsync(server, tmp_path, monkeypatch):
    from toolbox_backend.mcp import policy

    s, _ = server
    source = tmp_path / "input.yaml"
    source.write_text("default_decision: review\n")
    original = policy.os.fsync

    def check(fd):
        assert not (tmp_path / "mcp/ai_change_policy.yaml").exists()
        original(fd)

    monkeypatch.setattr(policy.os, "fsync", check)
    policy.import_policy(source, tmp_path)


def test_attachment_remote_limit_and_intermediate_symlink(server, tmp_path):
    s, _ = server
    config = s.store._read()
    config.mcp.ado.attachment_max_mb = 1
    s.store._write(config)
    s.ado = AdoRead(
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * (1024 * 1024 + 1)))
    )
    args = {
        "library_id": "l",
        "project_id": "p",
        "work_item_id": 1,
        "attachment_url": "https://ado.invalid/C/_apis/wit/attachments/large",
    }
    assert s.call("ado_get_attachment", args)["isError"]
    import shutil

    shutil.rmtree(tmp_path / "mcp/ado-attachments")
    (tmp_path / "mcp/ado-attachments").symlink_to(tmp_path)
    assert s.call("ado_get_attachment", args)["isError"]


def test_data_directory_owner_is_checked(tmp_path, monkeypatch):
    from toolbox_backend.mcp import runner

    monkeypatch.setattr(runner.os, "getuid", lambda: tmp_path.stat().st_uid + 1)
    with pytest.raises(ValueError):
        runner.validate_data_dir(tmp_path)
