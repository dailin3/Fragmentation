"""笔记文件读写（02-notes/）。"""
import re
from pathlib import Path
from datetime import datetime

from src.config import NOTES_DIR, TEMPLATES_DIR


class NoteStore:
    def write_note(self, topic: str, subdomain: str, keyword: str,
                   content: str, source: str, source_date: str) -> str:
        """写入笔记到 02-notes/ 根目录，返回文件路径。
        笔记通过 frontmatter 中的 topic/subdomain 归属，文件本身扁平。"""
        safe_kw = keyword.replace("/", "-").replace("\\", "-")
        date_part = source_date or datetime.now().strftime("%Y-%m-%d")
        filename = f"{safe_kw}-{date_part}.md"

        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        file_path = NOTES_DIR / filename

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
