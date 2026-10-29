"""WP-11 / D01：附件与内联图片的 PAT 只发给当前 library 的同源 URL（全离线）。"""

import base64
import socket
from types import SimpleNamespace

import httpx
import keyring
import pytest

from app_ado import ado_work_item_http as http_mod
from app_ado import mcp_ado_work_items_server as mcp_mod
from app_ado import tg_work_items_bridge as tg_mod
from app_ado import work_item_view
from app_ado.ado_work_item_http import (
    AttachmentOriginError,
    download_authenticated_file,
    fetch_attachment_bytes,
)

PAT = "FAKE-ADO-PAT-attachment-security"
AUTH = "Basic " + base64.b64encode(f":{PAT}".encode()).decode()
BASE = "https://ado.example.test/tfs"
PNG = b"\x89PNG\r\n\x1a\nfixture"


@pytest.fixture(autouse=True)
def reject_real_side_effects(monkeypatch):
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("unexpected network or credential access")
        raise AssertionError(attempts[-1])

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    for name in ("get_password", "set_password", "delete_password", "get_credential"):
        monkeypatch.setattr(keyring, name, forbidden)
    yield
    assert attempts == []


@pytest.fixture
def wire(monkeypatch):
    """安装 MockTransport；返回 (handler 设置函数, 已收到请求列表)。"""
    seen: list[httpx.Request] = []
    state = {"handler": lambda req: httpx.Response(200, content=PNG, headers={"content-type": "image/png"})}
    real_client = httpx.Client

    def respond(request):
        seen.append(request)
        return state["handler"](request)

    monkeypatch.setattr(
        http_mod.httpx, "Client", lambda *a, **kw: real_client(*a, **kw, transport=httpx.MockTransport(respond))
    )

    def set_handler(fn):
        state["handler"] = fn

    return set_handler, seen


def _redirect(to):
    return httpx.Response(302, headers={"location": to})


SAME = f"{BASE}/_apis/wit/attachments/abc.png"


def test_same_origin_attachment_is_authenticated(wire):
    _, seen = wire
    data, ct = fetch_attachment_bytes(SAME, pat=PAT, trusted_base_url=BASE)
    assert data == PNG and ct == "image/png"
    assert len(seen) == 1 and seen[0].headers["authorization"] == AUTH


def test_origin_compare_is_case_insensitive_and_default_port_aware(wire):
    _, seen = wire
    fetch_attachment_bytes("https://ADO.Example.TEST:443/x.png", pat=PAT, trusted_base_url=BASE)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/a.png",
        "https://ado.example.test:8443/a.png",
        "http://ado.example.test/a.png",
        "https://user:pw@ado.example.test/a.png",
        "https://ado.example.test@evil.invalid/a.png",
        "ftp://ado.example.test/a.png",
        "file:///etc/passwd",
        "//ado.example.test/a.png",
        "",
    ],
)
def test_untrusted_initial_url_sends_no_request(wire, url):
    _, seen = wire
    with pytest.raises(AttachmentOriginError):
        fetch_attachment_bytes(url, pat=PAT, trusted_base_url=BASE)
    assert seen == []


def test_same_origin_redirect_keeps_auth(wire):
    set_handler, seen = wire
    set_handler(
        lambda req: _redirect("/tfs/blob/final.png")
        if req.url.path.endswith("abc.png")
        else httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    )
    data, _ = fetch_attachment_bytes(SAME, pat=PAT, trusted_base_url=BASE)
    assert data == PNG
    assert [r.url.path for r in seen] == ["/tfs/_apis/wit/attachments/abc.png", "/tfs/blob/final.png"]
    assert all(r.headers["authorization"] == AUTH for r in seen)


@pytest.mark.parametrize(
    "target",
    [
        "https://cdn.evil.invalid/signed.png",
        "https://ado.example.test:9999/x.png",
        "http://ado.example.test/x.png",  # https -> http 降级
        "https://u:p@ado.example.test/x.png",
        "ftp://ado.example.test/x.png",
    ],
)
def test_cross_origin_redirect_terminates_without_following(wire, target):
    set_handler, seen = wire
    set_handler(lambda req: _redirect(target))
    with pytest.raises(AttachmentOriginError):
        fetch_attachment_bytes(SAME, pat=PAT, trusted_base_url=BASE)
    assert len(seen) == 1  # 只有同源首跳；越界目标根本没发


