#!/usr/bin/env python3
"""
Fragmentation SQLite 元数据管理。
- init: 扫描 02-fragment/ 建库导入
- query: 按日期/关键词/双链搜索
- batch: 删除关键词、移除双链等批量操作
- sync: 增量同步文件系统变更
"""
import argparse
import json
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent
FRAG_DIR = ROOT / "02-fragment"
DB_PATH = ROOT / "fragments.db"


# ─── 解析器 ───

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (metadata_dict, 剩余正文)。"""
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    raw = m.group(1)
    body = m.group(2)
    meta: dict = {}
    # 简单逐行解析（不依赖第三方库）
    current_key = None
    for line in raw.splitlines():
        if line.startswith("  - "):
            if current_key:
                val = line.strip().lstrip("- ").strip().strip('"').strip("'")
                meta.setdefault(current_key, []).append(val)
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v:
                meta[k] = v
            else:
                current_key = k
    return meta, body.strip()


def parse_wiki_links(text: str) -> tuple[list[str], str]:
    """提取末尾的 [[...]] 双链列表，返回 (links, 去掉双链的正文)。"""
    # 找最后一段连续的 [[...]]
    # 从末尾开始匹配
    links: list[str] = []
    # 从末尾往前扫描所有 [[...]]
    pattern = r"\[\[([^\]]+)\]\]"
    # 尝试匹配文件最后的部分
    all_links = re.findall(pattern, text)
    if all_links:
        # 验证这些链接是否在文件末尾（允许空白行分隔）
        last_link_end = len(text)
        # 从后往前检查是否都是链接
        stripped = text.rstrip()
        tail = stripped
        for link_text in reversed(all_links):
            expected = f"[[{link_text}]]"
            tail_stripped = tail.rstrip()
            if tail_stripped.endswith(expected):
                links.insert(0, link_text)
                tail = tail_stripped[: -len(expected)]
            else:
                break
        # 清理掉中间多余空白
        tail = tail.rstrip()
        return links, tail
    return [], text


def parse_fragment_file(path: Path) -> Optional[dict]:
    """解析一个 fragment .md 文件，返回元数据 dict。"""
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    origin = meta.get("origin", "")
    # keyword = tags 第二个（去掉 # 前缀）
    tags = meta.get("tags", [])
    keyword = ""
    if len(tags) >= 2:
        keyword = tags[1].lstrip("#")
    elif len(tags) == 1:
        keyword = tags[0].lstrip("#")

    created = meta.get("created", "")
    published = 1 if meta.get("published", "").strip() else 0

    # 提取双链 + 正文
    links, content = parse_wiki_links(body)

    return {
        "filename": path.name,
        "origin": origin,
        "keyword": keyword,
        "keywords": json.dumps(links, ensure_ascii=False),
        "content": content,
        "created": created,
        "published": published,
        "file_path": str(path.resolve()),
    }


# ─── 数据库操作 ───

class FragmentDB:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = DB_PATH
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS fragments (
                filename TEXT PRIMARY KEY,
                origin TEXT,
                keyword TEXT,
                keywords TEXT,
                content TEXT,
                created TEXT,
                published INTEGER DEFAULT 0,
                file_path TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_origin ON fragments(origin);
            CREATE INDEX IF NOT EXISTS idx_keyword ON fragments(keyword);
        """)
        self.conn.commit()

    def upsert(self, row: dict):
        self.conn.execute("""
            INSERT INTO fragments (filename, origin, keyword, keywords, content, created, published, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                origin=excluded.origin, keyword=excluded.keyword, keywords=excluded.keywords,
                content=excluded.content, created=excluded.created, published=excluded.published,
                file_path=excluded.file_path
        """, (row["filename"], row["origin"], row["keyword"], row["keywords"],
              row["content"], row["created"], row["published"], row["file_path"]))
        self.conn.commit()

    def delete(self, filename: str):
        self.conn.execute("DELETE FROM fragments WHERE filename = ?", (filename,))
        self.conn.commit()
    def init(self):
        """扫描 02-fragment/ 所有 .md 文件，批量导入。"""
        files = sorted(FRAG_DIR.glob("*.md"))
        if not files:
            print("❌ 02-fragment/ 为空")
            return
        print(f"📦 扫描 {len(files)} 个文件...")
        rows = []
        for p in files:
            try:
                row = parse_fragment_file(p)
                if row:
                    rows.append(row)
            except Exception as e:
                print(f"  ⚠️  {p.name}: {e}")

        self.conn.executemany("""
            INSERT INTO fragments (filename, origin, keyword, keywords, content, created, published, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                origin=excluded.origin, keyword=excluded.keyword, keywords=excluded.keywords,
                content=excluded.content, created=excluded.created, published=excluded.published,
                file_path=excluded.file_path
        """, [(r["filename"], r["origin"], r["keyword"], r["keywords"],
               r["content"], r["created"], r["published"], r["file_path"]) for r in rows])
        self.conn.commit()
        print(f"✅ 导入 {len(rows)} 条记录")

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM fragments").fetchone()[0]

    # ─── 查询 ───

    def by_keyword(self, kw: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM fragments WHERE keyword = ?", (kw,)
        ).fetchall()
        return [dict(r) for r in rows]

    def by_date(self, date: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM fragments WHERE origin = ?", (date,)
        ).fetchall()
        return [dict(r) for r in rows]

    def by_keyword_and_date(self, kw: str, date: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM fragments WHERE keyword = ? AND origin = ?", (kw, date)
        ).fetchall()
        return [dict(r) for r in rows]

    def has_keyword_in_links(self, kw: str) -> list[dict]:
        """查找双链中包含某词的笔记（精确匹配，非子串）。"""
        rows = self.conn.execute(
            "SELECT * FROM fragments WHERE keywords LIKE ?", (f"%{kw}%",)
        ).fetchall()
        # SQL LIKE 是子串匹配，需要 Python 层过滤确保精确匹配
        result = []
        for r in rows:
            links = json.loads(r["keywords"])
            if kw in links:
                result.append(dict(r))
        return result

    def search(self, query: str) -> list[dict]:
        """全文搜索（filename + keyword + content）。"""
        rows = self.conn.execute("""
            SELECT * FROM fragments
            WHERE filename LIKE ? OR keyword LIKE ? OR content LIKE ?
        """, (f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
        return [dict(r) for r in rows]

    def all_keywords(self) -> list[str]:
        """获取所有唯一的 keyword 列表。"""
        rows = self.conn.execute(
            "SELECT DISTINCT keyword FROM fragments WHERE keyword != '' ORDER BY keyword"
        ).fetchall()
        return [r["keyword"] for r in rows]

    def stats(self) -> dict:
        """统计信息。"""
        total = self.count()
        kw_count = self.conn.execute(
            "SELECT COUNT(DISTINCT keyword) FROM fragments WHERE keyword != ''"
        ).fetchone()[0]
        date_range = self.conn.execute(
            "SELECT MIN(origin), MAX(origin) FROM fragments WHERE origin != ''"
        ).fetchone()
        return {
            "total_fragments": total,
            "unique_keywords": kw_count,
            "date_range": (date_range[0], date_range[1]),
        }

    # ─── 批量操作 ───

    def remove_keyword(self, kw: str, confirm: bool = False) -> int:
        """从所有笔记的双链列表中移除某关键词，同时更新数据库。
        confirm=False 时只预览不执行。"""
        rows = self.has_keyword_in_links(kw)
        if not rows:
            print(f"  无双链包含 '{kw}' 的记录")
            return 0
        if not confirm:
            print(f"  [预览] 以下 {len(rows)} 个文件的 [[{kw}]] 将被移除:")
            for r in rows:
                print(f"    - {r['filename']}  links={r['keywords']}")
            return len(rows)
        count = 0
        for row in rows:
            links = json.loads(row["keywords"])
            if kw in links:
                links.remove(kw)
                new_kw_json = json.dumps(links, ensure_ascii=False)
                self.conn.execute(
                    "UPDATE fragments SET keywords = ? WHERE filename = ?",
                    (new_kw_json, row["filename"]))
                fp = FRAG_DIR / row["filename"]
                if fp.exists():
                    text = fp.read_text(encoding="utf-8")
                    text = re.sub(r"\[\[" + re.escape(kw) + r"\]\]\s*", "", text)
                    text = re.sub(r"\n{3,}", "\n\n", text)
                    fp.write_text(text.rstrip() + "\n", encoding="utf-8")
                count += 1
        self.conn.commit()
        print(f"  ✅ 已从 {count} 个文件中移除 [[{kw}]]（数据库同步更新）")
        return count

    def keyword_counts(self) -> dict[str, int]:
        """统计所有关键词（keyword 字段 + keywords 双链字段）的出现次数。"""
        counts: dict[str, int] = {}
        rows = self.conn.execute("SELECT keyword, keywords FROM fragments").fetchall()
        for r in rows:
            # keyword 字段
            if r["keyword"]:
                counts[r["keyword"]] = counts.get(r["keyword"], 0) + 1
            # keywords 双链字段
            for kw in json.loads(r["keywords"]):
                counts[kw] = counts.get(kw, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def remove_single_keywords(self, confirm: bool = False) -> int:
        """移除双链中只出现一次的关键词。keyword tag 不动。"""
        # 统计所有关键词出现次数（keyword + links 都算）
        counts: dict[str, int] = {}
        rows = self.conn.execute("SELECT filename, keyword, keywords FROM fragments").fetchall()
        for r in rows:
            if r["keyword"]:
                counts[r["keyword"]] = counts.get(r["keyword"], 0) + 1
            for kw in json.loads(r["keywords"]):
                counts[kw] = counts.get(kw, 0) + 1
        singles = {kw for kw, n in counts.items() if n == 1}
        if not singles:
            print("  没有只出现一次的关键词")
            return 0
        if not confirm:
            print(f"  [预览] 以下 {len(singles)} 个关键词只出现1次，将从双链中移除:")
            for kw in sorted(singles):
                print(f"    {kw}")
            return len(singles)
        # 执行：只清理 links 中的单次词，不动 keyword tag
        # 先转成普通 list 避免 sqlite3.Row 在 UPDATE 后失效
        data = [(r["filename"], r["keywords"]) for r in rows]
        updated = 0
        for filename, kw_str in data:
            links = json.loads(kw_str)
            new_links = [kw for kw in links if kw not in singles]
            if new_links != links:
                self.conn.execute(
                    "UPDATE fragments SET keywords = ? WHERE filename = ?",
                    (json.dumps(new_links, ensure_ascii=False), filename))
                # 更新文件：移除正文末尾的 [[单次关键词]]
                fp = FRAG_DIR / filename
                if fp.exists():
                    text = fp.read_text(encoding="utf-8")
                    for kw in singles:
                        if kw in links:
                            text = re.sub(r"\[\[" + re.escape(kw) + r"\]\]\s*", "", text)
                    text = re.sub(r"\n{3,}", "\n\n", text)
                    fp.write_text(text.rstrip() + "\n", encoding="utf-8")
                updated += 1
        self.conn.commit()
        print(f"  ✅ 已从 {updated} 个文件中移除 {len(singles)} 个单次关键词")
        return len(singles)

    def gather(self, confirm: bool = False) -> int:
        """按 (origin, 首个双链关键词) 聚合 fragment，树形结构：每个 fragment 只属于一个 gather。"""
        rows = self.conn.execute(
            "SELECT filename, origin, keywords FROM fragments WHERE keywords != '[]' AND keywords != '' ORDER BY origin, filename"
        ).fetchall()
        # 按 (date, 首个双链关键词) 分组
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in rows:
            links = json.loads(r["keywords"])
            if not links:
                continue
            date = r["origin"]
            first_kw = links[0]  # 取第一个双链关键词作为主题
            groups[(date, first_kw)].append({
                "filename": r["filename"],
                "keywords": links,
            })
        # 筛选 >= 2 的组
        candidates = [(k, v) for k, v in groups.items() if len(v) >= 2]
        if not candidates:
            print("  无同一天共享首个双链关键词的 fragment 组（>=2 个）")
            return 0
        if not confirm:
            print(f"  [预览] 将创建以下 {len(candidates)} 个 gather 文件:")
            for (date, kw), frags in sorted(candidates):
                fnames = [f["filename"] for f in frags]
                print(f"    {kw}-{date}-gather.md  ← ({len(fnames)} 个): {' '.join(fnames)}")
            return len(candidates)
        tpl_path = ROOT / "template_gather.md"
        if not tpl_path.exists():
            print("  ❌ template_gather.md 不存在")
            return 0
        template = tpl_path.read_text(encoding="utf-8")
        today = time.strftime("%Y-%m-%d")
        created = 0
        for (date, kw), frags in sorted(candidates):
            gather_name = f"{kw.replace('/', '-')}-{date}-gather.md"
            links_str = "\n".join(f"[[{f['filename'].replace('.md', '')}]]" for f in frags)
            all_kw = []
            seen_kw = set()
            for f in frags:
                for k in f["keywords"]:
                    if k not in seen_kw:
                        all_kw.append(k)
                        seen_kw.add(k)
            kw_chain = " ".join(f"[[{k}]]" for k in all_kw)
            content = (template
                       .replace("{{DATE}}", date)
                       .replace("{{NOW-DATE}}", today)
                       .replace("{{KEYWORD}}", kw)
                       .replace("{{links}}", links_str))
            if kw_chain:
                content = content.rstrip() + "\n\n" + kw_chain
            out_path = FRAG_DIR / gather_name
            out_path.write_text(content, encoding="utf-8")
            # 原 fragment 清空 keywords
            for f in frags:
                fp = FRAG_DIR / f["filename"]
                if fp.exists():
                    text = fp.read_text(encoding="utf-8")
                    _, clean_text = parse_wiki_links(text)
                    fp.write_text(clean_text.rstrip() + "\n", encoding="utf-8")
                self.conn.execute(
                    "UPDATE fragments SET keywords = ? WHERE filename = ?",
                    ("[]", f["filename"]))
            # 数据库记录 gather
            self.conn.execute("""
                INSERT OR REPLACE INTO fragments (filename, origin, keyword, keywords, content, created, published, file_path)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """, (gather_name, date, kw, json.dumps(all_kw, ensure_ascii=False),
                  content, today, str(out_path.resolve())))
            created += 1
        self.conn.commit()
        print(f"  ✅ 创建了 {created} 个 gather 文件，原 fragment keywords 已清空")
        return created

    def dedup_gathers(self, confirm: bool = False) -> int:
        """去重 gather 文件：同一天 keywords 完全一样的只保留一个。"""
        rows = self.conn.execute(
            "SELECT filename, origin, keywords FROM fragments WHERE filename LIKE '%-gather%' ORDER BY filename"
        ).fetchall()
        groups = defaultdict(list)
        for r in rows:
            key = (r["origin"], r["keywords"])
            groups[key].append(r["filename"])
        duplicates = {k: v for k, v in groups.items() if len(v) > 1}
        if not duplicates:
            print("  无重复的 gather 文件")
            return 0
        total_delete = sum(len(v) - 1 for v in duplicates.values())
        if not confirm:
            print(f"  [预览] 将删除以下 {total_delete} 个重复 gather 文件:")
            for (date, kw_str), files in sorted(duplicates.items()):
                print(f"    保留: {files[0]}")
                for f in files[1:]:
                    print(f"      ❌ {f}")
            return total_delete
        deleted = 0
        for files in duplicates.values():
            keep = files[0]
            for f in files[1:]:
                fp = FRAG_DIR / f
                if fp.exists():
                    fp.unlink()
                self.conn.execute("DELETE FROM fragments WHERE filename = ?", (f,))
                deleted += 1
        self.conn.commit()
        print(f"  ✅ 已删除 {deleted} 个重复 gather 文件")
        return deleted

    def merge_gathers(self, min_overlap: int = 2, confirm: bool = False) -> int:
        """同一天的 gather 文件，keywords 重叠 >= min_overlap 的合并为一组。"""
        rows = self.conn.execute(
            "SELECT filename, origin, keywords FROM fragments WHERE filename LIKE '%-gather%' ORDER BY origin, filename"
        ).fetchall()
        # 按日期分组
        by_date: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_date[r["origin"]].append({"filename": r["filename"], "kw": json.loads(r["keywords"])})
        # 找出每组内的连通分量（overlap >= min_overlap）
        groups_to_merge: list[dict] = []
        for date, frags in by_date.items():
            if len(frags) < 2:
                continue
            n = len(frags)
            parent = list(range(n))
            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x
            def union(a, b):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
            for i in range(n):
                for j in range(i+1, n):
                    common = set(frags[i]["kw"]) & set(frags[j]["kw"])
                    if len(common) >= min_overlap:
                        union(i, j)
            components = defaultdict(list)
            for i in range(n):
                components[find(i)].append(frags[i])
            for comp_frags in components.values():
                if len(comp_frags) >= 2:
                    groups_to_merge.append({
                        "date": date,
                        "frags": comp_frags,
                    })
        if not groups_to_merge:
            print("  无需要合并的 gather 文件")
            return 0
        if not confirm:
            print(f"  [预览] 将合并以下 {len(groups_to_merge)} 组 gather 文件:")
            for g in groups_to_merge:
                names = [f["filename"] for f in g["frags"]]
                print(f"    {g['date']}: {' + '.join(names)}")
            return len(groups_to_merge)
        # 执行合并
        tpl_path = ROOT / "template_gather.md"
        template = tpl_path.read_text(encoding="utf-8")
        today = time.strftime("%Y-%m-%d")
        merged = 0
        for g in groups_to_merge:
            date = g["date"]
            frags = g["frags"]
            names = sorted(f["filename"] for f in frags)
            # 新文件名用第一个 gather 的关键词
            first_kw = frags[0]["kw"][0] if frags[0]["kw"] else "gather"
            new_name = f"{first_kw.replace('/', '-')}-{date}-gather.md"
            # 收集所有 links 和 keywords
            all_links = []
            all_kw = []
            seen_kw = set()
            for f in frags:
                fp = FRAG_DIR / f["filename"]
                if fp.exists():
                    text = fp.read_text(encoding="utf-8")
                    meta, body = parse_frontmatter(text)
                    # 提取 [[文件名]] 链接
                    link_names = re.findall(r"\[\[([^\]]+)\]\]", body)
                    all_links.extend(link_names)
                    # 合并 keywords
                    for kw in f["kw"]:
                        if kw not in seen_kw:
                            all_kw.append(kw)
                            seen_kw.add(kw)
                self.conn.execute("DELETE FROM fragments WHERE filename = ?", (f["filename"],))
                # 删除旧文件
                if fp.exists():
                    fp.unlink()
            links_str = "\n".join(f"[[{ln}]]" for ln in all_links)
            kw_chain = " ".join(f"[[{k}]]" for k in all_kw)
            content = (template
                       .replace("{{DATE}}", date)
                       .replace("{{NOW-DATE}}", today)
                       .replace("{{KEYWORD}}", first_kw)
                       .replace("{{links}}", links_str))
            if kw_chain:
                content = content.rstrip() + "\n\n" + kw_chain
            out_path = FRAG_DIR / new_name
            out_path.write_text(content, encoding="utf-8")
            self.conn.execute("""
                INSERT OR REPLACE INTO fragments (filename, origin, keyword, keywords, content, created, published, file_path)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """, (new_name, date, first_kw, json.dumps(all_kw, ensure_ascii=False),
                  content, today, str(out_path.resolve())))
            merged += 1
        self.conn.commit()
        print(f"  ✅ 合并了 {merged} 组 gather 文件")
        return merged

    def sync(self) -> dict:
        """增量同步：对比文件系统与数据库，新增/删除的 fragment。"""
        db_filenames = set(
            r["filename"] for r in
            self.conn.execute("SELECT filename FROM fragments").fetchall()
        )
        fs_filenames = set(p.name for p in FRAG_DIR.glob("*.md"))

        new_files = fs_filenames - db_filenames
        deleted_files = db_filenames - fs_filenames

        imported = 0
        for name in new_files:
            try:
                row = parse_fragment_file(FRAG_DIR / name)
                if row:
                    self.upsert(row)
                    imported += 1
            except Exception as e:
                print(f"  ⚠️  {name}: {e}")

        for name in deleted_files:
            self.delete(name)

        self.conn.commit()
        return {"new": len(new_files), "deleted": len(deleted_files), "imported": imported}

    def close(self):
        self.conn.close()


# ─── CLI ───

def main():
    parser = argparse.ArgumentParser(description="Fragmentation 元数据管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="扫描 02-fragment/ 建库导入所有 fragment")
    sub.add_parser("count", help="显示数据库记录数")
    sub.add_parser("stats", help="显示统计信息")
    sub.add_parser("keywords", help="列出所有唯一 keyword")
    sub.add_parser("kw-counts", help="统计所有关键词出现次数")

    q_by_kw = sub.add_parser("query", help="按关键词查询")
    q_by_kw.add_argument("keyword", help="keyword 值")

    q_by_date = sub.add_parser("by-date", help="按日期查询")
    q_by_date.add_argument("date", help="origin 日期，如 2025-09-14")

    q_by_kw_date = sub.add_parser("by-kw-date", help="按关键词+日期查询")
    q_by_kw_date.add_argument("keyword")
    q_by_kw_date.add_argument("date")

    q_in_links = sub.add_parser("in-links", help="查找双链中包含某词的笔记")
    q_in_links.add_argument("keyword")

    q_search = sub.add_parser("search", help="全文搜索")
    q_search.add_argument("query")

    sync_cmd = sub.add_parser("sync", help="增量同步文件系统变更")

    rm_kw = sub.add_parser("remove", help="从所有笔记的双链中移除某关键词")
    rm_kw.add_argument("keyword", help="要移除的关键词，如 '学习'")
    rm_kw.add_argument("--confirm", action="store_true",
                       help="确认执行（默认只预览）")

    rm_single = sub.add_parser("remove-singles",
                               help="移除只出现1次的关键词（低价值标签批量清理）")
    rm_single.add_argument("--confirm", action="store_true",
                           help="确认执行（默认只预览）")

    gather = sub.add_parser("gather",
                            help="按日期+keyword聚合fragment，创建gather文件")
    gather.add_argument("--confirm", action="store_true",
                        help="确认执行（默认只预览）")

    dedup = sub.add_parser("dedup-gathers",
                           help="去重 gather 文件（同一天 keywords 相同的只保留一个）")
    dedup.add_argument("--confirm", action="store_true",
                       help="确认执行（默认只预览）")

    merge = sub.add_parser("merge-gathers",
                           help="合并同一天有 ≥2 个相同 keywords 的 gather 文件")
    merge.add_argument("--min-overlap", type=int, default=2,
                       help="最少重叠关键词数（默认 2）")
    merge.add_argument("--confirm", action="store_true",
                       help="确认执行（默认只预览）")

    args = parser.parse_args()

    db = FragmentDB()

    if args.cmd == "init":
        db.init()
    elif args.cmd == "count":
        print(f"📊 {db.count()} 条记录")
    elif args.cmd == "stats":
        s = db.stats()
        print(f"📊 总计: {s['total_fragments']}")
        print(f"   唯一关键词: {s['unique_keywords']}")
        print(f"   日期范围: {s['date_range'][0]} ~ {s['date_range'][1]}")
    elif args.cmd == "keywords":
        kws = db.all_keywords()
        print(f"📊 {len(kws)} 个唯一关键词:")
        for kw in kws:
            print(f"  {kw}")
    elif args.cmd == "kw-counts":
        counts = db.keyword_counts()
        print(f"📊 共 {len(counts)} 个不同关键词（含 keyword + 双链）:")
        for kw, n in counts.items():
            print(f"  {n:>4d}  {kw}")
    elif args.cmd == "query":
        rows = db.by_keyword(args.keyword)
        print(f"📊 {len(rows)} 条（keyword='{args.keyword}'）:")
        for r in rows[:50]:
            print(f"  {r['filename']}  origin={r['origin']}")
        if len(rows) > 50:
            print(f"  ... 还有 {len(rows) - 50} 条")
    elif args.cmd == "by-date":
        rows = db.by_date(args.date)
        print(f"📊 {len(rows)} 条（origin='{args.date}'）:")
        for r in rows:
            print(f"  {r['filename']}  kw={r['keyword']}")
    elif args.cmd == "by-kw-date":
        rows = db.by_keyword_and_date(args.keyword, args.date)
        print(f"📊 {len(rows)} 条（keyword='{args.keyword}', date='{args.date}'）:")
        for r in rows:
            print(f"  {r['filename']}")
    elif args.cmd == "in-links":
        rows = db.has_keyword_in_links(args.keyword)
        print(f"📊 {len(rows)} 条（双链包含 '{args.keyword}'）:")
        for r in rows[:50]:
            print(f"  {r['filename']}  links={r['keywords']}")
    elif args.cmd == "search":
        rows = db.search(args.query)
        print(f"📊 {len(rows)} 条（搜索 '{args.query}'）:")
        for r in rows[:50]:
            print(f"  {r['filename']}  kw={r['keyword']}")
    elif args.cmd == "sync":
        result = db.sync()
        print(f"📊 同步完成: 新增 {result['new']} 文件（导入 {result['imported']}），删除 {result['deleted']} 记录")
    elif args.cmd == "remove":
        db.remove_keyword(args.keyword, confirm=args.confirm)
    elif args.cmd == "remove-singles":
        db.remove_single_keywords(confirm=args.confirm)
    elif args.cmd == "gather":
        db.gather(confirm=args.confirm)
    elif args.cmd == "dedup-gathers":
        db.dedup_gathers(confirm=args.confirm)
    elif args.cmd == "merge-gathers":
        db.merge_gathers(min_overlap=args.min_overlap, confirm=args.confirm)

    db.close()


if __name__ == "__main__":
    main()
