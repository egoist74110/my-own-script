"""Cross-process store writer, always launched with a timeout by test_s1_store."""

import asyncio
import sys
import time
from pathlib import Path

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.errors import SettingsError


async def main():
    directory, barrier, owner = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == "owner"
    store = ConfigStore(directory)
    if owner:

        def pause(stage):
            if stage == "before_replace":
                (barrier / "locked").touch()
                deadline = time.monotonic() + 5
                while not (barrier / "release").exists():
                    if time.monotonic() > deadline:
                        raise TimeoutError
                    time.sleep(0.01)

        store.checkpoint = pause
    else:
        (barrier / "contending").touch()
    try:
        await store.update(0, lambda c: None)
        print("committed")
    except SettingsError as exc:
        print(exc.code)


asyncio.run(main())
