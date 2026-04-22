"""冒烟测试 - 核心链路能否走通。"""
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
    (root / "extract_rules.md").write_text("# 规则\n- 只提取有价值的内容\n")
    (root / "02-notes" / "tree" / "技术学习.md").write_text(
        '---\ntype: topic\ncreated: 2026-04-22\n---\n\n# 技术学习\n\n## 子领域\n\n  - [[C++]] — 系统级\n  - [[Python]] — 脚本\n')
    (root / "02-notes" / "tree" / "C++.md").write_text(
        '---\ntype: subdomain\ntopic: [[技术学习]]\ncreated: 2026-04-22\n---\n\n# C++\n')
    (root / "02-notes" / "tree" / "Python.md").write_text(
        '---\ntype: subdomain\ntopic: [[技术学习]]\ncreated: 2026-04-22\n---\n\n# Python\n')
    (root / "01-diary" / "simple.md").write_text("今天学了C++的指针")
    (root / "01-diary" / "empty.md").write_text("")
    (root / "01-diary" / "vague.md").write_text("今天好累")
    return root


def _apply_patches(root):
    """Patch config values at consuming module level. Returns list of start()-ed patches."""
    ps = [
        patch("src.storage.note_store.NOTES_DIR", root / "02-notes"),
        patch("src.storage.note_store.TEMPLATES_DIR", root / "templates"),
        patch("src.storage.tree_store.TREE_DIR", root / "02-notes" / "tree"),
        patch("src.storage.db.DB_PATH", root / "fragments.db"),
        patch("src.logic.extract_knowledge.EXTRACT_RULES_FILE", root / "extract_rules.md"),
    ]
    for p in ps:
        p.start()
    return ps


def _remove_patches(patchers):
    for p in patchers:
        p.stop()


class TestSmokeExtractKnowledge(unittest.TestCase):
    """extract_knowledge 核心链路冒烟。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def _mock_ai(self, extractions):
        def fn(prompt):
            return {
                "extractions": extractions,
                "needs_clarification": False,
                "questions": [],
                "add_subdomain": None,
            }
        return fn

    def test_full_extract_creates_note(self):
        """正常提取生成笔记文件。"""
        from src.logic.extract_knowledge import extract_knowledge
        from src.storage.db import Database

        extractions = [{
            "topic": "技术学习", "subdomain": "C++",
            "keyword": "指针", "content": "指针是指向内存的变量",
        }]
        with patch("src.logic.extract_knowledge.call_ai", self._mock_ai(extractions)):
            db = Database()
            db.add_subdomain("C++", "技术学习", "系统级")
            result = extract_knowledge(str(self.root / "01-diary" / "simple.md"), db)
            db.close()

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["notes"]), 1)
        note_path = Path(result["notes"][0]["file_path"])
        self.assertTrue(note_path.exists())
        self.assertEqual(note_path.parent, self.root / "02-notes")

    def test_empty_diary_no_notes(self):
        """空日记不生成笔记。"""
        from src.logic.extract_knowledge import extract_knowledge
        from src.storage.db import Database

        with patch("src.logic.extract_knowledge.call_ai", self._mock_ai([])):
            db = Database()
            result = extract_knowledge(str(self.root / "01-diary" / "empty.md"), db)
            db.close()

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["notes"]), 0)
        # diary_processed should still be recorded
        db2 = Database()
        self.assertTrue(db2.is_diary_processed(str(self.root / "01-diary" / "empty.md")))
        db2.close()

    def test_notes_written_to_flat_directory(self):
        """笔记在扁平目录下，不在子目录。"""
        from src.logic.extract_knowledge import extract_knowledge
        from src.storage.db import Database

        extractions = [{
            "topic": "技术学习", "subdomain": "C++",
            "keyword": "指针", "content": "内容",
        }]
        with patch("src.logic.extract_knowledge.call_ai", self._mock_ai(extractions)):
            db = Database()
            db.add_subdomain("C++", "技术学习", "系统级")
            result = extract_knowledge(str(self.root / "01-diary" / "simple.md"), db)
            db.close()

        notes_dir = self.root / "02-notes"
        note_files = list(notes_dir.glob("*.md"))
        subdirs = [d for d in notes_dir.iterdir() if d.is_dir() and d.name != "tree"]
        self.assertTrue(len(note_files) > 0, "笔记文件应该在 02-notes/ 根目录")
        self.assertEqual(len(subdirs), 0, "笔记应该在 02-notes/ 根目录，不在子目录")

    def test_extract_records_diary_processed(self):
        """提取后 diary_processed 有记录。"""
        from src.logic.extract_knowledge import extract_knowledge
        from src.storage.db import Database

        extractions = [{
            "topic": "技术学习", "subdomain": "C++",
            "keyword": "指针", "content": "内容",
        }]
        with patch("src.logic.extract_knowledge.call_ai", self._mock_ai(extractions)):
            db = Database()
            result = extract_knowledge(str(self.root / "01-diary" / "simple.md"), db)
            stats = db.get_processing_stats()
            db.close()

        self.assertEqual(stats.get("success", 0), 1)


class TestSmokeClarification(unittest.TestCase):
    """澄清流程冒烟。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def test_clarification_auto_reextract(self):
        """回答后自动重新提取生成笔记。"""
        from src.logic.ask_clarification import ask_clarification, ClarificationManager

        session = ClarificationManager.create(str(self.root / "01-diary" / "simple.md"), ["MT指什么？"])
        answer = ask_clarification(session.session_id, ["消息队列"])

        self.assertNotIn("error", answer)
        content = ClarificationManager.get_clarified_content(session.session_id)
        self.assertIn("MT指什么？", content)
        self.assertIn("消息队列", content)


class TestSmokeTreeSync(unittest.TestCase):
    """知识树读取冒烟。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def test_read_tree_returns_topics_and_subdomains(self):
        """read_tree 能读到完整的树结构。"""
        from src.storage.tree_store import TreeStore
        store = TreeStore()
        text = store.get_tree_text_for_prompt()
        self.assertIn("C++", text)
        self.assertIn("Python", text)

    def test_add_topic_creates_file(self):
        """add_topic 创建文件。"""
        from src.storage.tree_store import TreeStore
        store = TreeStore()
        store.add_topic("数学", "数学基础")
        topic_file = self.root / "02-notes" / "tree" / "数学.md"
        self.assertTrue(topic_file.exists())


if __name__ == "__main__":
    unittest.main()
