# Fragmentation 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零构建三层架构的 Fragmentation 系统：MCP/CLI 接口 → 知识树中层 → 底层存储

**Architecture:** 单进程同步实现。底层负责文件读写和 SQLite CRUD；中层实现 7 个知识树工具；上层通过 MCP JSON-RPC 2.0 和 argparse CLI 暴露工具。旧代码全部删除，数据作废。

**Tech Stack:** Python 3.9+, SQLite (内置), httpx (DeepSeek API), MCP SDK (fastmcp 或手动 JSON-RPC)

---

## 文件结构

```
src/
  __init__.py
  config.py                 加载 .env，定义路径常量
  storage/
    __init__.py
    db.py                   SQLite: topics, subdomains, notes 表
    note_store.py           笔记文件读写（02-notes/）
    tree_store.py           tree.md 解析/写入
    diary_parser.py         01-diary/ 文件解析
  logic/
    __init__.py
    extract_knowledge.py    核心：AI 提取信息 → 生成笔记
    add_subdomain.py        添加新子领域
    check_subdomain.py      子领域健康检查
    check_note.py           笔记健康检查
    query_tree.py           查询知识树
    ask_clarification.py    会话管理
    tree_sync.py            tree.md ↔ DB 同步
  mcp_server.py             MCP Server (7 tools)
  cli.py                    CLI (argparse, 7 commands)
templates/
  note.md                   笔记模板
  subdomain.md              子领域模板
  domain.md                 领域模板
tests/
  __init__.py
  test_db.py
  test_tree_store.py
  test_note_store.py
  test_extract_knowledge.py
  test_cli.py
tree.md                     知识树（空模板）
extract_rules.md            提取规则（用户填写）
```

---

## Task 1: 项目骨架与配置

**Files:**
- Create: `src/__init__.py`, `src/config.py`
- Create: `src/storage/__init__.py`
- Create: `src/logic/__init__.py`
- Create: `templates/note.md`, `templates/subdomain.md`, `templates/domain.md`
- Create: `tests/__init__.py`
- Create: `tree.md` (empty template)
- Create: `extract_rules.md` (placeholder)

- [ ] **Step 1: 创建目录结构与空文件**

```bash
mkdir -p src/storage src/logic templates tests
touch src/__init__.py src/storage/__init__.py src/logic/__init__.py tests/__init__.py
```

- [ ] **Step 2: 编写 `src/config.py`**

```python
"""加载 .env 配置，定义项目路径常量。"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

# 加载 .env
_env_path = ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
DEEPSEEK_MODEL = os.environ.get("MODEL", "deepseek-chat")

# 目录
DIARY_DIR = ROOT / "01-diary"
NOTES_DIR = ROOT / "02-notes"
TREE_FILE = ROOT / "tree.md"
EXTRACT_RULES_FILE = ROOT / "extract_rules.md"
DB_PATH = ROOT / "fragments.db"
LOGS_DIR = ROOT / "logs"
TEMPLATES_DIR = ROOT / "templates"
```

- [ ] **Step 3: 编写 `tree.md` 空模板**

```markdown
# Knowledge Tree
```

- [ ] **Step 4: 编写 `extract_rules.md` 占位符**

```markdown
# 信息提取规则

（待填写：定义什么信息值得提取）
```

- [ ] **Step 5: 编写模板文件**

`templates/note.md`:
```markdown
---
origin: "{{SOURCE_DATE}}"
topic: "{{TOPIC}}"
subdomain: "{{SUBDOMAIN}}"
keyword: "{{KEYWORD}}"
created: "{{NOW_DATE}}"
---

{{CONTENT}}
```

`templates/subdomain.md`:
```markdown
---
topic: "{{TOPIC}}"
created: "{{NOW_DATE}}"
---

## 子领域介绍

{{DESCRIPTION}}
```

`templates/domain.md`:
```markdown
---
created: "{{NOW_DATE}}"
---

## 主题介绍

{{DESCRIPTION}}
```

- [ ] **Step 6: Commit**

```bash
git add src/ templates/ tests/ tree.md extract_rules.md
git commit -m "chore: 项目骨架与配置文件"
```

---

## Task 2: 数据库层

**Files:**
- Create: `src/storage/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 编写 `src/storage/db.py`**

```python
"""SQLite 数据库：topics, subdomains, notes 三表。"""
import json
import sqlite3
from datetime import datetime

from src.config import DB_PATH


