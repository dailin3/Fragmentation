"""集成测试 - 模块间调用。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _setup_project(tmpdir):
    root = Path(tmpdir)
    for d in ["01-diary", "02-notes/tree", "templates", "logs"]:
        (root / d).mkdir(parents=True)
    (root / "templates" / "note.md").write_text(
        '---\norigin: "{{SOURCE_DATE}}"\nsubdomain: "[[{{SUBDOMAIN}}]]"\n'
        'keyword: "{{KEYWORD}}"\ntags: [fragment]\ncreated: "{{NOW_DATE}}"\n---\n\n{{CONTENT}}')
    (root / "extract_rules.md").write_text("# 规则\n")
    (root / "02-notes" / "tree" / "技术学习.md").write_text(
        '---\ntype: topic\ncreated: 2026-04-22\n---\n\n# 技术学习\n\n## 子领域\n\n  - [[C++]] — 系统级\n')
    (root / "02-notes" / "tree" / "C++.md").write_text(
        '---\ntype: subdomain\ntopic: [[技术学习]]\ncreated: 2026-04-22\n---\n\n# C++\n')
    (root / "01-diary" / "test.md").write_text("今天测试了C++的指针")
    return root


def _apply_patches(root):
    ps = [
        patch("src.storage.note_store.NOTES_DIR", root / "02-notes"),
        patch("src.storage.note_store.TEMPLATES_DIR", root / "templates"),
        patch("src.storage.tree_store.TREE_DIR", root / "02-notes" / "tree"),
        patch("src.storage.db.DB_PATH", root / "fragments.db"),
    ]
    for p in ps:
        p.start()
    return ps


def _remove_patches(patchers):
    for p in patchers:
        p.stop()


class TestClarificationFlow(unittest.TestCase):
    """澄清会话的完整流程：创建 -> 回答 -> 获取补充内容。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def test_clarification_lifecycle(self):
        from src.logic.ask_clarification import ask_clarification, ClarificationManager

        # Create session with absolute path
        session = ClarificationManager.create(str(self.root / "01-diary" / "test.md"), ["Q1?", "Q2?"])
        self.assertIsNotNone(session.session_id)
        self.assertEqual(session.status, "pending")

        # Answer
        result = ask_clarification(session.session_id, ["A1", "A2"])
        self.assertNotIn("error", result)
        self.assertEqual(result["answers"], ["A1", "A2"])

        # Get clarified content
        content = ClarificationManager.get_clarified_content(session.session_id)
        self.assertIn("Q1?", content)
        self.assertIn("A1", content)
        self.assertIn("Q2?", content)
        self.assertIn("A2", content)

    def test_clarification_not_found(self):
        from src.logic.ask_clarification import ask_clarification

        result = ask_clarification("不存在的id", ["answer"])
        self.assertIn("error", result)


class TestTreeStoreIntegration(unittest.TestCase):
    """TreeStore 的 topic + subdomain 联动。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def test_add_subdomain_creates_both_files(self):
        from src.storage.tree_store import TreeStore
        store = TreeStore()
        store.add_subdomain("技术学习", "Python", "脚本语言")

        # Topic file should have link
        topic_text = (self.root / "02-notes" / "tree" / "技术学习.md").read_text()
        self.assertIn("[[Python]]", topic_text)

        # Subdomain file should exist
        sd_text = (self.root / "02-notes" / "tree" / "Python.md").read_text()
        self.assertIn("type: subdomain", sd_text)
        self.assertIn("[[技术学习]]", sd_text)


class TestNoteStoreIntegration(unittest.TestCase):
    """NoteStore 写入 + 读取。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def test_write_and_read_note(self):
        from src.storage.note_store import NoteStore
        store = NoteStore()
        fp = store.write_note(
            topic="技术学习", subdomain="C++", keyword="指针",
            content="指针是指向内存地址的变量", source="test.md", source_date="2024-01-01",
        )
        data = store.read_note(fp)
        self.assertIn("指针", data["meta"]["keyword"])
        self.assertIn("[[C++]]", data["meta"]["subdomain"])
        self.assertIn("指针是指向内存地址的变量", data["content"])
        self.assertEqual(data["meta"]["tags"], "[fragment]")


if __name__ == "__main__":
    unittest.main()
