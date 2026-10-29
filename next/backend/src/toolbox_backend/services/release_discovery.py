"""使用已有项目凭据发现发布候选项，不写入任何配置。"""

import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from toolbox_backend.adapters.ado_read import AdoFailure
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.services.work_items import outbound

QUEUE_VERSIONS = ("7.1-preview.1", "6.0-preview.1", "5.1-preview.1", "5.0-preview.1")


def parse_remote(remote):
    """返回主机、显式端口、集合、项目、仓库与去凭据的远端。"""
    try:
        scp = re.fullmatch(
            r"[^/@:]+@([^/:]+):v3/([^/]+)/([^/]+)/([^/]+)/?",
            remote.split("?", 1)[0].split("#", 1)[0],
        )
        if scp:
            host, collection, project, repo = scp.groups()
            return (
                host.lower(),
                None,
                *map(unquote, (collection, project, repo)),
                (f"{host}:v3/{collection}/{project}/{repo}"),
            )
        url = urlsplit(remote)
        parts = url.path.strip("/").split("/")
        if (
            url.scheme not in {"http", "https", "ssh"}
            or not url.hostname
            or len(parts) < 4
            or parts[-2].lower() != "_git"
            or not all(parts[-4:])
        ):
            raise ValueError
        collection, project, _, repo = map(unquote, parts[-4:])
        # 查询串和片段也可能携带凭据；发现无需保留。
        safe = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
        return url.hostname.lower(), url.port, collection, project, repo, safe
    except ValueError:
        raise SettingsError("remote_not_ado", "远端地址不是支持的 ADO 仓库地址", 422) from None


