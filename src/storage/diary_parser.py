"""解析 01-diary/ 原始日记文件。"""
import re
from pathlib import Path


def parse_diary(file_path: str) -> dict:
    """解析日记文件，返回 {filename, date, content}。"""
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")

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
