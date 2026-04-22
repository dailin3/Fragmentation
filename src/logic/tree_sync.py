"""tree.md 与数据库同步（冲突时 tree.md 优先）。"""
from src.storage.db import Database
from src.storage.tree_store import TreeStore


def tree_sync(db: Database = None) -> dict:
    """tree.md 与数据库同步，冲突时 tree.md 优先。

    Args:
        db: 可选，数据库实例。不提供则仅返回 tree.md 统计信息。

    Returns:
        dict: 同步结果，包含 tree.md 子领域数、添加和删除数量。
    """
    tree_store = TreeStore()
    subs_from_md = tree_store.get_subdomains()

    if db is None:
        return {
            "tree.md 子领域数": len(subs_from_md),
            "添加到数据库": 0,
            "从数据库删除": 0,
        }

    md_names = {s["name"] for s in subs_from_md}
    db_names = {s["name"] for s in db.list_subdomains()}

    added = len(md_names - db_names)
    removed = len(db_names - md_names)

    db.sync_subdomains_from_tree(subs_from_md)

    return {
        "tree.md 子领域数": len(subs_from_md),
        "添加到数据库": added,
        "从数据库删除": removed,
    }
