import unittest

from app_ado.models import TaskSettings, UiSettings
from app_ado.store import migrate_acl_task_ids


class TestAclMigrate(unittest.TestCase):
    def test_acl_legacy_flow_to_uuid(self):
        # dynamic task with legacy_flow_id
        ts = TaskSettings.model_validate(
            {
                "tasks": [
                    {
                        "id": "uuid-1",
                        "tg_command": "sync_build_release",
                        "tg_desc": "desc",
                        "legacy_flow_id": "sync_build_release",
                        "git_flow": {"update_branches": ["main"], "merges": [], "push_branches": []},
                        "targets": [],
                    }
                ]
            }
        )
        s = UiSettings.model_validate(
            {
                "telegram_acl_groups": [
                    {"id": "g1", "name": "g", "can_run": True, "task_ids": ["sync_build_release"]}
                ]
            }
        )

        s2, changed = migrate_acl_task_ids(s, ts)
        self.assertTrue(changed)
        self.assertEqual(["uuid-1"], s2.telegram_acl_groups[0]["task_ids"])


if __name__ == "__main__":
    unittest.main()
