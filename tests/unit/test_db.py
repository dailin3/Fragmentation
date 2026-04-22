"""单元测试 - 数据库 CRUD + 新表。"""
import tempfile
import unittest
from pathlib import Path

from src.storage.db import Database


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = Database(db_path=self.tmp.name)

    def tearDown(self):
        self.db.close()

    def test_add_and_get_topic(self):
        self.db.add_topic("技术学习", "编程相关")
        topic = self.db.get_topic("技术学习")
        self.assertEqual(topic["name"], "技术学习")
        self.assertIsNone(self.db.get_topic("不存在的主题"))

    def test_add_and_get_note(self):
        self.db.add_topic("技术学习", "编程")
        self.db.add_subdomain("技术学习", "C++", "面向对象")
        self.db.add_note(
            filename="test-2024-01-01.md",
            topic="技术学习",
            subdomain="C++",
            keyword="test",
            source="20240101.md",
            content="测试内容",
            file_path="/tmp/test.md",
        )
        note = self.db.get_note("test-2024-01-01.md")
        self.assertEqual(note["keyword"], "test")
        self.assertEqual(note["content"], "测试内容")

    def test_add_and_list_subdomains(self):
        self.db.add_topic("技术学习", "编程")
        self.db.add_subdomain("C++", "技术学习", "系统级")
        self.db.add_subdomain("Python", "技术学习", "脚本")
        subs = self.db.list_subdomains("技术学习")
        self.assertGreaterEqual(len(subs), 2)

    def test_subdomain_exists(self):
        self.db.add_topic("技术学习", "")
        self.db.add_subdomain("C++", "技术学习", "")
        self.assertTrue(self.db.subdomain_exists("C++"))
        self.assertFalse(self.db.subdomain_exists("不存在的"))

    def test_list_notes_by_subdomain(self):
        self.db.add_topic("技术学习", "")
        self.db.add_subdomain("C++", "技术学习", "")
        self.db.add_note("n1.md", "技术学习", "C++", "kw1", "src.md", "c", "/tmp/n1.md")
        self.db.add_note("n2.md", "技术学习", "C++", "kw2", "src.md", "c", "/tmp/n2.md")
        notes = self.db.list_notes(subdomain="C++")
        self.assertGreaterEqual(len(notes), 2)

    def test_list_topics(self):
        self.db.add_topic("A", "")
        self.db.add_topic("B", "")
        topics = self.db.list_topics()
        self.assertEqual(len(topics), 2)


class TestDiaryProcessed(unittest.TestCase):
    """diary_processed 表测试。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = Database(db_path=self.tmp.name)

    def tearDown(self):
        self.db.close()

    def test_mark_and_check(self):
        self.db.mark_diary_processed("/path/a.md", "a.md", "success", notes_count=3)
        self.assertTrue(self.db.is_diary_processed("/path/a.md"))
        self.assertFalse(self.db.is_diary_processed("/path/b.md"))

    def test_stats(self):
        self.db.mark_diary_processed("/a.md", "a.md", "success", notes_count=1)
        self.db.mark_diary_processed("/b.md", "b.md", "success", notes_count=2)
        self.db.mark_diary_processed("/c.md", "c.md", "error", error_message="oops")
        stats = self.db.get_processing_stats()
        self.assertEqual(stats["success"], 2)
        self.assertEqual(stats["error"], 1)

    def test_update_existing(self):
        """同一路径重复写入应更新。"""
        self.db.mark_diary_processed("/a.md", "a.md", "error", error_message="err1")
        self.db.mark_diary_processed("/a.md", "a.md", "success", notes_count=1)
        self.assertTrue(self.db.is_diary_processed("/a.md"))


class TestClarificationSessions(unittest.TestCase):
    """clarification_sessions 表测试。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = Database(db_path=self.tmp.name)

    def tearDown(self):
        self.db.close()

    def test_save_and_get(self):
        self.db.save_session("s1", "/path/a.md", ["Q1?", "Q2?"])
        session = self.db.get_session("s1")
        self.assertIsNotNone(session)
        self.assertEqual(session["original_file"], "/path/a.md")
        self.assertEqual(session["questions"], ["Q1?", "Q2?"])
        self.assertEqual(session["status"], "pending")

    def test_update_answers(self):
        self.db.save_session("s1", "/path/a.md", ["Q1?"])
        self.db.update_session_answers("s1", ["A1"])
        session = self.db.get_session("s1")
        self.assertEqual(session["answers"], ["A1"])
        self.assertEqual(session["status"], "answered")
        self.assertIsNotNone(session["answered_at"])

    def test_list_pending(self):
        self.db.save_session("s1", "/a.md", ["Q1"])
        self.db.save_session("s2", "/b.md", ["Q2"])
        self.db.update_session_answers("s1", ["A1"])
        pending = self.db.list_pending_sessions()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["session_id"], "s2")

    def test_delete_session(self):
        self.db.save_session("s1", "/a.md", ["Q1"])
        self.db.delete_session("s1")
        self.assertIsNone(self.db.get_session("s1"))

    def test_get_nonexistent(self):
        self.assertIsNone(self.db.get_session("nope"))


class TestTreeSync(unittest.TestCase):
    """Tree 同步方法测试。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = Database(db_path=self.tmp.name)

    def tearDown(self):
        self.db.close()

    def test_sync_topics_adds_and_removes(self):
        # Add a topic not in tree
        self.db.add_topic("旧topic", "应该被删除")
        # Sync with tree data
        self.db.sync_topics_from_tree([{"name": "技术学习", "description": ""}])
        self.assertIsNotNone(self.db.get_topic("技术学习"))
        self.assertIsNone(self.db.get_topic("旧topic"))

    def test_sync_subdomains(self):
        self.db.add_subdomain("旧sub", "旧topic", "应该被删除")
        self.db.sync_subdomains_from_tree([
            {"topic": "技术学习", "name": "C++", "description": "系统级"},
        ])
        self.assertIsNotNone(self.db.get_subdomain("C++"))
        self.assertIsNone(self.db.get_subdomain("旧sub"))


if __name__ == "__main__":
    unittest.main()
