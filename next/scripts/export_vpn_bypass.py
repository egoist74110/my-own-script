"""Export a reviewed snapshot/helper/launchd bundle without privilege or installation.

Run using the backend environment (Python 3.14 with toolbox_backend installed):
  cd next/backend
  uv run python ../scripts/export_vpn_bypass.py /private/path/snapshot.json \
    /private/path/new-export --python /opt/root-owned-python/bin/python3
snapshot.json is the settings object from GET /api/vpn/bypass (not the envelope).
The standalone exported helper needs only a separately provisioned trusted Python
>=3.9, not the backend package. Never run this exporter as root.
"""

import argparse
import json
import os
from pathlib import Path

from toolbox_backend.domain.vpn_bypass import VpnBypassConfig
from toolbox_backend.services.vpn_bypass import export_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--python", required=True, dest="python_path")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error(
            "export as ordinary user; review artifacts before explicit administrator install"
        )
    config = VpnBypassConfig.model_validate_json(args.snapshot.read_text()).model_dump()
    bundle = export_bundle(config, args.python_path)
    args.output.mkdir(mode=0o700)  # refuse to overwrite an existing export
    files = {
        "config.json": bundle["config_json"],
        "helper.py": bundle["helper_source"],
        "com.toolbox.vpn-bypass.plist": bundle["launchd_plist"],
        "INSTRUCTIONS.txt": "\n\n".join(bundle["instructions"]) + "\n",
    }
    for name, content in files.items():
        with (args.output / name).open("x") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
    print(json.dumps({"exported": str(args.output), "installed": False}))


if __name__ == "__main__":
    main()
