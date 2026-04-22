"""MCP Server: 暴露 7 个工具给 AI 调用。"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from src.storage.db import Database
from src.logic.extract_knowledge import extract_knowledge, extract_knowledge_async
from src.logic.ask_clarification import ask_clarification
from src.logic.add_subdomain import add_subdomain
from src.logic.check_subdomain import check_subdomain
from src.logic.check_note import check_note
from src.logic.query_tree import query_tree
from src.logic.tree_sync import tree_sync

mcp = FastMCP("fragmentation")


@mcp.tool()
async def extract_knowledge_tool(file_path: str) -> str:
    """从指定的 Markdown 日记文件中提取有效信息，生成知识笔记并写入 02-notes/。"""
    db = Database()
    try:
        result = await extract_knowledge_async(file_path, db)
        return json.dumps(result, ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
def ask_clarification_tool(
    session_id: Optional[str] = None,
    answers: Optional[list] = None,
) -> str:
    """处理澄清会话：列出待回答问题或提交回答。不传参数时列出所有待处理会话。"""
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
def check_subdomain_tool(
    topic: Optional[str] = None,
    subdomain: Optional[str] = None,
) -> str:
    """检查子领域内部笔记是否符合该领域的介绍，返回问题列表。不传参数时检查全部。"""
    db = Database()
    try:
        result = check_subdomain(topic or "", subdomain or "", db)
        return json.dumps(result, ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
def check_note_tool(file_path: str) -> str:
    """检查笔记是否符合子领域要求，逻辑是否清晰，返回问题列表。"""
    result = check_note(file_path)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def query_tree_tool(
    topic: Optional[str] = None,
    subdomain: Optional[str] = None,
) -> str:
    """查询知识树结构。不传参数时返回全部。"""
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