def read_remote(path):
    """隔离 Git 环境，仅读取仓库与远端，不执行仓库脚本。"""

    try:
        path = Path(path).expanduser().resolve()
    except OSError, ValueError, RuntimeError:
        raise SettingsError("not_git_repo", "仓库路径无效", 422) from None

    def git(*args, optional=False):
        try:
            result = subprocess.run(
                [
                    "/usr/bin/git",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(path),
                    *args,
                ],
                env={
                    "PATH": "/usr/bin:/bin",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_TERMINAL_PROMPT": "0",
                },
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except OSError, ValueError, UnicodeError, subprocess.TimeoutExpired:
            raise SettingsError("not_git_repo", "无法读取 Git 仓库", 422) from None
        if result.returncode and not optional:
            raise SettingsError("not_git_repo", "路径不是 Git 仓库", 422)
        return result.stdout.strip() if result.returncode == 0 else ""

    if not path.is_dir():
        raise SettingsError("not_git_repo", "路径不是 Git 仓库目录", 422)
    git("rev-parse", "--git-dir")
    remotes = git("remote").splitlines()
    if not remotes:
        raise SettingsError("no_remote", "仓库没有配置远端", 422)
    name = "origin" if "origin" in remotes else remotes[0]
    remote = git("config", "--get", f"remote.{name}.url", optional=True)
    if not remote:
        raise SettingsError("no_remote", "仓库没有可读取的远端地址", 422)
    return path, remote


def object_field(payload, key):
    result = payload.get(key) or {}
    if not isinstance(result, dict):
        raise SettingsError("ado_unreachable", "ADO 返回的数据格式无效", 502)
    return result


def rows(payload, key="value"):
    result = payload.get(key, [] if key != "value" else None)
    if not isinstance(result, list) or any(not isinstance(x, dict) for x in result):
        raise SettingsError("ado_unreachable", "ADO 返回的数据格式无效", 502)
    return result


def item(row):
    if not row.get("id") or not isinstance(row.get("name"), str):
        raise SettingsError("ado_unreachable", "ADO 返回的身份字段无效", 502)
    return {"id": str(row["id"]), "name": row["name"]}


class ReleaseDiscoveryService:
    def __init__(self, work_items):
        self.work_items = work_items
        self.store = work_items.settings.store

    async def source(self, project_id):
        try:
            return await self.work_items.snapshot(project_id)
        except SettingsError as exc:
            if exc.code == "no_credential":
                raise SettingsError("pat_missing", "请先为项目所属库配置 PAT", 409) from None
            raise

    async def request(self, ctx, suffix, *, params=None, versions=("7.0",), queues=False):
        project, library, pat = ctx
        for index, version in enumerate(versions):
            try:
                return await outbound(
                    self.work_items.http.request_json,
                    library,
                    pat,
                    "GET",
                    [project.collection, project.project, "_apis", *suffix],
                    {"api-version": version, **(params or {})},
                )
            except AdoFailure as exc:
                if index < len(versions) - 1 and (
                    exc.version_unsupported or (queues and exc.status in {400, 404})
                ):
                    continue
                if exc.category == "not_found":
                    raise SettingsError("ado_not_found", "ADO 资源或接口不存在", 404) from None
                if exc.category == "no_credential":
                    raise SettingsError("pat_missing", "请先配置 PAT", 409) from None
                raise SettingsError(
                    "ado_unreachable", "ADO 请求失败，请检查连接与权限", 502
                ) from None

    async def repo(self, local_repo_path):
        # outbound 同样负责取消时等待读取线程退出，避免遗留子进程。
        path, remote = await outbound(read_remote, local_repo_path)
        host, port, collection, project_name, repo_name, safe = parse_remote(remote)
        config = await self.store.read()
        libraries = {lib.id: lib for lib in config.ado.libraries}
        matches = []
        for project in config.ado.projects:
            url = urlsplit(libraries[project.library_id].base_url)
            if (
                (url.hostname.lower(), url.port) == (host, port)
                and project.collection.casefold() == collection.casefold()
                and project.project.casefold() == project_name.casefold()
            ):
                matches.append(project)
        result = {"local_repo_path": str(path), "remote_url": safe}
        if len(matches) != 1:
            return {**result, "reason": "project_not_matched"}
        project = matches[0]
        ctx = await self.source(project.id)
        repo = await self.request(ctx, ["git", "repositories", repo_name])
        found = item(repo)
        existing = next(
            (
                c.id
                for c in config.tasks.release_configs
                if c.repo_id and c.repo_id.casefold() == found["id"].casefold()
            ),
            None,
        )
        return {
            **result,
            "project_id": project.id,
            "project_label": f"{project.collection}/{project.project}",
            "repo_id": found["id"],
            "repo_name": found["name"],
            "default_branch": self.default_branch(repo),
            "suggested_name": found["name"],
            "existing_config_id": existing,
        }

    @staticmethod
    def default_branch(repo):
        value = repo.get("defaultBranch")
        return value.removeprefix("refs/heads/") if isinstance(value, str) and value else None

    async def branches(self, project_id, repo_id):
        ctx = await self.source(project_id)
        repo = await self.request(ctx, ["git", "repositories", repo_id])
        refs = rows(
            await self.request(
                ctx, ["git", "repositories", repo_id, "refs"], params={"filter": "heads/"}
            )
        )
        default = self.default_branch(repo)
        names = {
            r["name"].removeprefix("refs/heads/")
            for r in refs
            if isinstance(r.get("name"), str) and r["name"].startswith("refs/heads/")
        }
        return {
            "branches": sorted(names, key=lambda n: (n != default, n)),
            "default_branch": default,
        }

    async def targets(self, project_id, repo_id):
        ctx = await self.source(project_id)
        definitions = rows(
            await self.request(
                ctx,
                ["build", "definitions"],
                params={
                    "repositoryId": repo_id,
                    "repositoryType": "TfsGit",
                    "includeAllProperties": "true",
                },
            )
        )
        builds = []
        for row in definitions:
            if str(object_field(row, "repository").get("id", "")).casefold() != repo_id.casefold():
                continue
            builds.append(
                {
                    **item(row),
                    "kind": "pipeline"
                    if object_field(row, "process").get("type") == 2
                    else "build",
                }
            )
        ids = {b["id"] for b in builds}
        definitions = rows(
            await self.request(
                ctx,
                ["release", "definitions"],
                params={"$expand": "artifacts,environments"},
                versions=("6.0", "7.0"),
            )
        )
        releases = []
        for row in definitions:
            linked = list(
                dict.fromkeys(
                    str(
                        object_field(object_field(a, "definitionReference"), "definition").get(
                            "id", ""
                        )
                    )
                    for a in rows(row, "artifacts")
                    if str(a.get("type", "")).casefold() == "build"
                )
            )
            linked = [ident for ident in linked if ident in ids]
            if linked:
                releases.append(
                    {
                        **item(row),
                        "build_definition_ids": linked,
                        "environments": [item(e) for e in rows(row, "environments")],
                    }
                )
        pairs = [(b, r) for b in builds for r in releases if b["id"] in r["build_definition_ids"]]
        counts = Counter(r["name"] for _, r in pairs)
        targets = []
        for build, release in pairs:
            name = release["name"]
            if counts[name] > 1:
                name += f"（{build['name']}）"
            targets.append(
                {
                    "name": name,
                    "build_kind": build["kind"],
                    "build_id": build["id"],
                    "build_name": build["name"],
                    "release_id": release["id"],
                    "release_name": release["name"],
                    "release_stage_ids": [e["id"] for e in release["environments"]],
                    "release_stage_names": [e["name"] for e in release["environments"]],
                }
            )
        return {"builds": builds, "releases": releases, "suggested_targets": targets}

    async def queues(self, project_id):
        ctx = await self.source(project_id)
        data = await self.request(
            ctx,
            ["distributedtask", "queues"],
            params={"actionFilter": "Use"},
            versions=QUEUE_VERSIONS,
            queues=True,
        )
        return {"queues": [item(row) for row in rows(data)]}
