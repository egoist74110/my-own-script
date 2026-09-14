"""dsh 版本比较 / 更新检查逻辑（services_panel 纯逻辑部分，不触网）。"""
from __future__ import annotations

import unittest

from app_ado import services_panel as svc


class TestSemverKey(unittest.TestCase):
    def _lt(self, a: str, b: str) -> None:
        ka, kb = svc._semver_key(a), svc._semver_key(b)
        self.assertIsNotNone(ka)
        self.assertIsNotNone(kb)
        self.assertLess(ka, kb)

    def test_patch_order(self):
        self._lt("0.1.2-rc.1", "0.1.5-rc.1")

    def test_prerelease_below_release(self):
        self._lt("0.1.5-rc.1", "0.1.5")

    def test_prerelease_tag_order(self):
        # 同数字段：字母段按字典序，alpha < rc
        self._lt("0.1.5-alpha.2", "0.1.5-rc.1")

    def test_prerelease_numeric_part(self):
        self._lt("0.1.5-rc.1", "0.1.5-rc.2")

    def test_equal(self):
        self.assertEqual(svc._semver_key("0.1.2-rc.1"), svc._semver_key("v0.1.2-rc.1"))

    def test_unparsable(self):
        self.assertIsNone(svc._semver_key(""))
        self.assertIsNone(svc._semver_key("latest"))
        self.assertIsNone(svc._semver_key("0.1.x-rc.1"))

    def test_short_version_pads_zero(self):
        self._lt("0.1", "0.1.1")


class TestHasUpdate(unittest.TestCase):
    def setUp(self):
        self._saved = (svc.dsh_version, svc.dsh_latest_version)

    def tearDown(self):
        svc.dsh_version, svc.dsh_latest_version = self._saved

    def _patch(self, cur, latest):
        svc.dsh_version = lambda: cur
        svc.dsh_latest_version = lambda: latest

    def test_update_available(self):
        self._patch("0.1.2-rc.1", "0.1.5-rc.1")
        self.assertTrue(svc.dsh_has_update())

    def test_no_update_when_equal(self):
        self._patch("0.1.5-rc.1", "0.1.5-rc.1")
        self.assertFalse(svc.dsh_has_update())

    def test_local_newer_than_registry(self):
        self._patch("0.2.0", "0.1.5-rc.1")
        self.assertFalse(svc.dsh_has_update())

    def test_unknown_when_missing(self):
        self._patch(None, "0.1.5-rc.1")
        self.assertIsNone(svc.dsh_has_update())
        self._patch("0.1.2-rc.1", None)
        self.assertIsNone(svc.dsh_has_update())


class TestDshUpdateGuard(unittest.TestCase):
    """「更新」按钮只在检测到有更新时才执行安装。"""

    def setUp(self):
        svc._dsh_version_cache.clear()
        self._saved = {
            "ver": svc.dsh_version,
            "latest": svc.dsh_latest_version,
            "run": svc.subprocess.run,
        }
        self.calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            self.calls.append(list(cmd))

            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            return R()

        svc.subprocess.run = fake_run

    def tearDown(self):
        svc.dsh_version = self._saved["ver"]
        svc.dsh_latest_version = self._saved["latest"]
        svc.subprocess.run = self._saved["run"]
        svc._dsh_version_cache.clear()

    def _patch(self, cur, latest):
        svc.dsh_version = lambda: cur
        svc.dsh_latest_version = lambda: latest

    def test_up_to_date_installs_nothing(self):
        self._patch("0.1.5-rc.1", "0.1.5-rc.1")
        ok, msg = svc.dsh_update()
        self.assertTrue(ok)
        self.assertIn("已是最新", msg)
        self.assertEqual(self.calls, [], "已是最新时不允许执行任何安装命令")

    def test_local_newer_installs_nothing(self):
        self._patch("0.2.0", "0.1.5-rc.1")
        ok, msg = svc.dsh_update()
        self.assertTrue(ok)
        self.assertEqual(self.calls, [])

    def test_registry_unreachable_installs_nothing(self):
        self._patch("0.1.2-rc.1", None)
        ok, msg = svc.dsh_update()
        self.assertFalse(ok)
        self.assertIn("不做更新", msg)
        self.assertEqual(self.calls, [])

    def test_update_available_runs_install(self):
        self._patch("0.1.2-rc.1", "0.1.5-rc.1")
        ok, msg = svc.dsh_update()
        self.assertTrue(ok)
        self.assertTrue(self.calls, "检测到更新时应执行安装命令")
        joined = " ".join(self.calls[0])
        self.assertIn("@deepseek-ai/dsh", joined)
        self.assertIn("@latest", joined)
        self.assertIn("已更新", msg)

    def test_unparsable_local_installs_nothing(self):
        self._patch("garbage", "0.1.5-rc.1")
        ok, msg = svc.dsh_update()
        self.assertFalse(ok)
        self.assertIn("不做更新", msg)
        self.assertEqual(self.calls, [])


