#!/usr/bin/env python3
"""
执行关键词删除：从文件和数据库中移除无意义关键词。
"""
import json
import re
import sqlite3
from pathlib import Path

FRAG_DIR = Path("02-fragment")
DB_PATH = "fragments.db"

# Load removal list
to_remove = set(json.loads(Path("keywords_to_remove.json").read_text(encoding="utf-8")))
print(f"待删除关键词: {len(to_remove)} 个")

# --- 1. Process fragment files (non-gather) ---
frag_files = [f for f in FRAG_DIR.glob("*.md") if "-gather.md" not in f.name]
frag_count = 0

for fp in frag_files:
    text = fp.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        continue
    fm = m.group(1)
    body = m.group(2)

    # Find keyword line(s) at the bottom (space-separated [[...]])
    lines = body.rstrip().split('\n')
    new_lines = []
    changed = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[[") and " " in stripped:
            # This is a keyword line - filter out removals
            kws = re.findall(r"\[\[([^\]]+)\]\]", stripped)
            kept_kws = [kw for kw in kws if kw not in to_remove]
            if len(kept_kws) < len(kws):
                changed = True
            if kept_kws:
                new_lines.append(" ".join(f"[[{kw}]]" for kw in kept_kws))
        else:
            new_lines.append(line)

    if changed:
        new_body = "\n".join(new_lines)
        new_text = f"---\n{fm}\n---\n{new_body}"
        fp.write_text(new_text, encoding="utf-8")
        frag_count += 1

print(f"修改了 {frag_count}/{len(frag_files)} 个 fragment 文件")

# --- 2. Process gather files ---
gather_files = sorted(FRAG_DIR.glob("*-gather.md"))
gather_count = 0

for gf in gather_files:
    text = gf.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        continue
    fm = m.group(1)
    body = m.group(2)

    lines = body.rstrip().split('\n')
    new_lines = []
    changed = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[[") and " " in stripped:
            kws = re.findall(r"\[\[([^\]]+)\]\]", stripped)
            kept_kws = [kw for kw in kws if kw not in to_remove]
            if len(kept_kws) < len(kws):
                changed = True
            if kept_kws:
                new_lines.append(" ".join(f"[[{kw}]]" for kw in kept_kws))
        else:
            new_lines.append(line)

    if changed:
        new_body = "\n".join(new_lines)
        new_text = f"---\n{fm}\n---\n{new_body}"
        gf.write_text(new_text, encoding="utf-8")
        gather_count += 1

print(f"修改了 {gather_count}/{len(gather_files)} 个 gather 文件")

# --- 3. Update database ---
db = sqlite3.connect(str(DB_PATH))
rows = db.execute("SELECT filename, keywords FROM fragments").fetchall()

db_updated = 0
for filename, keywords_str in rows:
    if not keywords_str:
        continue
    kws = json.loads(keywords_str)
    new_kws = [kw for kw in kws if kw not in to_remove]
    if len(new_kws) < len(kws):
        db.execute("UPDATE fragments SET keywords = ? WHERE filename = ?",
                   (json.dumps(new_kws, ensure_ascii=False), filename))
        db_updated += 1

db.commit()
print(f"更新了 {db_updated} 条数据库记录")

# Final count
remaining_rows = db.execute("SELECT keywords FROM fragments WHERE keywords IS NOT NULL").fetchall()
all_remaining = set()
for row in remaining_rows:
    if row[0]:
        all_remaining.update(json.loads(row[0]))
db.close()

print(f"\n剩余关键词总数: {len(all_remaining)} 个（去重）")