def test_redirect_hop_limit(wire):
    set_handler, seen = wire
    set_handler(lambda req: _redirect(str(req.url.copy_with(path=req.url.path + "x"))))
    with pytest.raises(AttachmentOriginError, match="超过"):
        fetch_attachment_bytes(SAME, pat=PAT, trusted_base_url=BASE)
    assert len(seen) == http_mod._MAX_ATTACHMENT_REDIRECTS + 1


def test_http_error_still_reported(wire):
    set_handler, _ = wire
    set_handler(lambda req: httpx.Response(404, text="nope"))
    with pytest.raises(RuntimeError, match="HTTP 404"):
        fetch_attachment_bytes(SAME, pat=PAT, trusted_base_url=BASE)


def test_download_authenticated_file_untrusted_writes_nothing(wire, tmp_path):
    _, seen = wire
    dest = tmp_path / "sub" / "a.png"
    with pytest.raises(AttachmentOriginError):
        download_authenticated_file(
            "https://evil.invalid/a.png", pat=PAT, dest_path=dest, trusted_base_url=BASE
        )
    assert seen == [] and not dest.exists()
    p = download_authenticated_file(SAME, pat=PAT, dest_path=dest, trusted_base_url=BASE)
    assert p.read_bytes() == PNG


# ---------------- 三个入口一致性 ----------------

EXTERNAL = "https://evil.invalid/shot.png"


def test_ui_entry_skips_external_and_downloads_same_origin(wire, monkeypatch, tmp_path):
    _, seen = wire
    monkeypatch.setattr(work_item_view, "view_cache_dir", lambda: tmp_path)
    out = work_item_view.download_images_to_cache(
        [EXTERNAL, SAME], pat=PAT, sub_key="1", trusted_base_url=BASE
    )
    assert list(out) == [SAME]
    assert [r.url.host for r in seen] == ["ado.example.test"]
    assert seen[0].headers["authorization"] == AUTH


def test_ui_entry_cross_origin_redirect_yields_no_image(wire, monkeypatch, tmp_path):
    set_handler, seen = wire
    set_handler(lambda req: _redirect("https://cdn.evil.invalid/s.png"))
    monkeypatch.setattr(work_item_view, "view_cache_dir", lambda: tmp_path)
    out = work_item_view.download_images_to_cache([SAME], pat=PAT, sub_key="1", trusted_base_url=BASE)
    assert out == {} and len(seen) == 1


def test_tg_entry_skips_external_and_sends_no_pat_out(wire, monkeypatch):
    _, seen = wire
    item = SimpleNamespace(id=7, title="t", state=None, work_item_type=None, assigned_to=None,
                           url=None, relations=[], fields={"System.Description": f'<img src="{EXTERNAL}"><img src="{SAME}">'})
    lib = SimpleNamespace(id="lib", name="L", base_url=BASE)
    proj = SimpleNamespace(collection="c", project="p")
    bridge = tg_mod.WorkItemsBridge.__new__(tg_mod.WorkItemsBridge)
    monkeypatch.setattr(bridge, "_settings", lambda: None, raising=False)
    monkeypatch.setattr(bridge, "_state", lambda chat_id: {}, raising=False)
    monkeypatch.setattr(bridge, "_fetch_item", lambda st, wid: (None, item, lib, proj, PAT), raising=False)
    monkeypatch.setattr(tg_mod, "get_work_item_comments", lambda *a, **k: [])
    result = bridge.handle_view("chat", 7)
    assert result["error"] is None
    assert len(result["photos"]) == 1
    assert [r.url.host for r in seen] == ["ado.example.test"]


