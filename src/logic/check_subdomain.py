"""检查子领域内部笔记是否符合该子领域的介绍。"""
from src.storage.db import Database
from src.storage.tree_store import TreeStore
from src.logic.ai_client import call_ai


def check_subdomain(topic: str, subdomain: str, db: Database = None) -> dict:
    """检查子领域内部笔记是否符合该子领域的介绍。

    Args:
        topic: 主题名称。
        subdomain: 子领域名称。
        db: 可选，数据库实例。

    Returns:
        dict: 检查结果，包含 issues 列表。
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
    {{"filename": "xxx.md", "issue": "问题描述"}}
  ]
}}

如果没有问题，返回 {{"issues": []}}。
"""
    result = call_ai(prompt)
    return {"status": "checked", "note_count": len(notes),
            "issues": result.get("issues", [])}
