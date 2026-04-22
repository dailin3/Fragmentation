"""检查单个笔记是否符合子领域要求。"""
import re
from pathlib import Path

from src.logic.ai_client import call_ai
from src.storage.tree_store import TreeStore


def check_note(file_path: str) -> dict:
    """检查单个笔记是否符合子领域要求。

    Args:
        file_path: 笔记文件路径。

    Returns:
        dict: 检查结果，包含 valid 和 issues。
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
