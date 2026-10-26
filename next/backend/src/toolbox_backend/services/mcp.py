"""S6-A MCP configuration owner; no Node or CLI configuration writes."""

import asyncio
import json
import os
import sys
from pathlib import Path

from toolbox_backend.adapters.config_store import stamp
from toolbox_backend.api.mcp_schemas import MCPSnapshot
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.mcp import MANAGED_NODE_VERSION, NODE_MIN_VERSION
from toolbox_backend.domain.settings import CredentialMeta


class McpService:
    def __init__(self, settings):
        self.settings = settings
        self.store = settings.store
        self._tests = {}

    async def snapshot(self):
        config = await self.store.read()
        return MCPSnapshot(
            revision=config.revision,
            ado=config.mcp.ado,
            runtime=config.mcp.runtime,
            node_min_version=NODE_MIN_VERSION,
            managed_node_version=MANAGED_NODE_VERSION,
            self_test_running="ado" in self._tests,
        )

    async def patch(self, body):
        def mutate(c):
            if body.mcp is not None:
                c.mcp = body.mcp
            for key in ("ado", "lark", "figma", "runtime"):
                value = getattr(body, key)
                if value is not None:
                    setattr(c.mcp, key, value)

        result = await self.store.update(body.revision, mutate)
        return {"revision": result.revision}

    @staticmethod
    def _account(kind, app_id, config):
        if kind == "figma_token":
            return "figma_token", "figma"
        app_id = app_id or config.mcp.lark.app_id
        if not app_id:
            raise SettingsError("validation_error", "请配置 Lark App ID", 422)
        return f"lark_app_secret:{app_id}", app_id

    async def credential(
        self,
        kind,
        revision,
        *,
        value=None,
        app_id=None,
        expiry_days=90,
        source="manual",
        login=None,
    ):
        def operation(tx):
            key, ref = self._account(kind, app_id, tx.config)
            previous = self.settings._get(key)

            def mutate(c):
                if value is None:
                    c.credentials.pop(key, None)
                else:
                    c.credentials[key] = CredentialMeta(
                        kind=kind, ref=ref, source=source, updated_at=stamp()
                    )
                if kind == "figma_token":
                    c.mcp.figma.token_set_at = stamp() if value else None
                    c.mcp.figma.expiry_days = expiry_days
                if login is not None:
                    c.mcp.lark.login = login

            # Validate the candidate before changing Keychain.
            candidate = tx.config.model_copy(deep=True)
            mutate(candidate)
            type(candidate).model_validate(candidate.model_dump(by_alias=True))
            if value is None:
                self.settings._delete(key)
            else:
                self.settings._set(key, value)
            try:
                tx.commit(mutate)
            except BaseException:
                # ConfigStore's commit point is replace; reconcile before rollback.
                disk = self.store._read()
                if disk.revision == tx.config.revision:
                    if previous is None:
                        self.settings._delete(key)
                    else:
                        self.settings._set(key, previous)
                raise
            return {"revision": tx.config.revision}

        return await self.store.run(revision, operation)

    async def import_credentials(self, body):
        from toolbox_backend.domain.mcp import LoginMetadata

        config = await self.store.read()
        if config.revision != body.revision:
            raise SettingsError("revision_conflict", "配置已更新", revision=config.revision)
        # Prepare reads before writes, never hold flock while old Keychain may prompt.
        values = []
        for kind in dict.fromkeys(body.kinds):
            key, _ = self._account(kind, body.app_id, config)
            try:
                value = await asyncio.to_thread(self.settings.legacy.get, key)
            except Exception:
                raise SettingsError("credential_backend_error", "凭据后端访问失败", 502) from None
            if not value:
                raise SettingsError("legacy_missing", "旧凭据不存在", 404)
            values.append((kind, value))
        login = None
        if "lark_app_secret" in body.kinds:
            path = self.settings.legacy_config.directory / "lark_login_state.json"

            def read_metadata():
                if not path.exists():
                    return None
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ValueError
                data = json.loads(raw)
                return LoginMetadata.model_validate(
                    {k: data[k] for k in ("logged_in_at", "scope") if k in data}
                )

            try:
                login = await asyncio.to_thread(read_metadata)
            except OSError, ValueError:
                raise SettingsError("validation_error", "旧登录元数据无效", 422) from None
        revision = body.revision
        for kind, value in values:
            result = await self.credential(
                kind,
                revision,
                value=value,
                app_id=body.app_id,
                source="imported",
                login=login if kind == "lark_app_secret" else None,
            )
            revision = result["revision"]
        return {"revision": revision}

    async def client_config(self, server, cli):
        config = await self.store.read()
        name = {"ado": "toolbox_ado", "figma": "toolbox_figma", "lark": "lark"}[server]
        if server == "lark":
            entry = {"url": f"http://localhost:{config.mcp.lark.port}/mcp"}
        else:
            entry = {
                "command": sys.executable,
                "args": [
                    "-m",
                    f"toolbox_backend.mcp.{server}_" + ("server" if server == "ado" else "wrapper"),
                    "--data-dir",
                    str(self.store.data_dir),
                ],
            }
        if cli == "codex":
            import json as j

            snippet = (
                f"[mcp_servers.{name}]\n"
                + "\n".join(f"{k} = {j.dumps(v, ensure_ascii=False)}" for k, v in entry.items())
                + "\n"
            )
        else:
            snippet = json.dumps({"mcpServers": {name: entry}}, ensure_ascii=False, indent=2)
        return dict(server=server, cli=cli, name=name, config=entry, snippet=snippet)

    async def import_policy(self, body):
        from toolbox_backend.mcp.policy import import_policy

        def operation(tx):
            import_policy(Path(body.path), self.store.data_dir)
            # No configuration change is needed; revision guards the explicit operation.
            return {"revision": tx.config.revision}

        return await self.store.run(body.revision, operation)

    async def self_test(self, body):
        from toolbox_backend.mcp.runner import CommandSpec, run_self_test

        if "ado" in self._tests:
            raise SettingsError("mcp_busy", "自检正在运行")
        task = asyncio.current_task()
        self._tests["ado"] = task
        try:
            return await run_self_test(
                CommandSpec(
                    name="ado",
                    argv=[
                        sys.executable,
                        "-m",
                        "toolbox_backend.mcp.ado_server",
                        "--data-dir",
                        str(self.store.data_dir),
                    ],
                ),
                self.store.data_dir,
                timeout_s=body.timeout_s,
            )
        finally:
            self._tests.pop("ado", None)

    async def close(self):
        tasks = list(self._tests.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
