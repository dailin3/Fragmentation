"""单元测试 - TreeStore。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.storage.tree_store import TreeStore


class TestTreeStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tree_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_read_tree_empty_dir(self):
        """tree 目录为空时返回只有 header 的文本。"""
        with patch("src.storage.tree_store.TREE_DIR", self.tree_dir):
            store = TreeStore()
            text = store.read_tree()
            self.assertEqual(text.strip(), "# Knowledge Tree")

    def test_read_tree_with_topic(self):
        """有 topic 文件时能正确读取。"""
        topic_file = self.tree_dir / "技术学习.md"
        topic_file.write_text("""---
type: topic
created: 2026-04-22
---

# 技术学习

## 子领域

  - [[C++]] — 系统级编程语言
""", encoding="utf-8")

        with patch("src.storage.tree_store.TREE_DIR", self.tree_dir):
            store = TreeStore()
            text = store.read_tree()
            self.assertIn("C++", text)

    def test_add_subdomain(self):
        """add_subdomain 创建 topic + subdomain 文件。"""
        with patch("src.storage.tree_store.TREE_DIR", self.tree_dir):
            store = TreeStore()
            store.add_subdomain("技术学习", "C++", "系统级编程语言")
            self.assertTrue((self.tree_dir / "C++.md").exists())
            text = store.read_tree()
            self.assertIn("C++", text)

    def test_get_subdomains(self):
        """get_subdomains 返回列表正确。"""
        with patch("src.storage.tree_store.TREE_DIR", self.tree_dir):
            store = TreeStore()
            store.add_subdomain("技术学习", "Python", "脚本语言")
            subs = store.get_subdomains()
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]["name"], "Python")


if __name__ == "__main__":
    unittest.main()
