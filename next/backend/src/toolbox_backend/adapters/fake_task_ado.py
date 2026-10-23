"""In-memory dev task endpoints. Only fake_ado installs this handler."""

import copy
import json
import threading

import httpx


class FakeTaskADO:
    def __init__(self, *, project="示例项目", repo="demo-repo", commit="a" * 40):
        self.project, self.repo, self.commit = project, repo, commit
        self.lock = threading.Lock()
        self.builds, self.pipelines, self.releases, self.writes = {}, {}, {}, []
        self.next_build, self.next_release = 100, 200
        for definition in (11, 12, 13):
            self.builds[definition] = self.build(definition, definition)
            for ident in (definition * 10, definition * 10 + 1):
                self.releases[ident] = self.release(ident, definition, definition, historical=True)

    def build(self, ident, definition):
        return {
            "id": ident,
            "project": {"name": self.project},
            "repository": {"id": self.repo},
            "definition": {"id": definition},
            "sourceBranch": "refs/heads/main",
            "sourceVersion": self.commit,
            "status": "completed",
            "result": "succeeded",
            "queue": {"id": 1},
        }

    def artifact(self, definition):
        return {
            "alias": "_demo",
            "type": "Build",
            "definitionReference": {
                "project": {"name": self.project, "id": self.project},
                "definition": {"id": str(definition), "name": "Demo"},
            },
        }

    def release(self, ident, definition, build, *, historical=False, description=""):
        return {
            "id": ident,
            "releaseDefinition": {"id": definition},
            "description": description,
            "createdOn": "2026-10-23T00:00:00Z",
            "artifacts": [{**self.artifact(definition), "instanceReference": {"id": str(build)}}],
            "environments": [
                {
                    "id": ident * 10 + stage,
                    "definitionEnvironmentId": stage,
                    "name": name,
                    "conditions": [{"conditionType": "manual"}],
                    "status": "succeeded" if historical else "notStarted",
                    "deploySteps": [{"attempt": 1}] if historical else [],
                }
                for stage, name in ((1, "演示"), (2, "未选环境"))
            ],
        }

    def __call__(self, request):
        with self.lock:
            return self.handle(request)

    def handle(self, request):
        path = request.url.path
        if "/_apis/" not in path:
            return None
        parts = path.split("/_apis/", 1)[1].split("/")
        method = request.method
        if parts[0] not in {"build", "pipelines", "release", "git"}:
            return None
        if method != "GET":
            self.writes.append((method, path, json.loads(request.content)))
        body = json.loads(request.content) if request.content else {}
        if parts[0] == "git" and parts[-1] == "refs":
            payload = {"value": [{"name": "refs/heads/main", "objectId": self.commit}]}
        elif parts[:2] == ["build", "definitions"]:
            ident = int(parts[2])
            payload = {
                "id": ident,
                "repository": {"id": self.repo},
                "project": {"name": self.project},
            }
        elif parts[0] == "pipelines":
            definition = int(parts[1])
            if method == "POST":
                self.next_build += 1
                ident = self.next_build
                b = self.build(ident, definition)
                b["sourceVersion"] = body["resources"]["repositories"]["self"]["version"]
                self.builds[ident] = b
                run_id = ident + 1000
                self.pipelines[run_id] = {
                    "id": run_id,
                    "_links": {
                        "build": {
                            "href": str(request.url).split("/_apis/")[0]
                            + f"/_apis/build/builds/{ident}"
                        }
                    },
                }
                payload = self.pipelines[run_id]
            else:
                payload = self.pipelines.get(int(parts[-1]), {})
        elif parts[:2] == ["build", "builds"]:
            if method == "POST":
                self.next_build += 1
                payload = self.build(self.next_build, body["definition"]["id"])
                payload["sourceVersion"] = body["sourceVersion"]
                payload["queue"] = body.get("queue", {"id": 1})
                self.builds[payload["id"]] = payload
            elif len(parts) == 2:
                definition = int(request.url.params["definitions"])
                payload = {
                    "value": sorted(
                        [x for x in self.builds.values() if x["definition"]["id"] == definition],
                        key=lambda x: x["id"],
                        reverse=True,
                    )[: int(request.url.params.get("$top", 20))]
                }
            else:
                payload = self.builds.get(int(parts[2]), {})
                if method == "PATCH":
                    payload.update(status="completed", result="canceled")
        elif parts[:2] == ["release", "definitions"]:
            ident = int(parts[2])
            payload = {
                "id": ident,
                "artifacts": [self.artifact(ident)],
                "environments": [{"id": 1, "name": "演示"}, {"id": 2, "name": "未选环境"}],
            }
        elif parts[:2] == ["release", "releases"]:
            if method == "POST":
                self.next_release += 1
                ident = self.next_release
                payload = self.release(
                    ident,
                    body["definitionId"],
                    int(body["artifacts"][0]["instanceReference"]["id"]),
                    description=body["description"],
                )
                self.releases[ident] = payload
            elif len(parts) == 2:
                definition = int(request.url.params["definitionId"])
                rows = sorted(
                    [
                        x
                        for x in self.releases.values()
                        if x["releaseDefinition"]["id"] == definition
                    ],
                    key=lambda x: x["id"],
                    reverse=True,
                )
                payload = {"value": rows[: int(request.url.params.get("$top", 6))]}
            else:
                payload = self.releases.get(int(parts[2]), {})
                if method == "PATCH":
                    env = next(e for e in payload["environments"] if e["id"] == int(parts[4]))
                    env["deploySteps"].append({"attempt": len(env["deploySteps"]) + 1})
                    definition = payload["releaseDefinition"]["id"]
                    env["status"] = (
                        "rejected"
                        if definition == 12
                        else "inProgress"
                        if definition == 13
                        else "succeeded"
                    )
                    payload = env
                    if definition == 13:
                        raise httpx.ReadError("dev simulated response loss", request=request)
        else:
            return httpx.Response(404)
        return httpx.Response(200, json=copy.deepcopy(payload))
