"""Independent S5-C conftest: fails any test that leaves a fake AI CLI process running."""

import asyncio

import pytest

from tests.independent.s5c.support import leftover_fake_cli_pids


@pytest.fixture(autouse=True)
async def no_fake_cli_leak():
    before = leftover_fake_cli_pids()
    yield
    # Give the process supervisor a moment to reap children closed during teardown.
    for _ in range(40):
        if not leftover_fake_cli_pids() - before:
            break
        await asyncio.sleep(0.05)
    leaked = leftover_fake_cli_pids() - before
    assert not leaked, f"fake AI CLI processes left behind: {sorted(leaked)}"
