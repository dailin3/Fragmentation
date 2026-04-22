"""CLI 接口：人类调试用。"""
import argparse
import asyncio
import glob
import json

from src.storage.db import Database
from src.logic.extract_knowledge import extract_knowledge, extract_knowledge_async
from src.logic.ask_clarification import ask_clarification, ClarificationManager
from src.logic.add_subdomain import add_subdomain
from src.logic.check_subdomain import check_subdomain
from src.logic.check_note import check_note
from src.logic.query_tree import query_tree
from src.logic.tree_sync import tree_sync


def output(result: dict):
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _batch_extract(db: Database, clarify: bool = False, skip_errors: bool = False):
    """批量提取所有未处理的日记（并发版本）。"""
    all_diaries = glob.glob("01-diary/*.md")
    processed_names = {r["filename"] for r in db.conn.execute(
        "SELECT filename FROM diary_processed").fetchall()}
    unprocessed = sorted(d for d in all_diaries if d.split("/")[-1] not in processed_names)

    total = len(unprocessed)
    if total == 0:
        print("没有待处理的日记。")
        return

    print(f"待处理日记: {total} 篇（并发度 15）")
    results = asyncio.run(_batch_extract_async(unprocessed, clarify, skip_errors))
    _print_batch_summary(results)


def _print_batch_summary(results: dict):
    """打印详细的批量处理结果摘要。"""
    print(f"\n=== 批量处理完成 ===")
    print(f"总计: {results['total']} 篇")
    print(f"成功: {results['success']} 篇, 跳过: {results['skipped']} 篇, "
          f"待澄清: {results['needs_clarification']} 篇, 错误: {results['errors']} 篇")

    if results["skipped_list"]:
        print(f"\n--- 跳过的日记 ({len(results['skipped_list'])} 篇) ---")
        for item in results["skipped_list"]:
            detail = ""
            if item.get("name"):
                detail = f" (请求创建子领域: {item['name']})"
            print(f"  {item['file']}{detail}")

    if results["needs_clarification_list"]:
        print(f"\n--- 待澄清的日记 ({len(results['needs_clarification_list'])} 篇) ---")
        for item in results["needs_clarification_list"]:
            print(f"  {item['file']} (session: {item['session_id'][:8]}...)")

    if results["error_list"]:
        print(f"\n--- 错误的日记 ({len(results['error_list'])} 篇) ---")
        for item in results["error_list"]:
            err = item["error"][:80] if len(item["error"]) > 80 else item["error"]
            print(f"  {item['file']}: {err}")


async def _batch_extract_async(diary_files: list, clarify: bool, skip_errors: bool) -> dict:
    """异步批量提取，限制并发度保护数据库。"""
    semaphore = asyncio.Semaphore(15)
    success = 0
    skipped_list = []
    error_list = []
    needs_clarify_list = []

    async def process_one(fp: str):
        nonlocal success
        async with semaphore:
            try:
                result = await extract_knowledge_async(fp, enable_clarification=clarify)
                status = result.get("status", "unknown")
                if status == "success":
                    success += 1
                elif status == "needs_clarification":
                    needs_clarify_list.append({
                        "file": fp, "session_id": result["session_id"],
                    })
                elif status == "add_subdomain_request":
                    skipped_list.append({
                        "file": fp, "name": result.get("name", ""),
                        "topic": result.get("topic", ""),
                    })
                elif status == "skipped":
                    skipped_list.append({"file": fp})
            except Exception as e:
                error_list.append({"file": fp, "error": str(e)})
                if not skip_errors:
                    raise

    tasks = [process_one(fp) for fp in diary_files]

    completed = 0
    for coro in asyncio.as_completed(tasks):
        try:
            await coro
        except Exception:
            pass
        completed += 1
        if completed % 20 == 0 or completed == len(diary_files):
            print(f"[{completed}/{len(diary_files)}] 成功: {success}, 跳过: {len(skipped_list)}, "
                  f"待澄清: {len(needs_clarify_list)}, 错误: {len(error_list)}")

    return {
        "total": len(diary_files), "success": success,
        "skipped": len(skipped_list), "skipped_list": skipped_list,
        "needs_clarification": len(needs_clarify_list), "needs_clarification_list": needs_clarify_list,
        "errors": len(error_list), "error_list": error_list,
    }


def main():
    parser = argparse.ArgumentParser(description="Fragmentation CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract-knowledge", help="从日记中提取知识")
    p.add_argument("file_path", help="01-diary/ 中的日记文件路径")
    p.add_argument("--clarify", action="store_true", help="允许 AI 提问获取上下文")

    p = sub.add_parser("ask-clarification", help="处理澄清会话")
    p.add_argument("--session-id", help="会话 ID")
    p.add_argument("--answers", nargs="*", help="回答列表")

    p = sub.add_parser("add-subdomain", help="添加新子领域")
    p.add_argument("name", help="子领域名称")
    p.add_argument("topic", help="所属主题")
    p.add_argument("description", help="子领域介绍")

    p = sub.add_parser("check-subdomain", help="检查子领域健康")
    p.add_argument("topic", help="主题名")
    p.add_argument("subdomain", help="子领域名")

    p = sub.add_parser("check-note", help="检查笔记质量")
    p.add_argument("file_path", help="笔记文件路径")

    p = sub.add_parser("query-tree", help="查询知识树")
    p.add_argument("--topic", help="主题名（可选）")
    p.add_argument("--subdomain", help="子领域名（可选）")

    sub.add_parser("tree-sync", help="同步 tree.md 与数据库")

    p = sub.add_parser("batch-extract", help="批量提取所有未处理的日记")
    p.add_argument("--clarify", action="store_true", help="允许 AI 提问获取上下文")
    p.add_argument("--skip-errors", action="store_true", help="遇到错误继续处理")

    args = parser.parse_args()
    db = Database()

    try:
        if args.cmd == "extract-knowledge":
            if db.is_diary_processed(args.file_path):
                stats = db.get_processing_stats()
                print(f"[warn] 该日记已处理过，跳过提取。当前处理统计: {stats}")
                return
            output(extract_knowledge(args.file_path, db, enable_clarification=args.clarify))
        elif args.cmd == "ask-clarification":
            result = ask_clarification(args.session_id, args.answers)
            # 如果回答成功，自动继续提取
            if "error" not in result:
                clarified = ClarificationManager.get_clarified_content(result["session_id"])
                if clarified:
                    extract_result = extract_knowledge(
                        result["file"], db,
                        enable_clarification=False,
                        clarification_content=clarified,
                    )
                    result["extraction"] = extract_result
            output(result)
        elif args.cmd == "add-subdomain":
            output(add_subdomain(args.name, args.topic, args.description, db))
        elif args.cmd == "check-subdomain":
            output(check_subdomain(args.topic, args.subdomain, db))
        elif args.cmd == "check-note":
            output(check_note(args.file_path))
        elif args.cmd == "query-tree":
            output(query_tree(args.topic, args.subdomain, db))
        elif args.cmd == "tree-sync":
            output(tree_sync(db))
        elif args.cmd == "batch-extract":
            _batch_extract(db, clarify=getattr(args, "clarify", False),
                           skip_errors=getattr(args, "skip_errors", False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
