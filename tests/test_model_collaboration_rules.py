import tempfile
import unittest
from pathlib import Path

from app_ado import model_collaboration_rules as rules


class ModelCollaborationRulesTest(unittest.TestCase):
    def test_repo_apply_keeps_non_markdown_bundle_files_valid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            template_root = tmp_path / "templates"
            codex_template = template_root / "codex"
            codex_template.mkdir(parents=True)
            (codex_template / "AGENTS.md").write_text("repo rules\n", "utf-8")
            (codex_template / "config.toml.template").write_text("model = \"gpt\"\n", "utf-8")

            original_template_dir = rules.TEMPLATE_DIR
            rules.TEMPLATE_DIR = template_root
            try:
                repo_root = tmp_path / "repo"

                result = rules.apply_rule_to_repo("codex", repo_root)

                self.assertTrue(result.ok)
                agents_text = (repo_root / "AGENTS.md").read_text("utf-8")
                config_text = (repo_root / "config.toml.template").read_text("utf-8")
                self.assertIn(rules.START_MARKER, agents_text)
                self.assertEqual("model = \"gpt\"\n", config_text)
                self.assertNotIn(rules.START_MARKER, config_text)

                (repo_root / "config.toml.template").write_text("model = \"custom\"\n", "utf-8")
                rules.apply_rule_to_repo("codex", repo_root)
                self.assertEqual(
                    "model = \"custom\"\n",
                    (repo_root / "config.toml.template").read_text("utf-8"),
                )

                rules.remove_rule_from_repo("codex", repo_root)
                self.assertNotIn(rules.START_MARKER, (repo_root / "AGENTS.md").read_text("utf-8"))
                self.assertEqual(
                    "model = \"custom\"\n",
                    (repo_root / "config.toml.template").read_text("utf-8"),
                )
            finally:
                rules.TEMPLATE_DIR = original_template_dir


if __name__ == "__main__":
    unittest.main()
