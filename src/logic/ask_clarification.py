"""会话管理：澄清问题（数据库持久化）。"""
from dataclasses import dataclass, field
from typing import Optional

from src.storage.db import Database


@dataclass
class ClarificationSession:
    session_id: str
    original_file: str
    questions: list
    answers: list = field(default_factory=list)
    status: str = "pending"  # pending | answered | completed


class ClarificationManager:
    @staticmethod
    def create(original_file: str, questions: list) -> ClarificationSession:
        db = Database()
        session_id = __import__("uuid").uuid4().hex[:8]
        db.save_session(session_id, original_file, questions)
        db.close()
        return ClarificationSession(
            session_id=session_id,
            original_file=original_file,
            questions=questions,
        )

    @staticmethod
    def answer(session_id: str, answers: list) -> dict:
        db = Database()
        session = db.get_session(session_id)
        if not session:
            db.close()
            return {"error": "会话不存在"}
        if len(answers) != len(session["questions"]):
            db.close()
            return {"error": f"需要 {len(session['questions'])} 个回答"}
        db.update_session_answers(session_id, answers)
        db.close()
        return {"session_id": session_id, "answers": answers, "file": session["original_file"]}

    @staticmethod
    def get(session_id: str) -> Optional[ClarificationSession]:
        db = Database()
        row = db.get_session(session_id)
        db.close()
        if not row:
            return None
        return ClarificationSession(
            session_id=row["session_id"],
            original_file=row["original_file"],
            questions=row["questions"],
            answers=row["answers"],
            status=row["status"],
        )

    @staticmethod
    def get_clarified_content(session_id: str) -> Optional[str]:
        """返回追加了回答的日记内容，如果会话不存在或未回答则返回 None。"""
        db = Database()
        row = db.get_session(session_id)
        db.close()
        if not row or row["status"] != "answered":
            return None
        # 从原始文件读取日记内容
        from src.storage.diary_parser import parse_diary
        diary = parse_diary(row["original_file"])
        # 构建补充上下文
        qa = "\n".join(
            f"- Q: {q}\n- A: {a}"
            for q, a in zip(row["questions"], row["answers"])
        )
        return f"{diary['content']}\n\n## 补充上下文\n{qa}"


def ask_clarification(session_id: str = None, answers: list = None) -> dict:
    if session_id is None:
        db = Database()
        pending = db.list_pending_sessions()
        db.close()
        return {"sessions": {s["session_id"]: {"file": s["original_file"], "questions": s["questions"]}
                            for s in pending}}
    return ClarificationManager.answer(session_id, answers)
