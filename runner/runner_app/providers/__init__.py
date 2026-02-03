from runner_app.providers.base import Provider
from runner_app.providers.github import GitHubProvider
from runner_app.providers.azure import AzureProvider


def get_provider(name: str) -> Provider:
    key = name.lower().strip()
    if key == "github":
        return GitHubProvider()
    if key == "azure":
        return AzureProvider()
    raise ValueError(f"Unknown provider: {name}")
