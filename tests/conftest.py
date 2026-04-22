"""全局 pytest fixtures。"""
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 设置 PYTHONPATH
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_URL", "http://localhost:9999/chat/completions")


@pytest.fixture
def temp_project():
    """创建临时项目目录，包含所有必要的子目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for d in ["01-diary", "02-notes", "02-notes/tree", "templates", "logs"]:
            (root / d).mkdir(parents=True)

        # 创建默认模板
        (root / "templates" / "note.md").write_text(
            '''---
origin: "{{SOURCE_DATE}}"
subdomain: "[[{{SUBDOMAIN}}]]"
keyword: "{{KEYWORD}}"
tags: [fragment]
created: "{{NOW_DATE}}"
---

{{CONTENT}}
''')

        # 创建默认 extract_rules
        (root / "extract_rules.md").write_text(
            '''# 信息提取规则
- 只提取有长期价值或可复用的内容
- 日常琐事不提取
''')

        # 创建 tree.md 和 tree 目录
        (root / "tree.md").write_text("# Knowledge Tree\n")

        # 创建基本 topic 文件
        (root / "02-notes" / "tree" / "技术学习.md").write_text(
            '''---
type: topic
created: 2026-04-22
---

# 技术学习

## 子领域

  - [[C++]] — 系统级编程语言
  - [[Python]] — 脚本语言
''')

        (root / "02-notes" / "tree" / "C++.md").write_text(
            '''---
type: subdomain
topic: [[技术学习]]
created: 2026-04-22
---

# C++

系统级编程语言
''')

        (root / "02-notes" / "tree" / "Python.md").write_text(
            '''---
type: subdomain
topic: [[技术学习]]
created: 2026-04-22
---

# Python

脚本语言
''')

        yield root


@pytest.fixture
def mock_config(temp_project):
    """将所有配置指向临时目录。"""
    with patch("src.config.DIARY_DIR", temp_project / "01-diary"),          patch("src.config.NOTES_DIR", temp_project / "02-notes"),          patch("src.config.TREE_DIR", temp_project / "02-notes" / "tree"),          patch("src.config.TREE_FILE", temp_project / "tree.md"),          patch("src.config.EXTRACT_RULES_FILE", temp_project / "extract_rules.md"),          patch("src.config.DB_PATH", temp_project / "fragments.db"),          patch("src.config.LOGS_DIR", temp_project / "logs"),          patch("src.config.TEMPLATES_DIR", temp_project / "templates"),          patch("src.config.DEEPSEEK_API_KEY", "test-key"),          patch("src.config.DEEPSEEK_API_URL", "http://localhost:9999"),          patch("src.config.DEEPSEEK_MODEL", "deepseek-chat"):
        yield temp_project


@pytest.fixture
def mock_db(mock_config):
    """返回一个干净的 Database 实例。"""
    from src.storage.db import Database
    db = Database()
    yield db
    db.close()


def mock_ai_response(extractions=None, needs_clarification=False, questions=None, add_subdomain=None):
    """构造 AI 返回结果。"""
    if needs_clarification:
        return {
            "extractions": extractions or [],
            "needs_clarification": True,
            "questions": questions or ["请补充信息"],
            "add_subdomain": add_subdomain,
        }
    return {
        "extractions": extractions or [],
        "needs_clarification": False,
        "questions": [],
        "add_subdomain": add_subdomain,
    }
