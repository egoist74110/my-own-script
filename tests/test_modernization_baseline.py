"""Offline tests of the opt-in, read-only baseline CLI."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "modernization_baseline.py"
spec = importlib.util.spec_from_file_location("modernization_baseline", SCRIPT)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def test_missing_directory_and_distribution(tmp_path, monkeypatch):
    assert baseline.directory_size(tmp_path, "ok")["status"] == "missing"
    def missing(name):
        raise baseline.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(baseline.metadata, "distribution", missing)
    result = baseline.distribution_size("not-a-package")
    assert result["status"] == "not_installed"
    assert result["bytes"] is None


def test_directory_no_symlink_or_hardlink_double_count(tmp_path):
    directory = tmp_path / "ok"
    directory.mkdir()
    (directory / "first").write_bytes(b"12345")
    os.link(directory / "first", directory / "second")
    (directory / "loop").symlink_to(directory, target_is_directory=True)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    try:
        (outside / "secret").write_bytes(b"secret")
        (directory / "outside").symlink_to(outside, target_is_directory=True)
        (directory / "external").symlink_to(outside / "secret")
        result = baseline.directory_size(tmp_path, "ok")
        assert result["bytes"] == 5
        assert result["files"] == 1
    finally:
        (outside / "secret").unlink()
        outside.rmdir()


def test_distribution_manifest_scope_and_duplicate(tmp_path, monkeypatch):
    (tmp_path / "owned").write_bytes(b"123")
    (tmp_path / "unowned").write_bytes(b"do not count")
    (tmp_path / "redirect").symlink_to(tmp_path.parent, target_is_directory=True)
    class Distribution:
        version = "1.2"
        files = ["owned", "owned", "../escape", "redirect/anything"]
        def locate_file(self, item):
            return tmp_path / item
    monkeypatch.setattr(baseline.metadata, "distribution", lambda name: Distribution())
    result = baseline.distribution_size("example")
    assert result["bytes"] == 3
    assert result["files"] == 1
    assert result["skipped"] == 2
    assert result["additive"] is False


def test_distribution_without_manifest_is_explicitly_unmeasured(monkeypatch):
    class Distribution:
        version = "2.0"
        files = None

    monkeypatch.setattr(baseline.metadata, "distribution", lambda name: Distribution())
    result = baseline.distribution_size("example")
    assert result["status"] == "unmeasured"
    assert result["reason"] == "no_file_manifest"
    assert result["bytes"] is None


def test_distribution_missing_manifest_file_is_partial(tmp_path, monkeypatch):
    class Distribution:
        version = "2.1"
        files = ["present", "missing"]

        def locate_file(self, item):
            return tmp_path / item

    (tmp_path / "present").write_bytes(b"1234")
    monkeypatch.setattr(baseline.metadata, "distribution", lambda name: Distribution())
    result = baseline.distribution_size("example")
    assert result["status"] == "partial"
    assert result["bytes"] == 4
    assert result["files"] == 1
    assert result["errors"] == 1


def test_git_inventory_includes_both_rename_paths_and_filters_unsafe_paths(tmp_path, monkeypatch):
    outputs = iter([
        b"0123456789abcdef\n",
        b"R  new name\0old name\0M  safe.py\0M  ../outside\0",
    ])

    def fake_run(command, **kwargs):
        assert command[:4] == ["git", "--no-optional-locks", "-c", "core.fsmonitor=false"]
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs))

    monkeypatch.setattr(baseline.subprocess, "run", fake_run)
    result = baseline.git_inventory(tmp_path)
    assert result == {
        "status": "ok",
        "head": "0123456789abcdef",
        "dirty_paths": ["new name", "old name", "safe.py"],
    }


def test_probe_only_import(tmp_path):
    (tmp_path / "app_main.py").write_text("def main():\n    raise AssertionError('GUI called')\n")
    result = baseline.import_probe(tmp_path, 5)
    assert result["status"] == "ok"
    assert result["kind"] == "import_only"
    assert result["gui"] is False
    assert result["elapsed_seconds"] >= 0
    assert result["peak_rss_bytes"] > 0
    assert not (tmp_path / "__pycache__").exists()


@pytest.mark.parametrize("source,status", [
    ("raise RuntimeError('SECRET_DO_NOT_PRINT')", "error"),
    ("import time; time.sleep(10)", "timeout"),
    ("open('created', 'w')", "error"),
    ("import keyring; keyring.get_password('service', 'user')", "error"),
])
def test_probe_failure_timeout_and_guards(tmp_path, source, status):
    (tmp_path / "app_main.py").write_text(source)
    result = baseline.import_probe(tmp_path, 0.2)
    assert result["status"] == status
    assert "SECRET_DO_NOT_PRINT" not in json.dumps(result)
    assert "elapsed_seconds" not in result
    assert not (tmp_path / "created").exists()


@pytest.mark.parametrize("source", [
    "import socket; socket.socket()",
    "import subprocess; subprocess.run(['python', '-c', 'pass'])",
])
def test_probe_blocks_network_and_child_process_creation(tmp_path, source):
    (tmp_path / "app_main.py").write_text(source)
    result = baseline.import_probe(tmp_path, 5)
    assert result["status"] == "error"
    assert result["error"] == "import_failed_or_guard_blocked"


def test_probe_blocks_reads_outside_allowed_roots(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-secret.txt"
    outside.write_text("PRIVATE_MARKER")
    try:
        (tmp_path / "app_main.py").write_text(
            f"open({str(outside)!r}, encoding='utf-8').read()"
        )
        result = baseline.import_probe(tmp_path, 5)
        assert result["status"] == "error"
        assert result["error"] == "import_failed_or_guard_blocked"
        assert "PRIVATE_MARKER" not in json.dumps(result)
    finally:
        outside.unlink(missing_ok=True)


def test_default_no_write_and_explicit_output(tmp_path, monkeypatch, capsys):
    report = {"import_probe": {"status": "not_run"}}
    calls = []
    def collect(root, probe, timeout):
        calls.append(probe)
        return report
    monkeypatch.setattr(baseline, "collect", collect)
    monkeypatch.chdir(tmp_path)
    assert baseline.main([]) == 0
    assert json.loads(capsys.readouterr().out) == report
    assert list(tmp_path.iterdir()) == []
    output = tmp_path / "report.json"
    assert baseline.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text()) == report
    capsys.readouterr()
    assert baseline.main(["--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"
    assert calls == [False, False, False]


def test_output_parent_not_created(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(baseline, "collect", lambda *args: {})
    assert baseline.main(["--output", str(tmp_path / "missing" / "report.json")]) == 2
    assert not (tmp_path / "missing").exists()
    assert json.loads(capsys.readouterr().out)["error"] == "output_write_failed_no_overwrite"


def test_cli_help_and_invalid_timeout():
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--import-probe" in result.stdout
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--timeout", "nan"], capture_output=True, text=True)
    assert result.returncode == 2


def test_expanded_dependency_inventory_and_manifest_failure(tmp_path, monkeypatch):
    assert {"PySide6-Addons", "PySide6", "playwright", "Pillow", "pyotp",
            "pyobjc-framework-Vision", "pyobjc-framework-Quartz"} <= set(baseline.DISTRIBUTIONS)
    class BrokenDistribution:
        version = "1"
        @property
        def files(self):
            raise OSError("SECRET_METADATA_EXCEPTION")
    monkeypatch.setattr(baseline.metadata, "distribution", lambda name: BrokenDistribution())
    result = baseline.distribution_size("example")
    assert result["status"] == "error"
    assert result["error"] == "manifest_unavailable"
    assert "SECRET_METADATA_EXCEPTION" not in json.dumps(result)


def test_distribution_manifest_locate_failure_is_structured(monkeypatch):
    class BrokenDistribution:
        version = "1"
        files = ["owned"]
        def locate_file(self, item):
            raise OSError("SECRET_PATH_OR_METADATA")

    monkeypatch.setattr(baseline.metadata, "distribution", lambda name: BrokenDistribution())
    result = baseline.distribution_size("example")
    assert result["status"] == "error"
    assert result["error"] == "manifest_unavailable"
    assert result["bytes"] is None
    assert "SECRET_PATH_OR_METADATA" not in json.dumps(result)


def test_keyring_stub_allows_import_but_denies_credentials(tmp_path):
    (tmp_path / "app_main.py").write_text("import keyring")
    result = baseline.import_probe(tmp_path, 5)
    assert result["status"] == "ok"
    assert result["stubs"] == ["keyring_credentials_denied"]
    assert "guarded_variant" in result["meaning"]
    for operation in ("get_password", "set_password", "delete_password", "get_credential", "get_keyring", "set_keyring", "unknown_operation"):
        (tmp_path / "app_main.py").write_text(f"import keyring; keyring.{operation}()")
        result = baseline.import_probe(tmp_path, 5)
        assert result["status"] == "error"
        assert result["error_type"] == "PermissionError"
        assert "keyring.credentials" in result["blocked_events"]
        assert "elapsed_seconds" not in result


def test_skips_mark_partial(tmp_path):
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok" / "loop").symlink_to(tmp_path / "ok", target_is_directory=True)
    result = baseline.directory_size(tmp_path, "ok")
    assert result["status"] == "partial"
    assert result["skipped"] == 1


def test_cleanup_bounded_retry_and_failure_keeps_handle(monkeypatch):
    class Process:
        pid = 123
        stdout = None
        stderr = None
        def __init__(self, attempts):
            self.attempts = attempts
            self.deadlines = []
            self.killed = False
        def communicate(self, *, timeout):
            self.deadlines.append(timeout)
            self.attempts -= 1
            if self.attempts >= 0:
                raise subprocess.TimeoutExpired("redacted", timeout)
            return b"", None
        def kill(self):
            self.killed = True
    monkeypatch.setattr(baseline.os, "killpg", lambda *args: None)
    retry = Process(1)
    assert baseline.cleanup_probe(retry) == {"status": "ok"}
    assert retry.deadlines == [2, 1]
    assert retry.killed
    pending = []
    monkeypatch.setattr(baseline, "UNREAPED_PROBES", pending)
    stuck = Process(2)
    result = baseline.cleanup_probe(stuck)
    assert result["status"] == "cleanup_failed"
    assert result["handle_retained"] is True
    assert pending == [stuck]
    assert stuck.deadlines == [2, 1]


def test_import_failure_survives_cleanup_failure(tmp_path, monkeypatch):
    class Process:
        returncode = 0
        def communicate(self, *, timeout):
            assert timeout > 0
            return json.dumps({"status": "error", "error_type": "PermissionError",
                               "blocked_events": ["os.putenv", "SECRET_EVENT"],
                               "elapsed_seconds": 0.1, "peak_rss_bytes": 100}).encode(), None
    process = Process()
    monkeypatch.setattr(baseline.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(baseline, "cleanup_probe", lambda child: {"status": "cleanup_failed"})
    result = baseline.import_probe(tmp_path, 5)
    assert result["status"] == "error"
    assert result["error"] == "import_failed_or_guard_blocked"
    assert result["error_type"] == "PermissionError"
    assert result["blocked_events"] == ["os.putenv"]
    assert result["cleanup"]["status"] == "cleanup_failed"
    assert "elapsed_seconds" not in result


def test_successful_import_becomes_error_when_cleanup_fails(tmp_path, monkeypatch):
    class Process:
        returncode = 0
        def communicate(self, *, timeout):
            return json.dumps({"status": "ok", "error_type": None, "blocked_events": [],
                               "elapsed_seconds": 0.1, "peak_rss_bytes": 100}).encode(), None

    process = Process()
    monkeypatch.setattr(baseline.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(baseline, "cleanup_probe", lambda child: {"status": "cleanup_failed"})
    result = baseline.import_probe(tmp_path, 5)
    assert result["status"] == "error"
    assert result["import_status"] == "ok"
    assert result["error"] == "cleanup_failed"
    assert result["cleanup"]["status"] == "cleanup_failed"
    assert "elapsed_seconds" not in result
    assert "peak_rss_bytes" not in result


def test_abrupt_probe_failure_reports_only_safe_diagnostics(tmp_path):
    (tmp_path / "app_main.py").write_text("import os\ntry:\n    os.putenv('PRIVATE_NAME', 'PRIVATE_VALUE')\nexcept PermissionError:\n    os._exit(7)\n")
    result = baseline.import_probe(tmp_path, 5)
    assert result["status"] == "error"
    assert result["error_type"] == "ProcessExit"
    assert result["return_code"] == 7
    assert result["blocked_events"] == ["os.putenv"]
    assert "PRIVATE" not in json.dumps(result)
    assert result["cleanup"] == {"status": "ok"}
