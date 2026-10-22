import pytest

from toolbox_backend.domain.settings import LocalRepo


async def test_local_repo_create_patch_delete_use_revision_and_report_directory_state(
    s2ctx, tmp_path
):
    path = str(tmp_path)
    created = await s2ctx.client.post(
        "/api/ado/local-repos",
        json={"revision": await s2ctx.revision(), "name": "Workspace", "path": path},
    )
    assert created.status_code == 200, created.text
    repo_id = created.json()["id"]
    assert repo_id.startswith("repo:")

    listing = await s2ctx.client.get("/api/ado")
    assert listing.status_code == 200, listing.text
    repo = next(item for item in listing.json()["local_repos"] if item["id"] == repo_id)
    assert repo["exists"] is True
    assert repo["path"] == path

    missing = await s2ctx.client.post(
        "/api/ado/local-repos",
        json={
            "revision": await s2ctx.revision(),
            "name": "Missing",
            "path": str(tmp_path / "does-not-exist"),
        },
    )
    assert missing.status_code == 200, missing.text
    listing = await s2ctx.client.get("/api/ado")
    absent = next(
        item for item in listing.json()["local_repos"] if item["id"] == missing.json()["id"]
    )
    assert absent["exists"] is False

    patched = await s2ctx.client.patch(
        f"/api/ado/local-repos/{repo_id}",
        json={
            "revision": await s2ctx.revision(),
            "name": "Workspace 2",
            "path": path,
        },
    )
    assert patched.status_code == 200, patched.text
    deleted = await s2ctx.client.delete(
        f"/api/ado/local-repos/{repo_id}", params={"revision": await s2ctx.revision()}
    )
    assert deleted.status_code == 200, deleted.text
    assert all(item["id"] != repo_id for item in (await s2ctx.client.get("/api/ado")).json()["local_repos"])


@pytest.mark.parametrize(
    "path",
    [
        "relative/path",
        "/safe/../outside",
        "/safe/..",
        "/bad\x00path",
        "/" + "a" * 1024,
    ],
)
async def test_new_local_repo_paths_reject_nonabsolute_traversal_controls_and_oversize(
    s2ctx, path
):
    response = await s2ctx.client.post(
        "/api/ado/local-repos",
        json={"revision": await s2ctx.revision(), "name": "Invalid", "path": path},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert path not in response.text
    assert (await s2ctx.client.get("/api/ado")).json()["local_repos"] == []


async def test_local_repo_mutations_reject_stale_revision(s2ctx, tmp_path):
    revision = await s2ctx.revision()
    created = await s2ctx.client.post(
        "/api/ado/local-repos",
        json={"revision": revision, "name": "Workspace", "path": str(tmp_path)},
    )
    assert created.status_code == 200, created.text

    stale = await s2ctx.client.patch(
        f"/api/ado/local-repos/{created.json()['id']}",
        json={"revision": revision, "name": "Stale", "path": str(tmp_path)},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    listing = await s2ctx.client.get("/api/ado")
    assert listing.json()["local_repos"][0]["name"] == "Workspace"


async def test_invalid_imported_local_repo_remains_readable_with_warning(s2ctx):
    await s2ctx.app.state.config_store.update(
        0,
        lambda config: config.ado.local_repos.append(
            LocalRepo(id="repo:imported", name="Imported", path="relative/../path")
        ),
    )

    response = await s2ctx.client.get("/api/ado")
    assert response.status_code == 200, response.text
    repo = response.json()["local_repos"][0]
    assert repo["id"] == "repo:imported"
    assert repo["warnings"]
    assert "路径" in " ".join(repo["warnings"])
