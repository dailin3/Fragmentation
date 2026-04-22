"""查询知识树结构。"""
from src.storage.db import Database
from src.storage.tree_store import TreeStore


def query_tree(topic: str = None, subdomain: str = None, db: Database = None) -> dict:
    """查询知识树结构。

    Args:
        topic: 可选，指定主题。
        subdomain: 可选，指定子领域（需与 topic 配合）。
        db: 可选，数据库实例，用于获取 notes。

    Returns:
        dict: 树结构查询结果。
    """
    tree_store = TreeStore()
    all_subs = tree_store.get_subdomains()

    if topic and subdomain:
        for s in all_subs:
            if s["topic"] == topic and s["name"] == subdomain:
                notes = db.list_notes(topic=topic, subdomain=subdomain) if db else []
                return {"topic": topic, "subdomain": s["name"],
                        "description": s["description"], "notes": notes}
        return {"error": "子领域不存在"}

    if topic:
        subs = [s for s in all_subs if s["topic"] == topic]
        return {"topic": topic, "subdomains": subs}

    topics_map = {}
    for s in all_subs:
        topics_map.setdefault(s["topic"], []).append(s)

    return {"tree": [{"topic": t, "subdomains": subs} for t, subs in topics_map.items()]}
