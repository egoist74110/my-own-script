import signal
import sys


def _early_exit(signum, frame):  # noqa: ARG001
    # Before the event loop owns signals (imports, bind): exit 0 as the contract requires.
    sys.exit(0)


for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, _early_exit)

from toolbox_backend.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
