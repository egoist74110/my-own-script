"""Tests for next/scripts/make_update_manifest.py (stdlib only)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent
MANIFEST_SCRIPT = SCRIPTS_DIR / "make_update_manifest.py"


class TestMakeUpdateManifest(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(MANIFEST_SCRIPT), *args],
            capture_output=True,
            text=True,
        )

    def test_valid_manifest_with_and_without_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            sig_file = tmp / "app.tar.gz.sig"
            sig_file.write_text("dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWdu\n", encoding="utf-8")
            notes_file = tmp / "notes.txt"
            notes_file.write_text("Fix bugs and improve stability.\n", encoding="utf-8")
            out_file = tmp / "latest.json"

            res = self._run(
                "--version",
                "1.2.3",
                "--notes-file",
                str(notes_file),
                "--platform",
                "darwin-aarch64",
                "--url",
                "https://github.com/owner/repo/releases/download/v1.2.3/TOOLBOX.app.tar.gz",
                "--signature-file",
                str(sig_file),
                "--out",
                str(out_file),
            )
            self.assertEqual(res.returncode, 0, msg=res.stdout + res.stderr)
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "1.2.3")
            self.assertEqual(data["notes"], "Fix bugs and improve stability.")
            self.assertTrue(
                re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", data["pub_date"]),
                f"unexpected pub_date: {data['pub_date']}",
            )
            self.assertEqual(
                data["platforms"]["darwin-aarch64"],
                {
                    "signature": "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWdu",
                    "url": "https://github.com/owner/repo/releases/download/v1.2.3/TOOLBOX.app.tar.gz",
                },
            )

            # Without --notes-file -> notes defaults to ""
            out_no_notes = tmp / "latest_no_notes.json"
            res2 = self._run(
                "--version",
                "1.2.3-rc.1+build.5",
                "--platform",
                "darwin-aarch64",
                "--url",
                "https://github.com/owner/repo/releases/download/v1.2.3/TOOLBOX.app.tar.gz",
                "--signature-file",
                str(sig_file),
                "--out",
                str(out_no_notes),
            )
            self.assertEqual(res2.returncode, 0, msg=res2.stdout + res2.stderr)
            data2 = json.loads(out_no_notes.read_text(encoding="utf-8"))
            self.assertEqual(data2["version"], "1.2.3-rc.1+build.5")
            self.assertEqual(data2["notes"], "")

    def test_rejects_invalid_semver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            sig_file = tmp / "app.sig"
            sig_file.write_text("sig-content\n", encoding="utf-8")
            out_file = tmp / "latest.json"

            for bad_ver in ("", "1.2", "v1.2.3", "1.2.3.4", "01.2.3", "abc"):
                res = self._run(
                    "--version",
                    bad_ver,
                    "--platform",
                    "darwin-aarch64",
                    "--url",
                    "https://example.com/app.tar.gz",
                    "--signature-file",
                    str(sig_file),
                    "--out",
                    str(out_file),
                )
                self.assertNotEqual(res.returncode, 0, f"expected failure for version={bad_ver!r}")
                self.assertFalse(out_file.exists())

    def test_rejects_empty_or_missing_signature_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            empty_sig = tmp / "empty.sig"
            empty_sig.write_text("   \n  ", encoding="utf-8")
            out_file = tmp / "latest.json"

            res_empty = self._run(
                "--version",
                "1.0.0",
                "--platform",
                "darwin-aarch64",
                "--url",
                "https://example.com/app.tar.gz",
                "--signature-file",
                str(empty_sig),
                "--out",
                str(out_file),
            )
            self.assertNotEqual(res_empty.returncode, 0)

            res_missing = self._run(
                "--version",
                "1.0.0",
                "--platform",
                "darwin-aarch64",
                "--url",
                "https://example.com/app.tar.gz",
                "--signature-file",
                str(tmp / "missing.sig"),
                "--out",
                str(out_file),
            )
            self.assertNotEqual(res_missing.returncode, 0)

    def test_url_https_and_loopback_allow_insecure_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            sig_file = tmp / "app.sig"
            sig_file.write_text("sig-content\n", encoding="utf-8")
            out_file = tmp / "latest.json"

            # Non-loopback http is always rejected (even with --allow-insecure)
            for args in (
                ["--url", "http://example.com/app.tar.gz"],
                ["--url", "http://example.com/app.tar.gz", "--allow-insecure"],
                ["--url", "ftp://example.com/app.tar.gz"],
            ):
                res = self._run(
                    "--version",
                    "1.0.0",
                    "--platform",
                    "darwin-aarch64",
                    "--signature-file",
                    str(sig_file),
                    "--out",
                    str(out_file),
                    *args,
                )
                self.assertNotEqual(res.returncode, 0, f"expected rejection for {args}")

            # Loopback http without --allow-insecure is rejected
            res_loop_no_flag = self._run(
                "--version",
                "1.0.0",
                "--platform",
                "darwin-aarch64",
                "--url",
                "http://127.0.0.1:8080/app.tar.gz",
                "--signature-file",
                str(sig_file),
                "--out",
                str(out_file),
            )
            self.assertNotEqual(res_loop_no_flag.returncode, 0)

            # Loopback http with --allow-insecure succeeds
            for loop_url in (
                "http://127.0.0.1:8080/app.tar.gz",
                "http://localhost:8080/app.tar.gz",
                "http://[::1]:8080/app.tar.gz",
            ):
                res_loop_ok = self._run(
                    "--version",
                    "1.0.0",
                    "--platform",
                    "darwin-aarch64",
                    "--url",
                    loop_url,
                    "--allow-insecure",
                    "--signature-file",
                    str(sig_file),
                    "--out",
                    str(out_file),
                )
                self.assertEqual(
                    res_loop_ok.returncode,
                    0,
                    f"expected loopback success for {loop_url}: {res_loop_ok.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
