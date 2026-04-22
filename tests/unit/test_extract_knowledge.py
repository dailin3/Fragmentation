"""单元测试 - extract_knowledge 流程（mock AI）。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.storage.db import Database


def _setup_project(tmpdir):
    """创建完整的项目目录结构。"""
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
        '---\ntype: subdomain\ntopic: [[技术学习]]\ncreated: 2026-04-22\n---\n\n# C++\n\n系统级\n')
    (root / "02-notes" / "tree" / "Python.md").write_text(
        '---\ntype: subdomain\ntopic: [[技术学习]]\ncreated: 2026-04-22\n---\n\n# Python\n\n脚本\n')

    (root / "01-diary" / "test.md").write_text("今天学了C++的指针")
    return root


def _apply_patches(root):
    """Patch config values at consuming module level."""
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


class TestExtractKnowledge(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _setup_project(self.tmpdir.name)
        self._patchers = _apply_patches(self.root)

    def tearDown(self):
        _remove_patches(self._patchers)
        self.tmpdir.cleanup()

    def _mock_call_ai(self, extractions=None, needs_clarification=False, questions=None):
        """返回 mock 函数。"""
        def mock_fn(prompt):
            return {
                "extractions": extractions or [],
                "needs_clarification": needs_clarification,
                "questions": questions or [],
                "add_subdomain": None,
            }
        return mock_fn

    def test_successful_extraction(self):
        from src.storage.db import Database
        from src.logic.extract_knowledge import extract_knowledge

        extractions = [{
            "topic": "技术学习",
            "subdomain": "C++",
            "keyword": "指针",
            "content": "学习了指针的基本概念",
        }]
        with patch("src.logic.extract_knowledge.call_ai", self._mock_call_ai(extractions)):
            db = Database()
            # Pre-populate subdomain so the extraction passes validation
            db.add_subdomain("C++", "技术学习", "系统级")
            result = extract_knowledge(str(self.root / "01-diary" / "test.md"), db)
            db.close()

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["notes"]), 1)
        # Verify diary_processed was recorded
        db2 = Database()
        self.assertTrue(db2.is_diary_processed(str(self.root / "01-diary" / "test.md")))
        stats = db2.get_processing_stats()
        self.assertEqual(stats.get("success", 0), 1)
        db2.close()

    def test_needs_clarification(self):
        from src.logic.extract_knowledge import extract_knowledge

        with patch("src.logic.extract_knowledge.call_ai",
                   self._mock_call_ai(needs_clarification=True, questions=["请补充"])):
            result = extract_knowledge(str(self.root / "01-diary" / "test.md"),
                                       enable_clarification=True)

        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("session_id", result)
        # Verify diary_processed was recorded with needs_clarification status
        db = Database()
        self.assertTrue(db.is_diary_processed(str(self.root / "01-diary" / "test.md")))
        stats = db.get_processing_stats()
        self.assertEqual(stats.get("needs_clarification", 0), 1)
        db.close()

    def test_add_subdomain_auto_create(self):
        """AI 请求新 subdomain 时，自动创建后重新提取。"""
        from src.storage.db import Database
        from src.logic.extract_knowledge import extract_knowledge

        call_count = [0]
        def mock_fn(prompt):
            call_count[0] += 1
            if call_count[0] == 1:
                # 第一次请求：AI 要求创建新 subdomain
                return {
                    "extractions": [],
                    "needs_clarification": False,
                    "questions": [],
                    "add_subdomain": {"name": "Rust", "topic": "编程语言", "description": "安全系统编程"},
                }
            else:
                # 第二次请求（创建后重提）：成功提取
                return {
                    "extractions": [{
                        "topic": "编程语言",
                        "subdomain": "Rust",
                        "keyword": "所有权",
                        "content": "所有权是Rust的核心概念",
                    }],
                    "needs_clarification": False,
                    "questions": [],
                    "add_subdomain": None,
                }

        with patch("src.logic.extract_knowledge.call_ai", mock_fn):
            db = Database()
            result = extract_knowledge(str(self.root / "01-diary" / "test.md"), db)
            db.close()

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["notes"]), 1)
        # 验证新 subdomain 被创建
        db2 = Database()
        self.assertTrue(db2.subdomain_exists("Rust"))
        db2.close()


if __name__ == "__main__":
    unittest.main()
