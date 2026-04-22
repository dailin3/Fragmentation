"""SQLite 数据库：topics, subdomains, notes, diary_processed, clarification_sessions 五表。"""
import json
import sqlite3
from datetime import datetime
from typing import Optional

from src.config import DB_PATH


class Database:
    def __init__(self, db_path=None):
        self.conn = sqlite3.connect(str(db_path or DB_PATH), timeout=30)
        self.conn.row_factory = sqlite3.Row
        # Enable WAL mode for concurrent writers
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS topics (
                name TEXT PRIMARY KEY,
                description TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS subdomains (
                name TEXT PRIMARY KEY,
                topic TEXT,
                description TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS notes (
                filename TEXT PRIMARY KEY,
                topic TEXT,
                subdomain TEXT,
                keyword TEXT,
                source TEXT,
                content TEXT,
                file_path TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS diary_processed (
                file_path TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                notes_count INTEGER DEFAULT 0,
                session_id TEXT,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS clarification_sessions (
                session_id TEXT PRIMARY KEY,
                original_file TEXT NOT NULL,
                questions TEXT NOT NULL,
                answers TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                answered_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notes_topic ON notes(topic);
            CREATE INDEX IF NOT EXISTS idx_notes_subdomain ON notes(subdomain);
            CREATE INDEX IF NOT EXISTS idx_subdomains_topic ON subdomains(topic);
            CREATE INDEX IF NOT EXISTS idx_diary_processed_status ON diary_processed(status);
        """)
        self.conn.commit()

    # ── Topics ──

    def add_topic(self, name: str, description: str = ""):
        self.conn.execute(
            "INSERT OR REPLACE INTO topics (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_topic(self, name: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM topics WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def list_topics(self) -> list:
        rows = self.conn.execute("SELECT * FROM topics ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    # ── Subdomains ──

    def add_subdomain(self, name: str, topic: str, description: str = ""):
        self.conn.execute(
            "INSERT OR REPLACE INTO subdomains (name, topic, description, created_at) VALUES (?, ?, ?, ?)",
            (name, topic, description, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_subdomain(self, name: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM subdomains WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def list_subdomains(self, topic: str = None) -> list:
        if topic:
            rows = self.conn.execute(
                "SELECT * FROM subdomains WHERE topic = ? ORDER BY name", (topic,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM subdomains ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def subdomain_exists(self, name: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM subdomains WHERE name = ?", (name,)).fetchone()
        return row is not None

    # ── Notes ──

    def add_note(self, filename: str, topic: str, subdomain: str,
                 keyword: str, source: str, content: str, file_path: str):
        self.conn.execute(
            """INSERT OR REPLACE INTO notes
               (filename, topic, subdomain, keyword, source, content, file_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (filename, topic, subdomain, keyword, source, content, file_path,
             datetime.now().isoformat())
        )
        self.conn.commit()

    def get_note(self, filename: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM notes WHERE filename = ?", (filename,)).fetchone()
        return dict(row) if row else None

    def list_notes(self, topic: str = None, subdomain: str = None) -> list:
        query = "SELECT * FROM notes WHERE 1=1"
        params = []
        if topic:
            query += " AND topic = ?"
            params.append(topic)
        if subdomain:
            query += " AND subdomain = ?"
            params.append(subdomain)
        query += " ORDER BY filename"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def delete_note(self, filename: str):
        self.conn.execute("DELETE FROM notes WHERE filename = ?", (filename,))
        self.conn.commit()

    # ── Diary Processing Tracking ──

    def mark_diary_processed(self, file_path: str, filename: str, status: str,
                             notes_count: int = 0, session_id: str = None,
                             error_message: str = None):
        self.conn.execute(
            """INSERT OR REPLACE INTO diary_processed
               (file_path, filename, processed_at, status, notes_count, session_id, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_path, filename, datetime.now().isoformat(), status,
             notes_count, session_id, error_message)
        )
        self.conn.commit()

    def is_diary_processed(self, file_path: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM diary_processed WHERE file_path = ?", (file_path,)
        ).fetchone()
        return row is not None

    def get_processing_stats(self) -> dict:
        """按 status 分组计数。"""
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM diary_processed GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ── Clarification Sessions ──

    def save_session(self, session_id: str, original_file: str, questions: list,
                     status: str = "pending"):
        self.conn.execute(
            """INSERT OR REPLACE INTO clarification_sessions
               (session_id, original_file, questions, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, original_file, json.dumps(questions, ensure_ascii=False),
             status, datetime.now().isoformat())
        )
        self.conn.commit()

    def update_session_answers(self, session_id: str, answers: list):
        self.conn.execute(
            """UPDATE clarification_sessions
               SET answers = ?, status = 'answered', answered_at = ?
               WHERE session_id = ?""",
            (json.dumps(answers, ensure_ascii=False), datetime.now().isoformat(), session_id)
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM clarification_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        # Parse JSON fields
        d["questions"] = json.loads(d["questions"]) if d["questions"] else []
        d["answers"] = json.loads(d["answers"]) if d["answers"] else []
        return d

    def list_pending_sessions(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM clarification_sessions WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["questions"] = json.loads(d["questions"]) if d["questions"] else []
            d["answers"] = json.loads(d["answers"]) if d["answers"] else []
            result.append(d)
        return result

    def delete_session(self, session_id: str):
        self.conn.execute(
            "DELETE FROM clarification_sessions WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()

    # ── Tree Sync ──

    def sync_topics_from_tree(self, topics: list):
        """从 tree 文件同步 topics 到 DB。topics = [{name, description}]."""
        # 删除 DB 中有但 tree 中没有的 topic
        tree_names = {t["name"] for t in topics}
        db_names = {r["name"] for r in self.list_topics()}
        for name in db_names - tree_names:
            self.conn.execute("DELETE FROM topics WHERE name = ?", (name,))
            # Also remove orphaned subdomains
            self.conn.execute("DELETE FROM subdomains WHERE topic = ?", (name,))
        # 添加/更新 tree 中的 topics
        for t in topics:
            self.add_topic(t["name"], t.get("description", ""))

    def sync_subdomains_from_tree(self, subdomains: list):
        """从 tree 文件同步 subdomains 到 DB。subdomains = [{topic, name, description}]."""
        tree_names = {s["name"] for s in subdomains}
        db_names = {r["name"] for r in self.list_subdomains()}
        for name in db_names - tree_names:
            self.conn.execute("DELETE FROM subdomains WHERE name = ?", (name,))
        for s in subdomains:
            self.add_subdomain(s["name"], s["topic"], s.get("description", ""))

    # ── Close ──

    def close(self):
        self.conn.close()
