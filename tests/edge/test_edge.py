"""边界测试 + 异常测试。"""
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


class TestEdgeCases(unittest.TestCase):
    """边界条件测试。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def test_keyword_with_special_characters(self):
        """关键词包含特殊字符（斜杠、反斜杠）。"""
        from src.storage.note_store import NoteStore
        store = NoteStore()
        fp = store.write_note(
            topic="技术", subdomain="C++", keyword="指针/引用",
            content="内容", source="test.md", source_date="2024-01-01",
        )
        self.assertNotIn("/", Path(fp).name)

    def test_empty_content_note(self):
        """空内容笔记能正常写入。"""
        from src.storage.note_store import NoteStore
        store = NoteStore()
        fp = store.write_note(
            topic="技术", subdomain="C++", keyword="空",
            content="", source="test.md", source_date="2024-01-01",
        )
        self.assertTrue(Path(fp).exists())

    def test_read_nonexistent_tree(self):
        """tree 目录不存在时 read_tree 返回空字符串。"""
        import shutil
        shutil.rmtree(self.root / "02-notes" / "tree", ignore_errors=True)

        from src.storage.tree_store import TreeStore
        store = TreeStore()
        text = store.read_tree()
        # Returns empty string when tree dir doesn't exist
        self.assertEqual(text, "")

    def test_add_duplicate_subdomain(self):
        """重复添加同名 subdomain 不报错。"""
        from src.storage.tree_store import TreeStore
        store = TreeStore()
        store.add_subdomain("技术学习", "C++", "系统级")
        store.add_subdomain("技术学习", "C++", "系统级")

    def test_db_get_nonexistent_note(self):
        """获取不存在的笔记返回 None。"""
        from src.storage.db import Database
        db = Database()
        result = db.get_note("不存在的.md")
        self.assertIsNone(result)
        db.close()

    def test_db_duplicate_topic(self):
        """重复添加同名 topic 不报错。"""
        from src.storage.db import Database
        db = Database()
        db.add_topic("技术学习", "描述")
        db.add_topic("技术学习", "另一个描述")
        topics = db.list_topics()
        self.assertEqual(len(topics), 1)
        db.close()


class TestSecurityInputs(unittest.TestCase):
    """输入安全测试 - 防止路径穿越等。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def test_keyword_path_traversal(self):
        """关键词包含路径穿越字符，文件仍在 notes 目录。"""
        from src.storage.note_store import NoteStore
        store = NoteStore()
        fp = store.write_note(
            topic="技术", subdomain="C++", keyword="../../../etc/passwd",
            content="内容", source="test.md", source_date="2024-01-01",
        )
        note_path = Path(fp).resolve()
        notes_dir = (self.root / "02-notes").resolve()
        self.assertTrue(str(note_path).startswith(str(notes_dir)))

    def test_topic_name_injection(self):
        """topic 名称包含特殊字符。"""
        from src.storage.tree_store import TreeStore
        store = TreeStore()
        store.add_topic("技术<学习>", "描述<script>alert(1)</script>")
        topic_file = self.root / "02-notes" / "tree" / "技术<学习>.md"
        self.assertTrue(topic_file.exists())
        content = topic_file.read_text()
        self.assertIn("<script>alert(1)</script>", content)

    def test_empty_session_id(self):
        """空 session_id 不崩溃。"""
        from src.logic.ask_clarification import ask_clarification
        result = ask_clarification("", ["answer"])
        self.assertIn("error", result)


class TestRegression(unittest.TestCase):
    """回归测试 - 确保之前修复的 bug 不再出现。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def test_note_has_fragment_tag(self):
        """笔记必须包含 tags: [fragment]。"""
        from src.storage.note_store import NoteStore
        store = NoteStore()
        fp = store.write_note(
            topic="技术", subdomain="C++", keyword="test",
            content="内容", source="test.md", source_date="2024-01-01",
        )
        text = Path(fp).read_text(encoding="utf-8")
        self.assertIn("tags: [fragment]", text)

    def test_note_has_subdomain_link(self):
        """笔记必须包含 [[subdomain]] 双链。"""
        from src.storage.note_store import NoteStore
        store = NoteStore()
        fp = store.write_note(
            topic="技术", subdomain="C++", keyword="test",
            content="内容", source="test.md", source_date="2024-01-01",
        )
        text = Path(fp).read_text(encoding="utf-8")
        self.assertIn("[[C++]]", text)

    def test_note_no_topic_link(self):
        """笔记不应包含 [[topic]] 双链（只链 subdomain）。"""
        from src.storage.note_store import NoteStore
        store = NoteStore()
        fp = store.write_note(
            topic="技术", subdomain="C++", keyword="test",
            content="内容", source="test.md", source_date="2024-01-01",
        )
        text = Path(fp).read_text(encoding="utf-8")
        self.assertIn("[[C++]]", text)
        import re
        fm = text.split("---")[1] if text.count("---") >= 2 else ""
        self.assertNotRegex(fm, r'topic:\s*"\[\[')


if __name__ == "__main__":
    unittest.main()