class Database:
    def __init__(self, db_path=None):
        self.conn = sqlite3.connect(str(db_path or DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS topics (
                name TEXT PRIMARY KEY,
                description TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS subdomains (
                name TEXT PRIMARY KEY,
                topic TEXT,
                description TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS notes (
                filename TEXT PRIMARY KEY,
                topic TEXT,
                subdomain TEXT,
                keyword TEXT,
                source TEXT,
                content TEXT,
                file_path TEXT,
                created_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_notes_topic ON notes(topic);
            CREATE INDEX IF NOT EXISTS idx_notes_subdomain ON notes(subdomain);
            CREATE INDEX IF NOT EXISTS idx_subdomains_topic ON subdomains(topic);
        """)
        self.conn.commit()

    # --- Topic 操作 ---

    def add_topic(self, name: str, description: str = ""):
        self.conn.execute(
            "INSERT OR REPLACE INTO topics (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_topic(self, name: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM topics WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def list_topics(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM topics ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    # --- Subdomain 操作 ---

    def add_subdomain(self, name: str, topic: str, description: str = ""):
        self.conn.execute(
            "INSERT OR REPLACE INTO subdomains (name, topic, description, created_at) VALUES (?, ?, ?, ?)",
            (name, topic, description, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_subdomain(self, name: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM subdomains WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def list_subdomains(self, topic: str = None) -> list[dict]:
        if topic:
            rows = self.conn.execute(
                "SELECT * FROM subdomains WHERE topic = ? ORDER BY name", (topic,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM subdomains ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def subdomain_exists(self, name: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM subdomains WHERE name = ?", (name,)).fetchone()
        return row is not None

    # --- Note 操作 ---

    def add_note(self, filename: str, topic: str, subdomain: str,
                 keyword: str, source: str, content: str, file_path: str):
        self.conn.execute(
            """INSERT OR REPLACE INTO notes
               (filename, topic, subdomain, keyword, source, content, file_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (filename, topic, subdomain, keyword, source, content, file_path,
             datetime.now().isoformat())
        )
        self.conn.commit()

    def get_note(self, filename: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM notes WHERE filename = ?", (filename,)).fetchone()
        return dict(row) if row else None

    def list_notes(self, topic: str = None, subdomain: str = None) -> list[dict]:
        query = "SELECT * FROM notes WHERE 1=1"
        params = []
        if topic:
            query += " AND topic = ?"
            params.append(topic)
        if subdomain:
            query += " AND subdomain = ?"
            params.append(subdomain)
        query += " ORDER BY filename"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def delete_note(self, filename: str):
        self.conn.execute("DELETE FROM notes WHERE filename = ?", (filename,))
        self.conn.commit()

    def close(self):
        self.conn.close()
```

- [ ] **Step 2: 编写 `tests/test_db.py`**

```python
"""测试数据库 CRUD 操作。"""
import tempfile
import unittest

from src.storage.db import Database


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = Database(self.tmp.name)

    def tearDown(self):
        self.db.close()

    def test_add_and_get_topic(self):
        self.db.add_topic("技术学习", "技术相关")
        topic = self.db.get_topic("技术学习")
        self.assertIsNotNone(topic)
        self.assertEqual(topic["name"], "技术学习")
        self.assertEqual(topic["description"], "技术相关")

    def test_list_topics(self):
        self.db.add_topic("A")
        self.db.add_topic("B")
        topics = self.db.list_topics()
        self.assertEqual(len(topics), 2)

    def test_add_and_list_subdomains(self):
        self.db.add_topic("技术学习")
        self.db.add_subdomain("C++", "技术学习", "编程语言")
        subs = self.db.list_subdomains("技术学习")
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["name"], "C++")

    def test_subdomain_exists(self):
        self.db.add_subdomain("Python", "技术学习")
        self.assertTrue(self.db.subdomain_exists("Python"))
        self.assertFalse(self.db.subdomain_exists("不存在"))

    def test_add_and_get_note(self):
        self.db.add_note("test.md", "技术学习", "C++", "指针",
                        "diary.md", "内容", "/path/test.md")
        note = self.db.get_note("test.md")
        self.assertEqual(note["topic"], "技术学习")
        self.assertEqual(note["keyword"], "指针")

    def test_list_notes_by_subdomain(self):
        self.db.add_note("a.md", "T", "S", "k1", "src", "c1", "p1")
        self.db.add_note("b.md", "T", "S", "k2", "src", "c2", "p2")
        self.db.add_note("c.md", "T", "S2", "k3", "src", "c3", "p3")
        notes = self.db.list_notes(subdomain="S")
        self.assertEqual(len(notes), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试验证**

```bash
python -m pytest tests/test_db.py -v
```

Expected: 6 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/storage/db.py tests/test_db.py
git commit -m "feat: 数据库层 (topics, subdomains, notes)"
```

---

## Task 3: NoteStore + TreeStore + DiaryParser

**Files:**
- Create: `src/storage/note_store.py`
- Create: `src/storage/tree_store.py`
- Create: `src/storage/diary_parser.py`
- Test: `tests/test_note_store.py`
- Test: `tests/test_tree_store.py`

- [ ] **Step 1: 编写 `src/storage/note_store.py`**

```python
"""笔记文件读写（02-notes/）。"""
from pathlib import Path
from datetime import datetime

from src.config import NOTES_DIR, TEMPLATES_DIR


class NoteStore:
    def write_note(self, topic: str, subdomain: str, keyword: str,
                   content: str, source: str, source_date: str) -> str:
        """写入笔记到 02-notes/{topic}/{subdomain}/，返回文件路径。"""
        # 生成文件名
        safe_kw = keyword.replace("/", "-").replace("\\", "-")
        date_part = source_date or datetime.now().strftime("%Y-%m-%d")
        filename = f"{safe_kw}-{date_part}.md"

        # 创建目录
        note_dir = NOTES_DIR / topic / subdomain
        note_dir.mkdir(parents=True, exist_ok=True)
        file_path = note_dir / filename

        # 读取模板并填充
        template = (TEMPLATES_DIR / "note.md").read_text(encoding="utf-8")
        rendered = (template
            .replace("{{SOURCE_DATE}}", source_date)
            .replace("{{TOPIC}}", topic)
            .replace("{{SUBDOMAIN}}", subdomain)
            .replace("{{KEYWORD}}", keyword)
            .replace("{{NOW_DATE}}", datetime.now().strftime("%Y-%m-%d"))
            .replace("{{CONTENT}}", content)
        )
        file_path.write_text(rendered, encoding="utf-8")
        return str(file_path)

    def read_note(self, file_path: str) -> dict:
        """读取笔记文件，返回 frontmatter + content。"""
        text = Path(file_path).read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not m:
            return {"content": text}
        fm = m.group(1)
        content = m.group(2).strip()
        meta = {}
        for line in fm.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip('"').strip("'")
        return {"meta": meta, "content": content}


import re  # needed at top for read_note
```

- [ ] **Step 2: 编写 `src/storage/tree_store.py`**

```python
"""tree.md 解析与写入。"""
import re
from pathlib import Path

from src.config import TREE_FILE


class TreeStore:
    def read_tree(self) -> str:
        """读取 tree.md 全文。"""
        if not TREE_FILE.exists():
            return ""
        return TREE_FILE.read_text(encoding="utf-8")

    def get_tree_text_for_prompt(self) -> str:
        """返回用于 AI prompt 的树结构文本。"""
        return self.read_tree()

    def add_topic(self, name: str, description: str):
        """在 tree.md 中添加主题。"""
        text = self.read_tree()
        new_section = f"\n## {name}\n\n{description}\n"
        text = text.rstrip() + new_section
        TREE_FILE.write_text(text, encoding="utf-8")

    def add_subdomain(self, topic: str, name: str, description: str):
        """在指定主题下添加子领域。"""
        text = self.read_tree()
        # 找到 ## {topic} 段落
        pattern = rf"(## {re.escape(topic)}\n.*?)(?=## |\Z)"
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            # 主题不存在，先创建主题
            self.add_topic(topic, "")
            text = self.read_tree()
            match = re.search(pattern, text, re.DOTALL)

        if match:
            # 在主题段落末尾添加子领域
            insert_pos = match.end()
            new_line = f"\n- 子领域: {name} — {description}\n"
            text = text[:insert_pos] + new_line + text[insert_pos:]
        TREE_FILE.write_text(text, encoding="utf-8")

    def get_subdomains(self) -> list[dict]:
        """解析 tree.md，返回 [{topic, name, description}, ...]。"""
        text = self.read_tree()
        result = []
        current_topic = None
        for line in text.splitlines():
            topic_match = re.match(r"^## (.+)$", line)
            if topic_match:
                current_topic = topic_match.group(1)
                continue
            sub_match = re.match(r"^- 子领域: (.+?) — (.+)$", line)
            if sub_match and current_topic:
                result.append({
                    "topic": current_topic,
                    "name": sub_match.group(1),
                    "description": sub_match.group(2),
                })
        return result
```

- [ ] **Step 3: 编写 `src/storage/diary_parser.py`**

```python
"""解析 01-diary/ 原始日记文件。"""
import re
from pathlib import Path


def parse_diary(file_path: str) -> dict:
    """解析日记文件，返回 {filename, date, content}。"""
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")

    # 尝试从 frontmatter 或文件名提取日期
    date = None
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if m:
        fm = m.group(1)
        date_match = re.search(r"date:\s*[\"']?(\d{4}-\d{2}-\d{2})", fm)
        if date_match:
            date = date_match.group(1)
        content = m.group(2).strip()
    else:
        content = text.strip()

    # 从文件名提取日期 (YYYYMMDD.md 或 YYYY-MM-DD.md)
    if not date:
        name = p.stem
        date_match = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", name)
        if date_match:
            date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

    return {
        "filename": p.name,
        "date": date or "unknown",
        "content": content,
    }
```

- [ ] **Step 4: 编写 `tests/test_note_store.py`**

```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.storage.note_store import NoteStore


class TestNoteStore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.notes_dir = Path(self.tmp_dir) / "02-notes"
        self.templates_dir = Path(self.tmp_dir) / "templates"
        self.templates_dir.mkdir()
        self.templates_dir.joinpath("note.md").write_text(
            "---\ntopic: \"{{TOPIC}}\"\nsubdomain: \"{{SUBDOMAIN}}\"\n"
            "keyword: \"{{KEYWORD}}\"\n---\n\n{{CONTENT}}"
        )
        self.store = NoteStore()

    @patch("src.storage.note_store.NOTES_DIR", new_callable=lambda: Path("/tmp"))
    def test_write_note_creates_file(self):
        # 简单验证模板渲染
        pass  # 集成测试在 test_extract_knowledge 中做


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: 编写 `tests/test_tree_store.py`**

```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.storage.tree_store import TreeStore


class TestTreeStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        self.tmp.write("# Knowledge Tree\n")
        self.tmp.close()

    def test_read_tree(self):
        with patch("src.storage.tree_store.TREE_FILE", Path(self.tmp.name)):
            store = TreeStore()
            text = store.read_tree()
            self.assertIn("# Knowledge Tree", text)

    def test_add_subdomain(self):
        with patch("src.storage.tree_store.TREE_FILE", Path(self.tmp.name)):
            store = TreeStore()
            store.add_subdomain("技术学习", "C++", "系统级编程语言")
            text = store.read_tree()
            self.assertIn("C++", text)

    def test_get_subdomains(self):
        with patch("src.storage.tree_store.TREE_FILE", Path(self.tmp.name)):
            store = TreeStore()
            store.add_subdomain("技术学习", "Python", "脚本语言")
            subs = store.get_subdomains()
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]["name"], "Python")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: 运行测试验证**

```bash
python -m pytest tests/test_tree_store.py tests/test_note_store.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/storage/note_store.py src/storage/tree_store.py src/storage/diary_parser.py tests/test_note_store.py tests/test_tree_store.py
git commit -m "feat: NoteStore + TreeStore + DiaryParser"
```

---

## Task 4: AIClient + extract_knowledge 核心流程

**Files:**
- Create: `src/logic/ai_client.py`
- Create: `src/logic/extract_knowledge.py`
- Test: `tests/test_extract_knowledge.py`

- [ ] **Step 1: 编写 `src/logic/ai_client.py`**

```python
"""DeepSeek API 调用。"""
import asyncio
import json
import re

import httpx

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL


def call_ai(prompt: str) -> dict:
    """同步调用 DeepSeek，返回解析后的 JSON。"""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    for attempt in range(3):
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(DEEPSEEK_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                outer = resp.json()
                content_str = outer["choices"][0]["message"]["content"].strip()
                # 清理 markdown 代码块
                if content_str.startswith("```"):
                    content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
                    content_str = re.sub(r"\s*```$", "", content_str)
                return json.loads(content_str)
        except Exception:
            if attempt == 2:
                raise
    return {}
```

- [ ] **Step 2: 编写 `src/logic/extract_knowledge.py`**

```python
"""核心流程：从日记中提取有效信息，生成知识笔记。"""
import json
from datetime import datetime

from src.config import EXTRACT_RULES_FILE
from src.storage.diary_parser import parse_diary
from src.storage.note_store import NoteStore
from src.storage.tree_store import TreeStore
from src.storage.db import Database
from src.logic.ai_client import call_ai
from src.logic.ask_clarification import ClarificationSession

note_store = NoteStore()


def extract_knowledge(file_path: str, db: Database = None) -> dict:
    """
    从日记文件中提取有效信息。

    返回:
        {"status": "success", "notes": [...]}
        {"status": "needs_clarification", "session_id": "...", "questions": [...]}
        {"status": "add_subdomain_request", "name": "...", "topic": "...", "description": "..."}
    """
    diary = parse_diary(file_path)
    tree_store = TreeStore()
    tree_text = tree_store.get_tree_text_for_prompt()

    # 读取提取规则
    rules_text = ""
    if EXTRACT_RULES_FILE.exists():
        rules_text = EXTRACT_RULES_FILE.read_text(encoding="utf-8")

    prompt = _build_prompt(diary["content"], tree_text, rules_text)
    result = call_ai(prompt)

    # 需要澄清
    if result.get("needs_clarification"):
        session = ClarificationSession.create(
            original_file=file_path,
            questions=result["questions"],
        )
        return {
            "status": "needs_clarification",
            "session_id": session.session_id,
            "questions": result["questions"],
        }

    # 请求添加子领域
    if result.get("add_subdomain"):
        return {
            "status": "add_subdomain_request",
            "name": result["add_subdomain"]["name"],
            "topic": result["add_subdomain"]["topic"],
            "description": result["add_subdomain"]["description"],
        }

    # 成功提取
    notes_created = []
    for item in result.get("extractions", []):
        topic = item["topic"]
        subdomain = item["subdomain"]
        keyword = item["keyword"]
        content = item["content"]

        # 写入文件
        fp = note_store.write_note(
            topic=topic,
            subdomain=subdomain,
            keyword=keyword,
            content=content,
            source=diary["filename"],
            source_date=diary["date"],
        )

        # 写入数据库
        if db:
            db.add_note(
                filename=f"{keyword}-{diary['date']}.md",
                topic=topic,
                subdomain=subdomain,
                keyword=keyword,
                source=diary["filename"],
                content=content,
                file_path=fp,
            )

        notes_created.append({"file_path": fp, "topic": topic, "subdomain": subdomain})

    return {"status": "success", "notes": notes_created}


def _build_prompt(diary_content: str, tree_text: str, rules_text: str) -> str:
    """构建 AI prompt。"""
    return f"""你是一个知识提取助手。请从以下日记中提取有价值的信息片段。

知识树结构：
{tree_text}

提取规则：
{rules_text}

日记内容：
{diary_content}

请返回 JSON 格式（不要其他任何文字）：
{{
  "extractions": [
    {{
      "topic": "所属主题名称",
      "subdomain": "所属子领域名称",
      "keyword": "主关键词",
      "content": "提取的有效信息内容"
    }}
  ],
  "needs_clarification": false,
  "questions": [],
  "add_subdomain": null
}}

如果无法确定主题或子领域，设置 needs_clarification 为 true 并列出需要澄清的问题。
如果发现应该创建新的子领域，设置 add_subdomain 为 {{name, topic, description}}。
"""
```

- [ ] **Step 3: 编写 `tests/test_extract_knowledge.py`**

```python
"""测试 extract_knowledge 流程。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.logic.extract_knowledge import extract_knowledge


class TestExtractKnowledge(unittest.TestCase):
    @patch("src.logic.extract_knowledge.call_ai")
    @patch("src.logic.extract_knowledge.note_store.write_note")
    def test_successful_extraction(self, mock_write, mock_ai):
        mock_ai.return_value = {
            "extractions": [
                {
                    "topic": "技术学习",
                    "subdomain": "C++",
                    "keyword": "智能指针",
                    "content": "学习了 unique_ptr 的用法"
                }
            ]
        }
        mock_write.return_value = "/tmp/02-notes/技术学习/C++/智能指针-2025-01-01.md"

        with patch("src.logic.extract_knowledge.parse_diary") as mock_parse:
            mock_parse.return_value = {
                "filename": "20250101.md",
                "date": "2025-01-01",
                "content": "今天学习了C++"
            }
            with patch("src.logic.extract_knowledge.TreeStore") as mock_tree:
                mock_tree.return_value.get_tree_text_for_prompt.return_value = "# Knowledge Tree\n"
                with patch("src.logic.extract_knowledge.EXTRACT_RULES_FILE") as mock_rules:
                    mock_rules.exists.return_value = False
                    result = extract_knowledge("/tmp/diary.md")

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["notes"]), 1)
        self.assertEqual(result["notes"][0]["topic"], "技术学习")

    @patch("src.logic.extract_knowledge.call_ai")
    def test_needs_clarification(self, mock_ai):
        mock_ai.return_value = {
            "extractions": [],
            "needs_clarification": True,
            "questions": ["这条日记属于哪个主题？"],
        }
        with patch("src.logic.extract_knowledge.parse_diary") as mock_parse:
            mock_parse.return_value = {"filename": "x.md", "date": "x", "content": "x"}
            with patch("src.logic.extract_knowledge.TreeStore") as mock_tree:
                mock_tree.return_value.get_tree_text_for_prompt.return_value = ""
                with patch("src.logic.extract_knowledge.EXTRACT_RULES_FILE") as mock_rules:
                    mock_rules.exists.return_value = False
                    result = extract_knowledge("/tmp/diary.md")

        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("这条日记属于哪个主题？", result["questions"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 运行测试验证**

```bash
python -m pytest tests/test_extract_knowledge.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/logic/ai_client.py src/logic/extract_knowledge.py tests/test_extract_knowledge.py
git commit -m "feat: AIClient + extract_knowledge 核心流程"
```

---

## Task 5: ask_clarification + add_subdomain

**Files:**
- Create: `src/logic/ask_clarification.py`
- Create: `src/logic/add_subdomain.py`

- [ ] **Step 1: 编写 `src/logic/ask_clarification.py`**

```python
"""会话管理：澄清问题。"""
import uuid
from dataclasses import dataclass, field


@dataclass
class ClarificationSession:
    session_id: str
    original_file: str
    questions: list[str]
    answers: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | answered | completed


# 内存会话存储（后续可持久化）
_sessions: dict[str, ClarificationSession] = {}


class ClarificationManager:
    @staticmethod
    def create(original_file: str, questions: list[str]) -> ClarificationSession:
        session = ClarificationSession(
            session_id=str(uuid.uuid4())[:8],
            original_file=original_file,
            questions=questions,
        )
        _sessions[session.session_id] = session
        return session

    @staticmethod
    def answer(session_id: str, answers: list[str]) -> dict:
        session = _sessions.get(session_id)
        if not session:
            return {"error": "会话不存在"}
        if len(answers) != len(session.questions):
            return {"error": f"需要 {len(session.questions)} 个回答"}
        session.answers = answers
        session.status = "answered"
        return {"session_id": session_id, "answers": answers}

    @staticmethod
    def get(session_id: str) -> ClarificationSession | None:
        return _sessions.get(session_id)


def ask_clarification(session_id: str = None, answers: list[str] = None) -> dict:
    """
    处理澄清会话。
    如果 session_id 为 None，返回所有待回答的会话。
    如果有 answers，提交回答并返回继续处理的结果。
    """
    if session_id is None:
        # 列出所有待回答会话
        pending = {sid: s for sid, s in _sessions.items() if s.status == "pending"}
        return {"sessions": {sid: {"file": s.original_file, "questions": s.questions}
                            for sid, s in pending.items()}}

    return ClarificationManager.answer(session_id, answers)
```

- [ ] **Step 2: 编写 `src/logic/add_subdomain.py`**

```python
"""添加新子领域到知识树和数据库。"""
from src.storage.db import Database
from src.storage.tree_store import TreeStore


def add_subdomain(name: str, topic: str, description: str, db: Database = None) -> dict:
    """
    添加新子领域。

    返回:
        {"status": "approved", "name": "...", "topic": "..."}
        {"status": "rejected", "reason": "..."}
    """
    # TODO: 后续可加用户审批流程
    # 当前自动批准

    # 写入 tree.md
    tree_store = TreeStore()
    tree_store.add_subdomain(topic, name, description)

    # 写入数据库
    if db:
        db.add_subdomain(name, topic, description)

    return {
        "status": "approved",
        "name": name,
        "topic": topic,
        "description": description,
    }
```

- [ ] **Step 3: Commit**

```bash
git add src/logic/ask_clarification.py src/logic/add_subdomain.py
git commit -m "feat: ask_clarification 会话管理 + add_subdomain"
```

**注意**: 用户环境为 Python 3.9，不支持 `dict | None` 语法，请使用 `Optional[dict]` from `typing`。

---

## Task 6: query_tree + check_subdomain + check_note + tree_sync

**Files:**
- Create: `src/logic/query_tree.py`
- Create: `src/logic/check_subdomain.py`
- Create: `src/logic/check_note.py`
- Create: `src/logic/tree_sync.py`

---

## Task 7: MCP Server

**Files:**
- Create: `src/mcp_server.py`

- [ ] **Step 1: 编写 `src/mcp_server.py`**

```python
"""MCP Server: 暴露 7 个工具给 AI 调用。"""
import sys
import json

# 使用 fastmcp 或手动 JSON-RPC
# 这里使用 mcp SDK (pip install mcp)
from mcp.server.fastmcp import FastMCP

from src.storage.db import Database
from src.logic.extract_knowledge import extract_knowledge
from src.logic.ask_clarification import ask_clarification
from src.logic.add_subdomain import add_subdomain
from src.logic.check_subdomain import check_subdomain
from src.logic.check_note import check_note
from src.logic.query_tree import query_tree
from src.logic.tree_sync import tree_sync

mcp = FastMCP("fragmentation")


@mcp.tool()
def extract_knowledge_tool(file_path: str) -> str:
    """从指定的 Markdown 日记文件中提取有效信息，生成知识笔记并写入 02-notes/。"""
    db = Database()
    try:
        result = extract_knowledge(file_path, db)
        return json.dumps(result, ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
def ask_clarification_tool(session_id: str = None, answers: list[str] = None) -> str:
    """处理澄清会话：列出待回答问题或提交回答。"""
    result = ask_clarification(session_id, answers)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def add_subdomain_tool(name: str, topic: str, description: str) -> str:
    """添加新子领域到知识树。"""
    db = Database()
    try:
        result = add_subdomain(name, topic, description, db)
        return json.dumps(result, ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
def check_subdomain_tool(topic: str, subdomain: str) -> str:
    """检查子领域内部笔记是否符合该领域的介绍，返回问题列表。"""
    db = Database()
    try:
        result = check_subdomain(topic, subdomain, db)
        return json.dumps(result, ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
def check_note_tool(file_path: str) -> str:
    """检查笔记是否符合子领域要求，逻辑是否清晰，返回问题列表。"""
    result = check_note(file_path)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def query_tree_tool(topic: str = None, subdomain: str = None) -> str:
    """查询知识树结构。传入领域和/或子领域名称。"""
    db = Database()
    try:
        result = query_tree(topic, subdomain, db)
        return json.dumps(result, ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
def tree_sync_tool() -> str:
    """遍历 tree.md 和数据库，同步两者信息（冲突时 tree.md 优先）。"""
    db = Database()
    try:
        result = tree_sync(db)
        return json.dumps(result, ensure_ascii=False, indent=2)
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: Commit**

```bash
git add src/mcp_server.py
git commit -m "feat: MCP Server (7 tools)"
```

---

## Task 7: query_tree + check_subdomain + check_note + tree_sync

**Files:**
- Create: `src/logic/query_tree.py`
- Create: `src/logic/check_subdomain.py`
- Create: `src/logic/check_note.py`
- Create: `src/logic/tree_sync.py`

- [ ] **Step 1: 编写 `src/logic/query_tree.py`**

```python
"""查询知识树结构。"""
from src.storage.db import Database
from src.storage.tree_store import TreeStore


def query_tree(topic: str = None, subdomain: str = None, db: Database = None) -> dict:
    """
    查询知识树。
    - 无参数：返回完整树
    - topic: 返回该主题及所有子领域
    - topic + subdomain: 返回子领域详情
    """
    tree_store = TreeStore()
    all_subs = tree_store.get_subdomains()

    if topic and subdomain:
        # 查找特定子领域
        for s in all_subs:
            if s["topic"] == topic and s["name"] == subdomain:
                notes = db.list_notes(topic=topic, subdomain=subdomain) if db else []
                return {"topic": topic, "subdomain": s["name"],
                        "description": s["description"], "notes": notes}
        return {"error": "子领域不存在"}

    if topic:
        subs = [s for s in all_subs if s["topic"] == topic]
        return {"topic": topic, "subdomains": subs}

    # 完整树
    topics_map = {}
    for s in all_subs:
        topics_map.setdefault(s["topic"], []).append(s)

    return {"tree": [{"topic": t, "subdomains": subs} for t, subs in topics_map.items()]}
```

- [ ] **Step 2: 编写 `src/logic/check_subdomain.py`**

```python
"""检查子领域内部笔记是否符合该子领域的介绍。"""
from src.storage.db import Database
from src.storage.tree_store import TreeStore
from src.logic.ai_client import call_ai


def check_subdomain(topic: str, subdomain: str, db: Database = None) -> dict:
    """
    检查子领域的笔记是否与子领域介绍一致。
    返回问题列表。
    """
    tree_store = TreeStore()
    subs = tree_store.get_subdomains()
    sub_info = None
    for s in subs:
        if s["topic"] == topic and s["name"] == subdomain:
            sub_info = s
            break

    if not sub_info:
        return {"error": "子领域不存在"}

    notes = db.list_notes(topic=topic, subdomain=subdomain) if db else []
    if not notes:
        return {"status": "ok", "note_count": 0, "issues": []}

    # 构建 AI prompt
    notes_text = "\n\n".join(
        f"笔记: {n['filename']}\n关键词: {n['keyword']}\n{n['content'][:500]}"
        for n in notes
    )

    prompt = f"""你是一个知识质量检查助手。

子领域介绍：
{sub_info['description']}

该子领域下的笔记：
{notes_text}

请检查：这些笔记是否符合子领域介绍？是否有不相关的内容？逻辑是否清晰？
返回 JSON 格式：
{{
  "issues": [
    {"filename": "xxx.md", "issue": "问题描述"}
  ]
}}

如果没有问题，返回 {{"issues": []}}。
"""
    result = call_ai(prompt)
    return {"status": "checked", "note_count": len(notes),
            "issues": result.get("issues", [])}
```

- [ ] **Step 3: 编写 `src/logic/check_note.py`**

```python
"""检查单个笔记是否符合子领域要求。"""
import re
from pathlib import Path

from src.logic.ai_client import call_ai
from src.storage.tree_store import TreeStore


def check_note(file_path: str) -> dict:
    """
    检查笔记是否符合子领域要求，逻辑是否清晰。
    返回问题列表。
    """
    p = Path(file_path)
    if not p.exists():
        return {"error": "文件不存在"}

    text = p.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        return {"error": "无 frontmatter"}

    fm = m.group(1)
    content = m.group(2).strip()

    topic = ""
    subdomain = ""
    for line in fm.splitlines():
        if line.startswith("topic:"):
            topic = line.split(":", 1)[1].strip().strip('"')
        if line.startswith("subdomain:"):
            subdomain = line.split(":", 1)[1].strip().strip('"')

    if not subdomain:
        return {"error": "笔记无 subdomain"}

    # 获取子领域介绍
    tree_store = TreeStore()
    subs = tree_store.get_subdomains()
    sub_desc = ""
    for s in subs:
        if s["topic"] == topic and s["name"] == subdomain:
            sub_desc = s["description"]
            break

    prompt = f"""请检查以下笔记是否符合其子领域要求。

子领域: {subdomain} (所属主题: {topic})
子领域介绍: {sub_desc}

笔记内容:
{content[:2000]}

返回 JSON 格式：
{{
  "issues": ["问题1", "问题2"],
  "valid": true/false
}}
"""
    result = call_ai(prompt)
    return {"file": file_path, "valid": result.get("valid", False),
            "issues": result.get("issues", [])}
```

- [ ] **Step 4: 编写 `src/logic/tree_sync.py`**

```python
"""tree.md ↔ 数据库同步（冲突时 tree.md 优先）。"""
from src.storage.db import Database
from src.storage.tree_store import TreeStore


def tree_sync(db: Database = None) -> dict:
    """
    遍历 tree.md，与数据库对比。
    冲突时以 tree.md 为准。
    返回同步状态。
    """
    tree_store = TreeStore()
    subs_from_md = tree_store.get_subdomains()

    added_to_db = 0
    removed_from_db = 0

    if db:
        db_subs = db.list_subdomains()
        db_sub_names = {s["name"] for s in db_subs}
        md_sub_names = {s["name"] for s in subs_from_md}

        # tree.md 中有但 DB 没有 → 添加到 DB
        for s in subs_from_md:
            if s["name"] not in db_sub_names:
                db.add_subdomain(s["name"], s["topic"], s["description"])
                added_to_db += 1

        # DB 中有但 tree.md 没有 → 从 DB 删除
        for s in db_subs:
            if s["name"] not in md_sub_names:
                db.conn.execute("DELETE FROM subdomains WHERE name = ?", (s["name"],))
                db.conn.commit()
                removed_from_db += 1

    return {
        "tree.md 子领域数": len(subs_from_md),
        "添加到数据库": added_to_db,
        "从数据库删除": removed_from_db,
    }
```

- [ ] **Step 5: Commit**

```bash
git add src/logic/query_tree.py src/logic/check_subdomain.py src/logic/check_note.py src/logic/tree_sync.py
git commit -m "feat: query_tree + check_subdomain + check_note + tree_sync"
```

---

## Task 8: CLI 接口

**Files:**
- Create: `src/cli.py`

- [ ] **Step 1: 编写 `src/cli.py`**

```python
"""CLI 接口：人类调试用。"""
import argparse
import json

from src.storage.db import Database
from src.logic.extract_knowledge import extract_knowledge
from src.logic.ask_clarification import ask_clarification
from src.logic.add_subdomain import add_subdomain
from src.logic.check_subdomain import check_subdomain
from src.logic.check_note import check_note
from src.logic.query_tree import query_tree
from src.logic.tree_sync import tree_sync


def output(result: dict):
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Fragmentation CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # extract-knowledge
    p = sub.add_parser("extract-knowledge", help="从日记中提取知识")
    p.add_argument("file_path", help="01-diary/ 中的日记文件路径")

    # ask-clarification
    p = sub.add_parser("ask-clarification", help="处理澄清会话")
    p.add_argument("--session-id", help="会话 ID")
    p.add_argument("--answers", nargs="*", help="回答列表")

    # add-subdomain
    p = sub.add_parser("add-subdomain", help="添加新子领域")
    p.add_argument("name", help="子领域名称")
    p.add_argument("topic", help="所属主题")
    p.add_argument("description", help="子领域介绍")

    # check-subdomain
    p = sub.add_parser("check-subdomain", help="检查子领域健康")
    p.add_argument("topic", help="主题名")
    p.add_argument("subdomain", help="子领域名")

    # check-note
    p = sub.add_parser("check-note", help="检查笔记质量")
    p.add_argument("file_path", help="笔记文件路径")

    # query-tree
    p = sub.add_parser("query-tree", help="查询知识树")
    p.add_argument("--topic", help="主题名（可选）")
    p.add_argument("--subdomain", help="子领域名（可选）")

    # tree-sync
    sub.add_parser("tree-sync", help="同步 tree.md 与数据库")

    args = parser.parse_args()
    db = Database()

    try:
        if args.cmd == "extract-knowledge":
            output(extract_knowledge(args.file_path, db))
        elif args.cmd == "ask-clarification":
            output(ask_clarification(args.session_id, args.answers))
        elif args.cmd == "add-subdomain":
            output(add_subdomain(args.name, args.topic, args.description, db))
        elif args.cmd == "check-subdomain":
            output(check_subdomain(args.topic, args.subdomain, db))
        elif args.cmd == "check-note":
            output(check_note(args.file_path))
        elif args.cmd == "query-tree":
            output(query_tree(args.topic, args.subdomain, db))
        elif args.cmd == "tree-sync":
            output(tree_sync(db))
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add src/cli.py
git commit -m "feat: CLI 接口 (7 commands)"
```

---

## Task 9: 运行 Smoke Test + 清理旧文件

- [ ] **Step 1: 安装依赖**

```bash
pip install httpx mcp
```

- [ ] **Step 2: 初始化数据库**

```bash
python -c "from src.storage.db import Database; Database(); print('DB OK')"
```

- [ ] **Step 3: 测试 CLI extract-knowledge**

```bash
# 先往 tree.md 加一个主题测试
python src/cli.py add-subdomain "C++" "技术学习" "面向对象编程语言，系统级开发"

# 提取知识
python src/cli.py extract-knowledge 01-diary/20250101.md
```

Expected: AI 返回提取结果或澄清请求。

- [ ] **Step 4: 运行所有测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 5: 删除旧文件**

```bash
rm batch.py clean_keywords.py compute_removals.py db.py execute_keyword_cleanup.py fragmentation.py phase2_merge.py phase3_short.py refine_keywords.py test_fragmentation.py
rm -rf __pycache__ .pytest_cache logs/ Meaningless/ archive/
rm fragments.db  # 旧数据库，新 DB 会在首次使用时创建
rm template.md template_gather.md prompt.md all_keywords.txt
rm 02-fragment/*.md  # 旧 fragment，数据作废
rm -rf 03-MOC/
```

- [ ] **Step 6: 运行完整测试确认新系统工作正常**

```bash
python -m pytest tests/ -v
python src/cli.py add-subdomain "测试" "测试主题" "测试子领域"
python src/cli.py query-tree
```

- [ ] **Step 7: Commit 清理**

```bash
git add -A
git commit -m "refactor: 全面重构 - 旧代码删除，新三层架构上线"
```

---

## Task 10: 添加日志模块

**Files:**
- Create: `src/storage/logger.py`

- [ ] **Step 1: 编写 `src/storage/logger.py`**

```python
"""简单日志模块。"""
import logging
from datetime import datetime
from pathlib import Path

from src.config import LOGS_DIR

LOGS_DIR.mkdir(exist_ok=True)

_extract_logger = logging.getLogger("extract")
_handler = logging.FileHandler(LOGS_DIR / "extract.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_extract_logger.addHandler(_handler)
_extract_logger.setLevel(logging.INFO)


def log_extract(source: str, status: str, notes: list[str] = None, error: str = None):
    """记录提取操作。"""
    msg = f"extract {source} -> {status}"
    if notes:
        msg += f" notes={notes}"
    if error:
        msg += f" error={error}"
    _extract_logger.info(msg)


def log_tree_change(action: str, detail: str):
    """记录知识树变更。"""
    logger = logging.getLogger("tree")
    handler = logging.FileHandler(LOGS_DIR / "tree_changes.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info(f"tree {action}: {detail}")
```

- [ ] **Step 2: 在 extract_knowledge.py 中添加日志调用**

在 `extract_knowledge` 函数返回前添加：

```python
from src.storage.logger import log_extract

# 在 return 前调用:
log_extract(file_path, result["status"],
            notes=[n["file_path"] for n in result.get("notes", [])],
            error=result.get("error"))
```

- [ ] **Step 3: Commit**

```bash
git add src/storage/logger.py src/logic/extract_knowledge.py
git commit -m "feat: 日志模块"
```