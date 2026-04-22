"""添加新子领域到知识树和数据库。"""
from src.storage.db import Database
from src.storage.tree_store import TreeStore


def add_subdomain(name: str, topic: str, description: str, db: Database = None) -> dict:
    """添加新子领域。当前自动批准。"""
    tree_store = TreeStore()
    tree_store.add_subdomain(topic, name, description)

    if db:
        db.add_subdomain(name, topic, description)
    else:
        db = Database()
        db.add_subdomain(name, topic, description)
        db.close()

    return {
        "status": "approved",
        "name": name,
        "topic": topic,
        "description": description,
    }
