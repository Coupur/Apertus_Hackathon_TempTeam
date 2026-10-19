"""Local credential loading without committing secrets or overriding the shell."""
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


CONFIG = Path(__file__).resolve().parents[1] / "src" / "navigator" / "config.py"


class LocalConfigTests(unittest.TestCase):
    def load(self, content=None, environment=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "src" / "navigator" / "config.py"
            config.parent.mkdir(parents=True)
            config.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
            if content is not None:
                (root / ".env").write_text(content, encoding="utf-8-sig")
            with patch.dict(os.environ, environment or {}, clear=True):
                return runpy.run_path(str(config))

    def test_loads_repo_local_settings_with_bom_and_quotes(self):
        settings = self.load('LLM_BASE_URL=https://gateway.example/api/v1\nLLM_NAME=model-test\nLLM_API_KEY="test-only-token"\n')
        self.assertTrue(settings["LLM_ENABLED"])
        self.assertEqual(settings["LLM_NAME"], "model-test")
        self.assertEqual(settings["LLM_API_KEY"], "test-only-token")

    def test_environment_wins_and_values_are_not_expanded(self):
        settings = self.load('LLM_NAME=local\nLLM_API_KEY=literal-${EXAMPLE}\n',
                             {"LLM_NAME": "environment", "EXAMPLE": "expanded"})
        self.assertEqual(settings["LLM_NAME"], "environment")
        self.assertEqual(settings["LLM_API_KEY"], "literal-${EXAMPLE}")

    def test_missing_file_keeps_llm_optional(self):
        settings = self.load()
        self.assertFalse(settings["LLM_ENABLED"])
        self.assertEqual(settings["LLM_API_KEY"], "")


if __name__ == "__main__":
    unittest.main()