def test_mcp_entry_rejects_external_with_clear_error(wire, monkeypatch, tmp_path):
    _, seen = wire
    lib = SimpleNamespace(id="lib", name="L", base_url=BASE)
    proj = SimpleNamespace(project="p", collection="c")
    monkeypatch.setattr(mcp_mod, "_resolve_context", lambda args: (lib, proj, PAT))
    monkeypatch.setattr(mcp_mod, "_ATTACHMENT_CACHE_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="拒绝|不同源"):
        mcp_mod._tool_ado_get_attachment({"attachment_url": EXTERNAL})
    assert seen == []
    # 同 host:port 但 scheme 不同：越过旧的 netloc 预检，必须由底层拒绝
    with pytest.raises(RuntimeError, match="不同源"):
        mcp_mod._tool_ado_get_attachment({"attachment_url": "http://ado.example.test/tfs/a.png"})
    assert seen == []


def test_mcp_entry_cross_origin_redirect_terminates(wire, monkeypatch, tmp_path):
    set_handler, seen = wire
    set_handler(lambda req: _redirect("https://cdn.evil.invalid/s.png"))
    lib = SimpleNamespace(id="lib", name="L", base_url=BASE)
    proj = SimpleNamespace(project="p", collection="c")
    monkeypatch.setattr(mcp_mod, "_resolve_context", lambda args: (lib, proj, PAT))
    monkeypatch.setattr(mcp_mod, "_ATTACHMENT_CACHE_ROOT", tmp_path)
    with pytest.raises(AttachmentOriginError):
        mcp_mod._tool_ado_get_attachment({"attachment_url": SAME})
    assert len(seen) == 1


# ---------------- 攻击者视角追加用例（WP-11 独立测试者） ----------------

import re  # noqa: E402  (追加段内局部使用)

HTTP_BASE = "http://ado.example.test/tfs"


def test_relative_and_dotdot_redirects_stay_same_origin_and_reach_exact_hop_limit(wire):
    """相对路径 / ../ 重定向保持同源并保留 PAT；恰好 5 跳后 200 必须成功（边界不误杀）。"""
    set_handler, seen = wire

    def handler(req):
        m = re.fullmatch(r"/tfs/h/(\d+)", req.url.path)
        if m is None:
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        n = int(m.group(1))
        if n < http_mod._MAX_ATTACHMENT_REDIRECTS:
            return _redirect(f"../h/{n + 1}")
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    set_handler(handler)
    data, ct = fetch_attachment_bytes(f"{BASE}/h/0", pat=PAT, trusted_base_url=BASE)
    assert data == PNG and ct == "image/png"
    assert [r.url.path for r in seen] == [f"/tfs/h/{i}" for i in range(http_mod._MAX_ATTACHMENT_REDIRECTS + 1)]
    assert all(r.url.host == "ado.example.test" for r in seen)
    assert all(r.headers["authorization"] == AUTH for r in seen)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("location", ["//evil.invalid/x", "//ado.example.test.evil.invalid/x"])
def test_protocol_relative_redirect_to_other_host_terminates_for_every_redirect_status(wire, status, location):
    set_handler, seen = wire
    set_handler(lambda req: httpx.Response(status, headers={"location": location}))
    with pytest.raises(AttachmentOriginError):
        fetch_attachment_bytes(SAME, pat=PAT, trusted_base_url=BASE)
    assert len(seen) == 1  # 只有同源首跳；协议相对的越界目标根本没发


def test_http_trusted_base_same_origin_http_redirect_keeps_auth(wire):
    """可信 base 本身是 http 时，同源 http 重定向应继续且保持 Authorization；https 升级视为跨 origin 拒绝。"""
    set_handler, seen = wire
    start = f"{HTTP_BASE}/_apis/wit/attachments/abc.png"
    set_handler(
        lambda req: _redirect("/tfs/blob/final.png")
        if req.url.path.endswith("abc.png")
        else httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    )
    data, _ = fetch_attachment_bytes(start, pat=PAT, trusted_base_url=HTTP_BASE)
    assert data == PNG
    assert [r.url.scheme for r in seen] == ["http", "http"]
    assert all(r.headers["authorization"] == AUTH for r in seen)

    seen.clear()
    set_handler(lambda req: _redirect("https://ado.example.test/tfs/blob/final.png"))
    with pytest.raises(AttachmentOriginError):
        fetch_attachment_bytes(start, pat=PAT, trusted_base_url=HTTP_BASE)
    assert len(seen) == 1


def test_ipv6_and_dotted_host_variants_follow_exact_origin_rule(wire):
    """IPv6 同 origin 放行；端口不同、末尾点、后缀拼接等 host 变体一律不发请求。"""
    _, seen = wire
    v6_base = "https://[::1]/tfs"
    data, _ = fetch_attachment_bytes("https://[::1]/tfs/a.png", pat=PAT, trusted_base_url=v6_base)
    assert data == PNG and len(seen) == 1
    assert seen[0].headers["authorization"] == AUTH

    variants = [
        "https://[::1]:8443/tfs/a.png",
        "https://[::2]/tfs/a.png",
        "https://ado.example.test./tfs/a.png",  # 末尾点：精确比较，拒绝（fail closed）
        "https://ado.example.test.evil.invalid/tfs/a.png",
        "https://evil.invalid/tfs/a.png?host=ado.example.test",
    ]
    for url in variants:
        with pytest.raises(AttachmentOriginError):
            fetch_attachment_bytes(url, pat=PAT, trusted_base_url=v6_base if "[" in url else BASE)
    assert len(seen) == 1  # 变体全部未发出


@pytest.mark.parametrize(
    "location",
    [
        "https://u:p@ado.example.test/tfs/x.png",  # 同 host 但带 userinfo
        "https://:@ado.example.test/tfs/x.png",
    ],
)
def test_userinfo_in_redirect_terminates_even_when_host_is_same(wire, location):
    set_handler, seen = wire
    set_handler(lambda req: _redirect(location))
    with pytest.raises(AttachmentOriginError):
        fetch_attachment_bytes(SAME, pat=PAT, trusted_base_url=BASE)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "bad_base",
    ["", "not a url", "ftp://ado.example.test/tfs", "https://", "https://u:p@ado.example.test/tfs", "https://ado.example.test:99999/tfs"],
)
def test_illegal_trusted_base_rejects_before_any_request(wire, bad_base):
    _, seen = wire
    with pytest.raises(AttachmentOriginError):
        fetch_attachment_bytes(SAME, pat=PAT, trusted_base_url=bad_base)
    assert seen == []


