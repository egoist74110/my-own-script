from __future__ import annotations

from ui_app.azuredevops_client import AzureDevOpsClient


def list_collections(base_url: str, pat: str) -> list[str]:
    c = AzureDevOpsClient(base_url=base_url, pat=pat, api_version="7.0")
    cols = c.list_collections()
    return [x.name for x in cols]


def list_projects(base_url: str, pat: str, collection: str) -> list[str]:
    c = AzureDevOpsClient(base_url=base_url, pat=pat, api_version="7.0")
    ps = c.list_projects(collection)
    return [x.name for x in ps]
