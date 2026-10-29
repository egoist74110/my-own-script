"""Tests for next/scripts/*.sh argument/environment validation and signing order (stdlib only)."""

from __future__ import annotations

import os
import stat
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent
REPO_ROOT = SCRIPTS_DIR.parent.parent


def _write_exec(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestShellScripts(unittest.TestCase):
    def test_bash_syntax_all_scripts(self) -> None:
        expected = [
            "build_runtime.sh",
            "verify_app.sh",
            "sign_app.sh",
            "notarize_app.sh",
            "build_app.sh",
            "make_dmg.sh",
        ]
        for name in expected:
            script = SCRIPTS_DIR / name
            self.assertTrue(script.is_file(), f"missing script: {script}")
            res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"bash -n failed for {name}: {res.stderr}")

    def test_build_runtime_missing_pbs_python_home_fails_with_hint(self) -> None:
        script = SCRIPTS_DIR / "build_runtime.sh"
        env = dict(os.environ)
        env.pop("TOOLBOX_PBS_PYTHON_HOME", None)
        res = subprocess.run(
            ["bash", str(script)],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        combined = res.stdout + res.stderr
        self.assertIn("TOOLBOX_PBS_PYTHON_HOME", combined)
        self.assertIn("uv python install 3.14", combined)

    def test_build_runtime_invokes_uv_offline_and_copies_mcp_resources(self) -> None:
        script = SCRIPTS_DIR / "build_runtime.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            fake_bin = tmp / "bin"
            log_file = tmp / "uv.log"
            pbs_home = tmp / "pbs-python"
            out_dir = tmp / "build/app-resources/backend"

            # Create fake PBS python3.14 interpreter
            _write_exec(
                pbs_home / "bin/python3.14",
                "#!/usr/bin/env bash\n"
                "echo \"py:$*\" >> \"" + str(log_file) + "\"\n"
                "exit 0\n",
            )
            (pbs_home / "lib/python3.14/site-packages").mkdir(parents=True, exist_ok=True)
            (pbs_home / "lib/python3.14/EXTERNALLY-MANAGED").write_text("managed\n", encoding="utf-8")
            (pbs_home / "lib/python3.14/idlelib").mkdir(parents=True, exist_ok=True)

            # Create fake uv binary
            _write_exec(
                fake_bin / "uv",
                "#!/usr/bin/env bash\n"
                "echo \"uv:$*\" >> \"" + str(log_file) + "\"\n"
                "for ((i=1; i<=$#; i++)); do\n"
                "  if [ \"${!i}\" = \"-o\" ]; then\n"
                "    next=$((i+1))\n"
                "    echo \"fastapi==0.159.1\" > \"${!next}\"\n"
                "  fi\n"
                "done\n"
                "exit 0\n",
            )

            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            env["TOOLBOX_PBS_PYTHON_HOME"] = str(pbs_home)
            env["TOOLBOX_BUILD_DIR"] = str(tmp / "build")
            env["TOOLBOX_RUNTIME_OUT"] = str(out_dir)

            res = subprocess.run(
                ["bash", str(script)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=res.stdout + res.stderr)

            calls = log_file.read_text(encoding="utf-8").splitlines()
            uv_calls = [c for c in calls if c.startswith("uv:")]
            self.assertTrue(
                any("export" in c and "--frozen" in c and "--no-dev" in c and "--no-emit-project" in c and "--no-hashes" in c for c in uv_calls),
                f"missing expected uv export call in {uv_calls}",
            )
            pip_calls = [c for c in uv_calls if "pip install" in c]
            self.assertEqual(len(pip_calls), 2, f"expected 2 uv pip install calls, got {pip_calls}")
            for pc in pip_calls:
                self.assertIn("--no-deps", pc)
                self.assertIn("--offline", pc)

            # Check MCP resources copied to lib/python3.14/resources/mcp without node_modules
            mcp_dst = out_dir / "lib/python3.14/resources/mcp"
            for fname in (
                "figma_mcp_concurrency.js",
                "lark_mcp_patches.js",
                "package.json",
                "package-lock.json",
            ):
                self.assertTrue((mcp_dst / fname).is_file(), f"missing MCP resource {fname}")
            self.assertFalse((mcp_dst / "node_modules").exists())
            self.assertFalse((out_dir / "lib/python3.14/EXTERNALLY-MANAGED").exists())
            self.assertFalse((out_dir / "lib/python3.14/idlelib").exists())

    def test_sign_app_no_identity_and_no_adhoc_exits_2(self) -> None:
        script = SCRIPTS_DIR / "sign_app.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            app_dir = Path(tmp_str) / "TOOLBOX.app"
            (app_dir / "Contents/MacOS").mkdir(parents=True)
            env = dict(os.environ)
            env.pop("TOOLBOX_SIGN_IDENTITY", None)
            res = subprocess.run(
                ["bash", str(script), str(app_dir)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 2, msg=res.stdout + res.stderr)

            res2 = subprocess.run(
                ["bash", str(script), "--identity", str(app_dir)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res2.returncode, 2, msg=res2.stdout + res2.stderr)

    def test_sign_app_adhoc_banner_and_signing_order_without_timestamp(self) -> None:
        script = SCRIPTS_DIR / "sign_app.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            fake_bin = tmp / "bin"
            log_file = tmp / "codesign.log"
            app_dir = tmp / "TOOLBOX.app"

            # Create fake Mach-O files (4-byte Mach-O 64-bit magic \xcf\xfa\xed\xfe)
            macho_magic = b"\xcf\xfa\xed\xfe" + b"\x00" * 16
            so_file = app_dir / "Contents/Resources/backend/lib/python3.14/lib-dynload/_struct.cpython-314-darwin.so"
            dylib_file = app_dir / "Contents/Resources/backend/lib/libz.dylib"
            py_bin = app_dir / "Contents/Resources/backend/bin/python3.14"
            main_bin = app_dir / "Contents/MacOS/toolbox-desktop"
            txt_file = app_dir / "Contents/Resources/backend/lib/python3.14/site-packages/readme.txt"

            for p in (so_file, dylib_file, py_bin, main_bin):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(macho_magic)
                p.chmod(0o755)
            txt_file.parent.mkdir(parents=True, exist_ok=True)
            txt_file.write_text("plain text\n", encoding="utf-8")

            _write_exec(
                fake_bin / "codesign",
                "#!/usr/bin/env bash\n"
                "echo \"$*\" >> \"" + str(log_file) + "\"\n"
                "exit 0\n",
            )

            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            env.pop("TOOLBOX_SIGN_IDENTITY", None)

            res = subprocess.run(
                ["bash", str(script), "--adhoc", str(app_dir)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=res.stdout + res.stderr)
            combined_out = res.stdout + res.stderr
            self.assertIn("不可分发，授权会随更新失效", combined_out)

            lines = log_file.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(lines), 4, f"expected >=4 codesign calls, got {lines}")
            for line in lines:
                self.assertNotIn("--timestamp", line)
                # ad-hoc has no Team ID: hardened runtime library validation would reject bundled .so files
                self.assertNotIn("--options runtime", line)
                self.assertIn("-s -", line)

            # Verify order: inner .so/.dylib -> bin/python3.14 -> Contents/MacOS/toolbox-desktop -> .app
            idx_so = next(i for i, l in enumerate(lines) if str(so_file) in l)
            idx_dylib = next(i for i, l in enumerate(lines) if str(dylib_file) in l)
            idx_py = next(i for i, l in enumerate(lines) if l.endswith(str(py_bin)))
            idx_main = next(i for i, l in enumerate(lines) if l.endswith(str(main_bin)))
            idx_app = next(i for i, l in enumerate(lines) if l.endswith(str(app_dir)))

            self.assertLess(idx_so, idx_py)
            self.assertLess(idx_dylib, idx_py)
            self.assertLess(idx_py, idx_main)
            self.assertLess(idx_main, idx_app)
            self.assertIn("--entitlements", lines[idx_app])

    def test_sign_app_identity_mode_uses_runtime_timestamp_and_entitlements(self) -> None:
        script = SCRIPTS_DIR / "sign_app.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            fake_bin = tmp / "bin"
            log_file = tmp / "codesign.log"
            app_dir = tmp / "TOOLBOX.app"

            macho_magic = b"\xcf\xfa\xed\xfe" + b"\x00" * 16
            so_file = app_dir / "Contents/Resources/backend/lib/python3.14/site-packages/foo.so"
            py_bin = app_dir / "Contents/Resources/backend/bin/python3.14"
            main_bin = app_dir / "Contents/MacOS/toolbox-desktop"

            for p in (so_file, py_bin, main_bin):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(macho_magic)
                p.chmod(0o755)

            _write_exec(
                fake_bin / "codesign",
                "#!/usr/bin/env bash\n"
                "echo \"$*\" >> \"" + str(log_file) + "\"\n"
                "exit 0\n",
            )

            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            env["TOOLBOX_SIGN_IDENTITY"] = "Developer ID Application: ExampleTest (TEAMID1234)"

            res = subprocess.run(
                ["bash", str(script), "--identity", str(app_dir)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=res.stdout + res.stderr)
            lines = log_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4, f"expected 4 codesign calls, got {lines}")
            for line in lines:
                self.assertIn("--options runtime", line)
                self.assertIn("--timestamp", line)
                self.assertIn("Developer ID Application: ExampleTest (TEAMID1234)", line)
            self.assertIn("--entitlements", lines[-1])
            self.assertTrue(lines[-1].endswith(str(app_dir)))

    def test_notarize_app_missing_profile_exits_2_and_with_profile_calls_notarytool_and_stapler(self) -> None:
        script = SCRIPTS_DIR / "notarize_app.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            app_dir = tmp / "TOOLBOX.app"
            (app_dir / "Contents/MacOS").mkdir(parents=True)

            env = dict(os.environ)
            env.pop("TOOLBOX_NOTARY_PROFILE", None)
            res = subprocess.run(
                ["bash", str(script), str(app_dir)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 2, msg=res.stdout + res.stderr)

            # Now test with fake ditto + xcrun
            fake_bin = tmp / "bin"
            log_file = tmp / "notarize.log"
            _write_exec(
                fake_bin / "ditto",
                "#!/usr/bin/env bash\n"
                "echo \"ditto:$*\" >> \"" + str(log_file) + "\"\n"
                "touch \"${@: -1}\"\n"
                "exit 0\n",
            )
            _write_exec(
                fake_bin / "xcrun",
                "#!/usr/bin/env bash\n"
                "echo \"xcrun:$*\" >> \"" + str(log_file) + "\"\n"
                "exit 0\n",
            )
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            env["TOOLBOX_NOTARY_PROFILE"] = "fake-notary-profile"

            res_ok = subprocess.run(
                ["bash", str(script), str(app_dir)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_ok.returncode, 0, msg=res_ok.stdout + res_ok.stderr)
            calls = log_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 3, f"expected 3 calls (ditto, notarytool, stapler), got {calls}")
            self.assertTrue(calls[0].startswith("ditto:-c -k --keepParent"))
            self.assertIn("notarytool submit", calls[1])
            self.assertIn("--keychain-profile fake-notary-profile", calls[1])
            self.assertIn("--wait", calls[1])
            self.assertIn("stapler staple", calls[2])

    def test_verify_app_checks_layout_leak_and_relocatable_startup(self) -> None:
        script = SCRIPTS_DIR / "verify_app.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            app_dir = tmp / "TOOLBOX.app"

            # 1. Missing layout -> exits nonzero
            app_dir.mkdir(parents=True)
            res_missing = subprocess.run(
                ["bash", str(script), str(app_dir)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res_missing.returncode, 0)

            # 2. Populate valid fake .app bundle
            main_bin = app_dir / "Contents/MacOS/toolbox-desktop"
            py_bin = app_dir / "Contents/Resources/backend/bin/python3.14"
            mcp_dir = app_dir / "Contents/Resources/backend/lib/python3.14/resources/mcp"
            mcp_dir.mkdir(parents=True, exist_ok=True)
            for fname in (
                "figma_mcp_concurrency.js",
                "lark_mcp_patches.js",
                "package.json",
                "package-lock.json",
            ):
                (mcp_dir / fname).write_text("// ok\n", encoding="utf-8")

            main_bin.parent.mkdir(parents=True, exist_ok=True)
            main_bin.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 16)
            main_bin.chmod(0o755)

            # Fake python3.14 that emits TOOLBOX_READY, waits for stdin EOF, and exits 0
            sys_py = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else "python3"
            http_log = tmp / "http_get.log"
            _write_exec(
                py_bin,
                f"#!{sys_py}\n"
                "import json, os, sys\n"
                "token = 'test-token-123'\n"
                "port = 54321\n"
                "sys.stdout.write('TOOLBOX_READY ' + json.dumps({'v': 1, 'port': port, 'token': token, 'pid': os.getpid()}) + '\\n')\n"
                "sys.stdout.flush()\n"
                "sys.stdin.read()\n"
                "sys.exit(0)\n",
            )

            # Test leak detection first: write a file containing /Users/somebody
            leak_file = app_dir / "Contents/Resources/backend/lib/python3.14/leaked_config.txt"
            leak_file.write_text("prefix=/Users/somebody/secret\n", encoding="utf-8")
            res_leak = subprocess.run(
                ["bash", str(script), str(app_dir)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res_leak.returncode, 0, "expected verify_app.sh to fail on /Users/ path leak")
            self.assertIn("leaked_config.txt", res_leak.stdout + res_leak.stderr)

            # Remove leaked file and run full verify with fake codesign/vtool/http helper
            leak_file.unlink()
            fake_bin = tmp / "bin"
            codesign_log = tmp / "codesign_verify.log"
            fake_http = _write_exec(
                fake_bin / "fake_http_get",
                "#!/usr/bin/env bash\n"
                "echo \"$1|$2|$3\" >> \"" + str(http_log) + "\"\n"
                "[ \"$1\" = \"http://127.0.0.1:54321/health\" ] && [ \"$2\" = \"127.0.0.1:54321\" ] && [ \"$3\" = \"Bearer test-token-123\" ]\n",
            )
            _write_exec(
                fake_bin / "codesign",
                "#!/usr/bin/env bash\n"
                "echo \"$*\" >> \"" + str(codesign_log) + "\"\n"
                "exit 0\n",
            )
            _write_exec(
                fake_bin / "vtool",
                "#!/usr/bin/env bash\n"
                "echo \"    minos 14.0\"\n"
                "exit 0\n",
            )
            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            env["TOOLBOX_VERIFY_HTTP_GET"] = str(fake_http)

            res_ok = subprocess.run(
                ["bash", str(script), str(app_dir)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_ok.returncode, 0, msg=res_ok.stdout + res_ok.stderr)
            self.assertIn("14.0", res_ok.stdout + res_ok.stderr)
            cs_calls = codesign_log.read_text(encoding="utf-8")
            self.assertIn("--verify --deep --strict --verbose=2", cs_calls)
            self.assertIn("http://127.0.0.1:54321/health|127.0.0.1:54321|Bearer test-token-123", http_log.read_text(encoding="utf-8"))

    def test_make_dmg_creates_dmg_and_zip_with_versioned_names(self) -> None:
        script = SCRIPTS_DIR / "make_dmg.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            app_dir = tmp / "TOOLBOX.app"
            (app_dir / "Contents/MacOS").mkdir(parents=True)
            out_dir = tmp / "dist-out"
            fake_bin = tmp / "bin"
            log_file = tmp / "dmg.log"

            _write_exec(
                fake_bin / "hdiutil",
                "#!/usr/bin/env bash\n"
                "echo \"hdiutil:$*\" >> \"" + str(log_file) + "\"\n"
                "touch \"${@: -1}\"\n"
                "exit 0\n",
            )
            _write_exec(
                fake_bin / "ditto",
                "#!/usr/bin/env bash\n"
                "echo \"ditto:$*\" >> \"" + str(log_file) + "\"\n"
                "touch \"${@: -1}\"\n"
                "exit 0\n",
            )

            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"

            res = subprocess.run(
                ["bash", str(script), str(app_dir), str(out_dir)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=res.stdout + res.stderr)
            self.assertTrue((out_dir / "TOOLBOX-1.0.0-arm64.dmg").is_file())
            self.assertTrue((out_dir / "TOOLBOX-1.0.0-arm64.zip").is_file())
            calls = log_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 2)
            self.assertIn("-format UDZO", calls[0])
            self.assertIn("-c -k --keepParent", calls[1])

    def test_build_app_invalid_sign_arg_exits_2(self) -> None:
        script = SCRIPTS_DIR / "build_app.sh"
        res = subprocess.run(
            ["bash", str(script), "--sign", "invalid-mode"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 2)

    def test_build_app_updater_config_validation_and_overlay_merge(self) -> None:
        script = SCRIPTS_DIR / "build_app.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            missing_cfg = tmp / "nonexistent.updater.json"

            # 1. Missing argument after --updater-config -> exit 2
            res_no_arg = subprocess.run(
                ["bash", str(script), "--updater-config"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_no_arg.returncode, 2)

            # 2. Non-existent file -> exit 2
            res_missing = subprocess.run(
                ["bash", str(script), "--updater-config", str(missing_cfg)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_missing.returncode, 2)

            res_missing_eq = subprocess.run(
                ["bash", str(script), f"--updater-config={missing_cfg}"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_missing_eq.returncode, 2)

            # 3. Valid updater config merges into overlay JSON
            updater_cfg = tmp / "updater.json"
            updater_cfg.write_text(
                '{\n'
                '  "bundle": {\n'
                '    "createUpdaterArtifacts": true\n'
                '  },\n'
                '  "plugins": {\n'
                '    "updater": {\n'
                '      "pubkey": "TEST_PUBKEY",\n'
                '      "endpoints": ["https://example.com/latest.json"]\n'
                '    }\n'
                '  }\n'
                '}\n',
                encoding="utf-8",
            )
            fake_bin = tmp / "bin"
            pnpm_log = tmp / "pnpm.log"
            build_dir = tmp / "build"
            out_dir = tmp / "out"
            cargo_target = tmp / "cargo-target"

            # Prepare fake built .app so step 4 succeeds and stops at fake verify_app or finishes
            built_app = cargo_target / "release/bundle/macos/代码工具箱.app"
            (built_app / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
            (built_app / "Contents/MacOS/toolbox-desktop").write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 16)
            (built_app / "Contents/MacOS/toolbox-desktop").chmod(0o755)
            py_bin = built_app / "Contents/Resources/backend/bin/python3.14"
            py_bin.parent.mkdir(parents=True, exist_ok=True)
            sys_py = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else "python3"
            _write_exec(
                py_bin,
                f"#!{sys_py}\n"
                "import json, os, sys\n"
                "sys.stdout.write('TOOLBOX_READY ' + json.dumps({'v': 1, 'port': 54321, 'token': 't', 'pid': os.getpid()}) + '\\n')\n"
                "sys.stdout.flush()\n"
                "sys.stdin.read()\n"
                "sys.exit(0)\n",
            )
            mcp_dir = built_app / "Contents/Resources/backend/lib/python3.14/resources/mcp"
            mcp_dir.mkdir(parents=True, exist_ok=True)
            for fname in (
                "figma_mcp_concurrency.js",
                "lark_mcp_patches.js",
                "package.json",
                "package-lock.json",
            ):
                (mcp_dir / fname).write_text("// ok\n", encoding="utf-8")

            _write_exec(
                fake_bin / "pnpm",
                "#!/usr/bin/env bash\n"
                "echo \"$*\" >> \"" + str(pnpm_log) + "\"\n"
                "mkdir -p dist/assets\n"
                "echo '<html><script type=module src=/assets/a.js></script></html>' > dist/index.html\n"
                "echo '//' > dist/assets/a.js\n"
                "exit 0\n",
            )
            pbs_home = tmp / "pbs-python"
            _write_exec(pbs_home / "bin/python3.14", "#!/usr/bin/env bash\nexit 0\n")
            (pbs_home / "lib/python3.14/site-packages").mkdir(parents=True, exist_ok=True)
            _write_exec(
                fake_bin / "uv",
                "#!/usr/bin/env bash\n"
                "for ((i=1; i<=$#; i++)); do\n"
                "  if [ \"${!i}\" = \"-o\" ]; then\n"
                "    next=$((i+1))\n"
                "    echo \"fastapi==0.159.1\" > \"${!next}\"\n"
                "  fi\n"
                "done\n"
                "exit 0\n",
            )
            fake_http = _write_exec(
                fake_bin / "fake_http_get",
                "#!/usr/bin/env bash\nexit 0\n",
            )
            _write_exec(fake_bin / "codesign", "#!/usr/bin/env bash\nexit 0\n")
            _write_exec(fake_bin / "vtool", "#!/usr/bin/env bash\necho '    minos 13.5'\nexit 0\n")

            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            env["TOOLBOX_PBS_PYTHON_HOME"] = str(pbs_home)
            env["TOOLBOX_BUILD_DIR"] = str(build_dir)
            env["TOOLBOX_RUNTIME_OUT"] = str(build_dir / "app-resources/backend")
            env["TOOLBOX_OUT_DIR"] = str(out_dir)
            env["CARGO_TARGET_DIR"] = str(cargo_target)
            env["TOOLBOX_VERIFY_HTTP_GET"] = str(fake_http)
            # Never let the fake pnpm touch the real next/desktop/dist (it once shipped a blank window).
            fake_desktop = tmp / "desktop"
            (fake_desktop / "src-tauri").mkdir(parents=True)
            shutil.copy(
                REPO_ROOT / "next/desktop/src-tauri/tauri.bundle.conf.json",
                fake_desktop / "src-tauri/tauri.bundle.conf.json",
            )
            env["TOOLBOX_DESKTOP_DIR"] = str(fake_desktop)

            res_ok = subprocess.run(
                ["bash", str(script), "--updater-config", str(updater_cfg)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_ok.returncode, 0, msg=res_ok.stdout + res_ok.stderr)

            import json
            overlay_data = json.loads((build_dir / "tauri.build.overlay.json").read_text(encoding="utf-8"))
            self.assertEqual(overlay_data["bundle"]["createUpdaterArtifacts"], True)
            expected_key = os.path.relpath(
                os.path.abspath(build_dir / "app-resources/backend"),
                os.path.abspath(fake_desktop / "src-tauri"),
            )
            self.assertEqual(overlay_data["bundle"]["resources"], {expected_key: "backend"})
            self.assertEqual(overlay_data["bundle"]["macOS"]["minimumSystemVersion"], "13.5")
            self.assertEqual(overlay_data["plugins"]["updater"]["pubkey"], "TEST_PUBKEY")
            self.assertEqual(
                overlay_data["plugins"]["updater"]["endpoints"],
                ["https://example.com/latest.json"],
            )

    def test_build_app_rejects_stub_frontend_dist(self) -> None:
        script = SCRIPTS_DIR / "build_app.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            desktop = tmp / "desktop"
            (desktop / "dist").mkdir(parents=True)
            (desktop / "dist/index.html").write_text("<html></html>\n", encoding="utf-8")
            env = dict(os.environ, TOOLBOX_DESKTOP_DIR=str(desktop), TOOLBOX_BUILD_DIR=str(tmp / "build"))
            res = subprocess.run(
                ["bash", str(script), "--skip-frontend", "--sign", "adhoc"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 1, msg=res.stdout + res.stderr)
            self.assertIn("not a real frontend build", res.stderr)

    def test_build_app_rejects_unsafe_updater_configs_exit_2(self) -> None:
        script = SCRIPTS_DIR / "build_app.sh"
        good = {
            "bundle": {"createUpdaterArtifacts": True},
            "plugins": {"updater": {"pubkey": "REALKEY", "endpoints": ["https://e.com/latest.json"]}},
        }
        import copy
        import json

        def variant(mut) -> dict:
            c = copy.deepcopy(good)
            mut(c)
            return c

        bad_cases = {
            "insecure_flag": variant(lambda c: c["plugins"]["updater"].update(dangerousInsecureTransportProtocol=True)),
            "http_endpoint": variant(lambda c: c["plugins"]["updater"].update(endpoints=["http://e.com/l.json"])),
            "empty_endpoints": variant(lambda c: c["plugins"]["updater"].update(endpoints=[])),
            "empty_pubkey": variant(lambda c: c["plugins"]["updater"].update(pubkey="  ")),
            "placeholder_pubkey": variant(lambda c: c["plugins"]["updater"].update(pubkey="REPLACE_WITH_MINISIGN_PUBLIC_KEY")),
        }
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            for name, conf in bad_cases.items():
                cfg = tmp / f"{name}.json"
                cfg.write_text(json.dumps(conf), encoding="utf-8")
                res = subprocess.run(
                    ["bash", str(script), "--updater-config", str(cfg)],
                    capture_output=True, text=True,
                )
                self.assertEqual(res.returncode, 2, msg=f"{name}: {res.stdout}{res.stderr}")
                self.assertIn("updater config invalid", res.stderr, msg=name)
            # example file itself (placeholders) must be rejected too
            example = REPO_ROOT / "next/desktop/src-tauri/tauri.updater.conf.example.json"
            res = subprocess.run(
                ["bash", str(script), "--updater-config", str(example)], capture_output=True, text=True
            )
            self.assertEqual(res.returncode, 2, msg=res.stderr)
            # good config passes the validator
            good_cfg = tmp / "good.json"
            good_cfg.write_text(json.dumps(good), encoding="utf-8")
            res_good = subprocess.run(
                ["python3", str(SCRIPTS_DIR / "validate_updater_config.py"), str(good_cfg)],
                capture_output=True, text=True,
            )
            self.assertEqual(res_good.returncode, 0, msg=res_good.stderr)

    def test_build_runtime_refuses_unsafe_runtime_out(self) -> None:
        script = SCRIPTS_DIR / "build_runtime.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            pbs = tmp / "pbs"
            _write_exec(pbs / "bin/python3.14", "#!/usr/bin/env bash\nexit 0\n")
            build = tmp / "build"
            build.mkdir()
            victim = tmp / "victim"
            victim.mkdir()
            (victim / "keep.txt").write_text("x", encoding="utf-8")
            cases = {
                "outside_build": str(victim),
                "equals_build": str(build),
                "relative": "relative/path",
                "dotdot_escape": str(build / ".." / "victim"),
                "root": "/",
                "home": os.environ["HOME"],
            }
            for name, out in cases.items():
                env = dict(os.environ)
                env.update(
                    TOOLBOX_PBS_PYTHON_HOME=str(pbs),
                    TOOLBOX_BUILD_DIR=str(build),
                    TOOLBOX_RUNTIME_OUT=out,
                )
                res = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
                self.assertEqual(res.returncode, 2, msg=f"{name}: {res.stdout}{res.stderr}")
                self.assertIn("refusing to rm -rf", res.stderr, msg=name)
            self.assertTrue((victim / "keep.txt").is_file())

    def test_make_update_artifact_retars_signed_app_and_signs_from_env(self) -> None:
        script = SCRIPTS_DIR / "make_update_artifact.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            app = tmp / "out/代码工具箱.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/marker.txt").write_text("signed-copy", encoding="utf-8")
            fake_bin = tmp / "bin"
            pnpm_log = tmp / "pnpm.log"
            _write_exec(
                fake_bin / "codesign",
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = \"-dv\" ] && [ \"$2\" = \"--verbose=2\" ]; then echo 'Authority=Developer ID Application: X' >&2; fi\n"
                "exit 0\n",
            )
            _write_exec(
                fake_bin / "pnpm",
                "#!/usr/bin/env bash\n"
                "echo \"ARGV: $*\" >> \"" + str(pnpm_log) + "\"\n"
                "echo \"keyset=${TAURI_SIGNING_PRIVATE_KEY:+yes}\" >> \"" + str(pnpm_log) + "\"\n"
                "for a in \"$@\"; do last=\"$a\"; done\n"
                "echo SIGDATA > \"$last.sig\"\n",
            )
            dist = tmp / "dist"
            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            env.pop("TAURI_SIGNING_PRIVATE_KEY", None)

            # no key: tarball produced, signing skipped, exit 0
            res = subprocess.run(["bash", str(script), str(app), str(dist)], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, msg=res.stdout + res.stderr)
            tarball = dist / "TOOLBOX.app.tar.gz"
            self.assertTrue(tarball.is_file())
            self.assertFalse((dist / "TOOLBOX.app.tar.gz.sig").exists())
            self.assertIn("skipping", res.stderr)
            listing = subprocess.run(["tar", "-tzf", str(tarball)], capture_output=True, text=True).stdout
            self.assertIn("代码工具箱.app/Contents/marker.txt", listing)
            self.assertNotIn("._", listing)

            # with key: signer invoked, secret never in argv
            secret = "SUPER-SECRET-KEY-VALUE"
            env["TAURI_SIGNING_PRIVATE_KEY"] = secret
            res2 = subprocess.run(["bash", str(script), str(app), str(dist)], env=env, capture_output=True, text=True)
            self.assertEqual(res2.returncode, 0, msg=res2.stdout + res2.stderr)
            self.assertTrue((dist / "TOOLBOX.app.tar.gz.sig").is_file())
            log = pnpm_log.read_text(encoding="utf-8")
            self.assertIn("tauri signer sign", log)
            self.assertIn("keyset=yes", log)
            self.assertNotIn(secret, log)
            self.assertNotIn(secret, res2.stdout + res2.stderr)

    def test_make_update_artifact_refuses_adhoc_and_unsigned(self) -> None:
        script = SCRIPTS_DIR / "make_update_artifact.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            app = tmp / "TOOLBOX.app"
            (app / "Contents").mkdir(parents=True)
            fake_bin = tmp / "bin"
            _write_exec(
                fake_bin / "codesign",
                "#!/usr/bin/env bash\necho 'Signature=adhoc' >&2\nexit 0\n",
            )
            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            dist = tmp / "dist"
            res = subprocess.run(["bash", str(script), str(app), str(dist)], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 2, msg=res.stderr)
            self.assertIn("ad-hoc", res.stderr)
            self.assertFalse((dist / "TOOLBOX.app.tar.gz").exists())

    def test_verify_app_kills_leftover_group_even_when_main_exited(self) -> None:
        script = SCRIPTS_DIR / "verify_app.sh"
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            app_dir = tmp / "TOOLBOX.app"
            main_bin = app_dir / "Contents/MacOS/toolbox-desktop"
            py_bin = app_dir / "Contents/Resources/backend/bin/python3.14"
            mcp_dir = app_dir / "Contents/Resources/backend/lib/python3.14/resources/mcp"
            mcp_dir.mkdir(parents=True, exist_ok=True)
            for fname in ("figma_mcp_concurrency.js", "lark_mcp_patches.js", "package.json", "package-lock.json"):
                (mcp_dir / fname).write_text("// ok\n", encoding="utf-8")
            main_bin.parent.mkdir(parents=True, exist_ok=True)
            main_bin.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 16)
            main_bin.chmod(0o755)
            child_pid_file = tmp / "child.pid"
            sys_py = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else "python3"
            # Backend spawns a lingering child in the same group, then exits 0 on stdin EOF.
            _write_exec(
                py_bin,
                f"#!{sys_py}\n"
                "import json, os, subprocess, sys\n"
                f"c = subprocess.Popen(['/bin/sleep', '60'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                f"open({str(child_pid_file)!r}, 'w').write(str(c.pid))\n"
                "sys.stdout.write('TOOLBOX_READY ' + json.dumps({'v': 1, 'port': 54321, 'token': 't', 'pid': os.getpid()}) + '\\n')\n"
                "sys.stdout.flush()\n"
                "sys.stdin.read()\n"
                "sys.exit(0)\n",
            )
            fake_bin = tmp / "bin"
            fake_http = _write_exec(fake_bin / "fake_http_get", "#!/usr/bin/env bash\nexit 0\n")
            _write_exec(fake_bin / "codesign", "#!/usr/bin/env bash\nexit 0\n")
            _write_exec(fake_bin / "vtool", "#!/usr/bin/env bash\necho '    minos 14.0'\nexit 0\n")
            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
            env["TOOLBOX_VERIFY_HTTP_GET"] = str(fake_http)
            res = subprocess.run(["bash", str(script), str(app_dir)], env=env, capture_output=True, text=True)
            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            try:
                self.assertNotEqual(res.returncode, 0, msg="leftover child must fail verification")
                self.assertIn("leftover", res.stdout + res.stderr)
                import time
                alive = True
                for _ in range(40):
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        alive = False
                        break
                    time.sleep(0.1)
                self.assertFalse(alive, "leftover child in the verify process group must be killed")
            finally:
                try:
                    os.kill(child_pid, 9)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    unittest.main()
