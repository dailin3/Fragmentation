import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fragmentation


class FakeModelClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            raise AssertionError("no fake response left")
        return self.responses.pop(0)


class AnalyzeSingleDiaryTests(unittest.TestCase):
    def test_create_model_client_from_env_uses_deepseek_as_default_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_path = root / ".env"
            env_path.write_text(
                "API_KEY=test-key\nAPI_URL=https://example.com/v1/chat/completions\n",
                encoding="utf-8",
            )

            client = fragmentation.create_model_client_from_env(env_path)

            self.assertEqual(client.api_key, "test-key")
            self.assertEqual(client.api_url, "https://example.com/v1/chat/completions")
            self.assertEqual(client.model, "deepseek-chat")

    def test_analyze_single_diary_retries_invalid_response_and_writes_fragments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            diary_dir = root / "01-diary"
            fragment_dir = root / "02-fragment"
            diary_dir.mkdir()
            fragment_dir.mkdir()

            diary_path = diary_dir / "20260419.md"
            diary_text = "我想研究双链。我要把知识系统开源。"
            diary_path.write_text(diary_text, encoding="utf-8")

            (fragment_dir / "existing.md").write_text("旧碎片内容", encoding="utf-8")
            (root / "prompt.md").write_text("请切片", encoding="utf-8")
            (root / "template.md").write_text(
                "---\norigin: \"{{DATE}}\"\ncreated: {{NOW-DATE}}\n---\n\n{{CONTENT}}\n",
                encoding="utf-8",
            )

            client = FakeModelClient(
                [
                    '{"fragments": [{"title": "双链", "content": "[[双链"}]}',
                    '{"fragments": ['
                    '{"title": "双链", "content": "我想研究[[双链]]。"}, '
                    '{"title": "双链", "content": "我要把知识系统开源。"}'
                    ']}'
                ]
            )

            result = fragmentation.analyze_single_diary(
                diary_path=diary_path,
                fragment_dir=fragment_dir,
                prompt_path=root / "prompt.md",
                template_path=root / "template.md",
                model_client=client,
                current_date="2026-04-19",
                max_attempts=2,
            )

            self.assertEqual(result["attempts"], 2)
            self.assertEqual(len(result["written_files"]), 2)
            self.assertTrue((fragment_dir / "双链.md").exists())
            self.assertTrue((fragment_dir / "双链-1.md").exists())

            first_output = (fragment_dir / "双链.md").read_text(encoding="utf-8")
            second_output = (fragment_dir / "双链-1.md").read_text(encoding="utf-8")
            log_output = result["log_path"].read_text(encoding="utf-8")

            self.assertIn('origin: "2026-04-19"', first_output)
            self.assertIn('created: 2026-04-19', first_output)
            self.assertIn("我想研究[[双链]]。", first_output)
            self.assertIn("我要把知识系统开源。", second_output)
            self.assertIn("attempt 1 invalid", log_output)
            self.assertIn("missing closing brackets", log_output)
            self.assertIn("existing.md", client.calls[0])
            self.assertIn(diary_text, client.calls[0])

    def test_main_analyzes_one_diary_from_cli_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            diary_dir = root / "01-diary"
            fragment_dir = root / "02-fragment"
            diary_dir.mkdir()
            fragment_dir.mkdir()

            diary_path = diary_dir / "20260419.md"
            diary_path.write_text("我想研究双链。", encoding="utf-8")
            (root / "prompt.md").write_text("请切片", encoding="utf-8")
            (root / "template.md").write_text(
                "---\norigin: \"{{DATE}}\"\ncreated: {{NOW-DATE}}\n---\n\n{{CONTENT}}\n",
                encoding="utf-8",
            )
            (root / ".env").write_text(
                "API_KEY=test-key\nAPI_URL=https://example.com/v1/chat/completions\n",
                encoding="utf-8",
            )

            fake_client = FakeModelClient(
                ['{"fragments": [{"title": "双链", "content": "我想研究[[双链]]。"}]}']
            )
            stdout = io.StringIO()

            with mock.patch.object(fragmentation, "create_model_client_from_env", return_value=fake_client):
                with contextlib.redirect_stdout(stdout):
                    exit_code = fragmentation.main(
                        [
                            "--project-root",
                            str(root),
                            "--diary",
                            str(diary_path),
                            "--current-date",
                            "2026-04-19",
                        ]
                    )

            self.assertEqual(exit_code, 0)
            self.assertTrue((fragment_dir / "双链.md").exists())
            self.assertIn("双链.md", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
