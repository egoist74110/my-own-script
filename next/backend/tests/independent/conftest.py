"""Module-scoped real backend processes for the independent fault tests."""

from collections.abc import Iterator

import pytest

from .harness import Proc


@pytest.fixture(scope="module")
def ind_backend() -> Iterator[Proc]:
    p = Proc(env_extra={"TOOLBOX_HEARTBEAT_INTERVAL_S": "0.2"}).start()
    try:
        yield p
    finally:
        p.close()


@pytest.fixture(scope="module")
def ind_dev() -> Iterator[Proc]:
    p = Proc(["--dev"], env_extra={"TOOLBOX_HEARTBEAT_INTERVAL_S": "0.2"}).start()
    try:
        yield p
    finally:
        p.close()
