"""知识树索引文件管理（tree/ 目录）。"""
import re
from pathlib import Path
from typing import Optional, List

from src.config import TREE_DIR


class TreeStore:
    def __init__(self, db=None):
        self.db = db

    def read_tree(self) -> str:
        """读取 tree/ 目录下所有文件，拼成 prompt 用的树结构文本。"""
        if not TREE_DIR.exists():
            return ""

        lines = ["# Knowledge Tree\n"]
        # Only read topic files (type: topic in frontmatter)
        for topic_file in sorted(TREE_DIR.glob("*.md")):
            text = topic_file.read_text(encoding="utf-8")
            if "type: topic" not in text:
                continue  # Skip subdomain files
            topic_name = self._extract_topic_name(topic_file)
            lines.append(f"\n## {topic_name}\n")

            # Read subdomain links from topic file
            for line in text.splitlines():
                # Match:   - [[子领域名]] — 描述
                m = re.match(r"\s*-\s*\[\[(.+?)\]\]\s*[—-]\s*(.*)", line)
                if m:
                    sd_name, sd_desc = m.group(1), m.group(2).strip()
                    lines.append(f"- 子领域: {sd_name} — {sd_desc}\n")

        return "\n".join(lines)

    def get_tree_text_for_prompt(self) -> str:
        """返回用于 AI prompt 的树结构文本。"""
        return self.read_tree()

    def add_topic(self, name: str, description: str):
        """在 tree/ 目录下创建 topic 文件，同时写入 DB。"""
        TREE_DIR.mkdir(parents=True, exist_ok=True)
        topic_file = TREE_DIR / f"{name}.md"
        if topic_file.exists():
            return
        content = f"""---
type: topic
created: 2026-04-22
---

# {name}

{description}

## 子领域

"""
        topic_file.write_text(content, encoding="utf-8")
        if self.db:
            self.db.add_topic(name, description)

    def add_subdomain(self, topic: str, name: str, description: str):
        """在指定 topic 文件下添加子领域，并创建子领域文件，同时写入 DB。"""
        topic_file = TREE_DIR / f"{topic}.md"
        if not topic_file.exists():
            self.add_topic(topic, "")
            topic_file = TREE_DIR / f"{topic}.md"

        # Append subdomain link to topic file
        text = topic_file.read_text(encoding="utf-8")
        text = text.rstrip() + f"\n  - [[{name}]] — {description}\n"
        topic_file.write_text(text, encoding="utf-8")

        # Create subdomain file
        sd_file = TREE_DIR / f"{name}.md"
        if not sd_file.exists():
            sd_content = f"""---
type: subdomain
topic: [[{topic}]]
created: 2026-04-22
---

# {name}

{description}
"""
            sd_file.write_text(sd_content, encoding="utf-8")

        if self.db:
            self.db.add_subdomain(name, topic, description)

    def get_subdomains(self) -> list:
        """读取 tree/ 目录，返回 [{topic, name, description}, ...]。"""
        result = []
        if not TREE_DIR.exists():
            return result

        for topic_file in sorted(TREE_DIR.glob("*.md")):
            text = topic_file.read_text(encoding="utf-8")
            if "type: topic" not in text:
                continue
            topic_name = self._extract_topic_name(topic_file)
            for line in text.splitlines():
                m = re.match(r"\s*-\s*\[\[(.+?)\]\]\s*[—-]\s*(.*)", line)
                if m:
                    result.append({
                        "topic": topic_name,
                        "name": m.group(1),
                        "description": m.group(2).strip(),
                    })
        return result

    def _extract_topic_name(self, file_path: Path) -> str:
        """从文件内容或文件名提取 topic 名称。"""
        text = file_path.read_text(encoding="utf-8")
        # Try to get name from markdown header
        m = re.search(r"^# (.+)$", text, re.MULTILINE)
        if m:
            return m.group(1)
        # Fallback to filename without extension
        return file_path.stem
