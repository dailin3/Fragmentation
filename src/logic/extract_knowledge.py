"""核心流程：从日记中提取有效信息，生成知识笔记。"""
from src.config import EXTRACT_RULES_FILE
from src.storage.diary_parser import parse_diary
from src.storage.note_store import NoteStore
from src.storage.tree_store import TreeStore
from src.storage.db import Database
from src.storage.logger import log_extract
from src.logic.ai_client import call_ai
from src.logic.ask_clarification import ClarificationManager
from src.logic.add_subdomain import add_subdomain


def extract_knowledge(file_path: str, db: Database = None, enable_clarification: bool = False,
                      clarification_content: str = None) -> dict:
    should_close_db = db is None
    if should_close_db:
        db = Database()
    try:
        diary = parse_diary(file_path)
        note_store = NoteStore()
        tree_store = TreeStore()
        tree_text = tree_store.get_tree_text_for_prompt()

        rules_text = ""
        if EXTRACT_RULES_FILE.exists():
            rules_text = EXTRACT_RULES_FILE.read_text(encoding="utf-8")

        content = clarification_content or diary["content"]
        prompt = _build_prompt(content, tree_text, rules_text, enable_clarification)
        result = call_ai(prompt)

        if result.get("needs_clarification"):
            session = ClarificationManager.create(
                original_file=file_path,
                questions=result["questions"],
            )
            db.mark_diary_processed(
                file_path=file_path,
                filename=diary["filename"],
                status="needs_clarification",
                session_id=session.session_id,
            )
            log_extract(file_path, "needs_clarification")
            if should_close_db:
                db.close()
            return {
                "status": "needs_clarification",
                "session_id": session.session_id,
                "questions": result["questions"],
            }

        if result.get("add_subdomain"):
            sd = result["add_subdomain"]
            log_extract(file_path, "add_subdomain_request", error=f"创建新子领域: {sd['name']}")
            add_subdomain(sd["name"], sd["topic"], sd["description"], db=db)
            # 创建后重新提取该日记（新 subdomain 已写入 DB）
            return extract_knowledge(file_path, db, enable_clarification, clarification_content)

        notes_created = []
        existing_subdomains = {r["name"] for r in db.conn.execute("SELECT name FROM subdomains").fetchall()}
        for item in result.get("extractions", []):
            required = ["topic", "subdomain", "keyword", "content"]
            missing = [k for k in required if k not in item]
            if missing:
                log_extract(file_path, "warning", error=f"AI返回的extraction缺少字段: {missing}")
                continue
            topic = item["topic"]
            subdomain = item["subdomain"]
            if subdomain not in existing_subdomains:
                log_extract(file_path, "warning", error=f"subdomain '{subdomain}' 不存在于知识树中，跳过")
                continue
            keyword = item["keyword"]
            content = item["content"]

            fp = note_store.write_note(
                topic=topic,
                subdomain=subdomain,
                keyword=keyword,
                content=content,
                source=diary["filename"],
                source_date=diary["date"],
            )

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

        db.mark_diary_processed(
            file_path=file_path,
            filename=diary["filename"],
            status="success",
            notes_count=len(notes_created),
        )
        log_extract(
            file_path,
            "success",
            notes=[n["file_path"] for n in notes_created],
        )
        if should_close_db:
            db.close()
        return {"status": "success", "notes": notes_created}
    except Exception as e:
        db.mark_diary_processed(
            file_path=file_path,
            filename=diary.get("filename", "unknown"),
            status="error",
            error_message=str(e),
        )
        log_extract(file_path, "error", error=str(e))
        if should_close_db:
            db.close()
        raise


def _extract_one(file_path: str, enable_clarification: bool = False,
                 clarification_content: str = None) -> dict:
    """单篇提取（线程安全包装）。创建独立 DB 连接，保证线程局部性。"""
    db = Database()
    try:
        return extract_knowledge(file_path, db, enable_clarification, clarification_content)
    finally:
        db.close()


async def extract_knowledge_async(file_path: str, db: Database = None,
                                   enable_clarification: bool = False,
                                   clarification_content: str = None) -> dict:
    """异步版本，用于批量并发处理。

    核心思路：整篇提取是单个 I/O 密集型任务，用 asyncio.to_thread()
    包装整个 extract_knowledge()，让事件循环在等待 AI 响应时继续调度其他任务。
    """
    import asyncio

    def _run():
        return extract_knowledge(file_path, db, enable_clarification, clarification_content)

    return await asyncio.to_thread(_run)


def _build_prompt(diary_content: str, tree_text: str, rules_text: str, enable_clarification: bool = False) -> str:
    if enable_clarification:
        clarify_rule = "如果无法确定主题或子领域，设置 needs_clarification 为 true 并列出需要澄清的问题。"
    else:
        clarify_rule = "不要提问或请求澄清。如果信息不足，直接跳过不提取。"

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

{clarify_rule}
如果发现应该创建新的子领域，设置 add_subdomain 为 {{name, topic, description}}。
"""