@pytest.mark.parametrize(
    "url",
    [
        "https://ado.example.test\\@evil.invalid/a.png",  # 反斜杠混淆：userinfo 解析差异
        "https:\\\\evil.invalid/a.png",  # 无 netloc
        "https://evil.invalid\\.ado.example.test/a.png",  # 反斜杠拼接伪装成子域
    ],
)
def test_backslash_parser_differential_is_rejected_without_request(wire, url):
    _, seen = wire
    with pytest.raises(AttachmentOriginError):
        fetch_attachment_bytes(url, pat=PAT, trusted_base_url=BASE)
    assert seen == []


def test_escape_after_several_same_origin_hops_is_caught_at_the_escaping_hop(wire):
    """前两跳同源（保持 PAT），第三跳才越界：越界目标不得被请求，之前的同源跳必须是 PAT 发出的。"""
    set_handler, seen = wire

    def handler(req):
        if req.url.path == "/tfs/hop/0":
            return _redirect("1")  # 相对路径
        if req.url.path == "/tfs/hop/1":
            return _redirect("https://cdn.evil.invalid/steal.png")
        return httpx.Response(200, content=b"SHOULD-NOT-BE-REACHED")

    set_handler(handler)
    with pytest.raises(AttachmentOriginError):
        fetch_attachment_bytes(f"{BASE}/hop/0", pat=PAT, trusted_base_url=BASE)
    assert [r.url.path for r in seen] == ["/tfs/hop/0", "/tfs/hop/1"]
    assert all(r.url.host == "ado.example.test" for r in seen)
    assert all(r.headers["authorization"] == AUTH for r in seen)
