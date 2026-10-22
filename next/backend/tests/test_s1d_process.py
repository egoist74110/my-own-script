"""S1-D process stderr regression. Requires loopback bind; run outside sandbox."""

import socket

import httpx

from .independent.harness import Proc
from .test_s1_settings import PAT


def test_cr006_dev_memory_process_stderr_never_contains_pat(tmp_path):
    # Reserve a loopback port without listening: connections are refused, and another
    # process cannot claim the port before the request completes.
    with socket.socket() as unreachable:
        unreachable.bind(("127.0.0.1", 0))
        port = unreachable.getsockname()[1]
        backend = Proc(
            ["--dev"],
            env_extra={
                "TOOLBOX_CREDENTIALS": "memory",
                "TOOLBOX_DATA_DIR": str(tmp_path / "data"),
                "TOOLBOX_LEGACY_CONFIG_DIR": str(tmp_path / "legacy"),
            },
        ).start()
        try:
            with httpx.Client(
                base_url=backend.base, headers=backend.auth, timeout=15, trust_env=False
            ) as client:
                created = client.post(
                    "/api/ado/libraries",
                    json={
                        "revision": 0,
                        "name": "Isolated",
                        "base_url": f"http://127.0.0.1:{port}",
                    },
                )
                assert created.status_code == 200
                lid = created.json()["id"]
                saved = client.put(
                    f"/api/ado/libraries/{lid}/pat",
                    json={"revision": created.json()["revision"], "pat": PAT},
                )
                assert saved.status_code == 200
                result = client.post(
                    f"/api/ado/libraries/{lid}/test", json={"collection": "Default"}
                )
                assert result.status_code == 200
                # macOS may silently drop SYNs to a bound, non-listening port: the request then
                # ends as a connect timeout instead of a refusal. Either way no request succeeds.
                assert result.json()["category"] in {"network", "timeout"}
                assert PAT not in created.text + saved.text + result.text
            backend.close_stdin()
            assert backend.wait_exit(10) == 0
            backend.join_pumps()
            # Read after the process has exited, including shutdown logging.
            assert PAT not in backend.stderr_text()
        finally:
            backend.close()
