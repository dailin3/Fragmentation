"""单元测试 - NoteStore。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.storage.note_store import NoteStore


class TestNoteStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.notes_dir = Path(self.tmpdir.name)
        self.templates_dir = Path(self.tmpdir.name) / "templates"
        self.templates_dir.mkdir()
        (self.templates_dir / "note.md").write_text(
            '---\norigin: "{{SOURCE_DATE}}"\nsubdomain: "[[{{SUBDOMAIN}}]]"\n'
            'keyword: "{{KEYWORD}}"\ntags: [fragment]\ncreated: "{{NOW_DATE}}"\n---\n\n{{CONTENT}}',
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_write_note_content(self):
        with patch("src.storage.note_store.NOTES_DIR", self.notes_dir), \
             patch("src.storage.note_store.TEMPLATES_DIR", self.templates_dir):
            store = NoteStore()
            fp = store.write_note(
                topic="技术学习", subdomain="C++", keyword="test_kw",
                content="这是测试内容", source="test.md", source_date="2024-01-01",
            )
            text = Path(fp).read_text(encoding="utf-8")
            self.assertIn("这是测试内容", text)
            self.assertIn("[[C++]]", text)
            self.assertIn("tags: [fragment]", text)


if __name__ == "__main__":
    unittest.main()
