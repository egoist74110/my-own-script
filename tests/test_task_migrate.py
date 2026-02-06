import unittest

from app_ado.task_migrate import migrate_task_settings


class TestTaskMigrate(unittest.TestCase):
    def test_migrate_flows_to_tasks(self):
        raw = {
            "flows": [
                {
                    "id": "sync_merge_build_release",
                    "enabled": True,
                    "local_repo_path": "/tmp/repo",
                    "source_branch": "feat/a",
                    "target_branch": "feat/b",
                    "build_kind": "pipeline",
                    "build_id": "1",
                    "release_id": "2",
                    "release_stage_ids": ["10"],
                }
            ]
        }
        s, changed = migrate_task_settings(raw)
        self.assertTrue(changed)
        self.assertEqual(1, len(s.tasks))
        t = s.tasks[0]
        self.assertEqual("sync_merge_build_release", t.tg_command)
        self.assertEqual(["feat/a", "feat/b"], t.git_flow.update_branches)
        self.assertEqual(1, len(t.git_flow.merges))
        self.assertEqual("feat/a", t.git_flow.merges[0].source)
        self.assertEqual("feat/b", t.git_flow.merges[0].target)
        self.assertEqual(["feat/b"], t.git_flow.push_branches)
        self.assertEqual(1, len(t.targets))


if __name__ == "__main__":
    unittest.main()