class TestVersionStatusLine(unittest.TestCase):
    def setUp(self):
        svc._dsh_version_cache.clear()
        self._saved = (svc.dsh_version, svc.dsh_latest_version)
        svc.dsh_version = lambda: "0.1.2-rc.1"

    def tearDown(self):
        svc.dsh_version, svc.dsh_latest_version = self._saved
        svc._dsh_version_cache.clear()

    def test_no_latest_cached(self):
        self.assertEqual(svc._dsh_version_status_line(), "版本：0.1.2-rc.1")

    def test_newer_latest_cached(self):
        import time as _t
        svc._dsh_version_cache["latest"] = (_t.time(), "0.1.5-rc.1")
        line = svc._dsh_version_status_line()
        self.assertIn("0.1.5-rc.1", line)
        self.assertIn("点「更新」", line)

    def test_same_latest_cached(self):
        import time as _t
        svc.dsh_version = lambda: "0.1.5-rc.1"
        svc._dsh_version_cache["latest"] = (_t.time(), "0.1.5-rc.1")
        self.assertEqual(
            svc._dsh_version_status_line(), "版本：0.1.5-rc.1（当前已是最新版本，无需更新）"
        )

    def test_local_newer_than_registry_cached(self):
        # 本地比 registry 还新 → 也按「已是最新」提示
        import time as _t
        svc.dsh_version = lambda: "0.2.0"
        svc._dsh_version_cache["latest"] = (_t.time(), "0.1.5-rc.1")
        self.assertIn("无需更新", svc._dsh_version_status_line())


class TestHasUpdateCached(unittest.TestCase):
    """UI 轮询用的纯缓存判断（不发网络/子进程），按钮显隐依赖它。"""

    def setUp(self):
        svc._dsh_version_cache.clear()

    def tearDown(self):
        svc._dsh_version_cache.clear()

    def _set(self, cur, latest):
        import time as _t
        if cur is not ...:
            svc._dsh_version_cache["installed"] = (_t.time(), cur)
        if latest is not ...:
            svc._dsh_version_cache["latest"] = (_t.time(), latest)

    def test_cache_empty_is_none(self):
        self.assertIsNone(svc.dsh_has_update_cached())

    def test_latest_none_is_none(self):
        self._set("0.1.2-rc.1", None)
        self.assertIsNone(svc.dsh_has_update_cached())

    def test_update_available(self):
        self._set("0.1.2-rc.1", "0.1.5-rc.1")
        self.assertTrue(svc.dsh_has_update_cached())

    def test_up_to_date(self):
        self._set("0.1.5-rc.1", "0.1.5-rc.1")
        self.assertFalse(svc.dsh_has_update_cached())

    def test_local_newer(self):
        self._set("0.2.0", "0.1.5-rc.1")
        self.assertFalse(svc.dsh_has_update_cached())


if __name__ == "__main__":
    unittest.main()
