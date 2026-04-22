#!/usr/bin/env python3
"""
Phase 3: 短 fragment 终极处理
将所有 <150 字符的短 fragment 发给 DeepSeek，能聚合的聚合成 gather，
不能聚合的移到 meaningless/ 文件夹保留。
用法: python3 phase3_short.py
"""
import asyncio
import json
import re
import shutil
import sqlite3
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
FRAG_DIR = ROOT / "02-fragment"
MEANINGLESS_DIR = FRAG_DIR / "meaningless"
DB_PATH = ROOT / "fragments.db"
CONCURRENCY = 5
SHORT_THRESHOLD = 150
BATCH_SIZE = 80

PROMPT_PREFIX = """你是一个笔记聚合助手。以下是若干极短的笔记片段（正文均较短），请将它们按主题聚类。

要求：
1. 将主题相同、语义连贯的片段分到同一组，可以聚合
2. 对于完全孤立、无法与任何片段聚合的片段，标记为 "standalone"
3. 为每组选 2-4 个关键词（只能从以下白名单中选）：
   {whitelist}
4. 返回 JSON 格式，不要其他任何文字

输出格式：
{
  "groups": [
    {
      "members": ["文件名1.md", "文件名2.md", ...],
      "keywords": ["关键词1", "关键词2"],
      "reason": "为什么这些片段可以聚合"
    }
  ],
  "standalone": ["孤立文件名1.md", "孤立文件名2.md"]
}

笔记片段：
"""


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def parse_fragment(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        return None
    fm, body = m.group(1), m.group(2)

    origin_m = re.search(r'origin:\s*"([^"]+)"', fm)
    origin = origin_m.group(1) if origin_m else ""

    # Extract clean content (no keyword lines)
    lines = body.strip().split('\n')
    content_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[[") and " " in stripped:
            continue
        content_lines.append(line)

    content = '\n'.join(content_lines).strip()

    return {
        "filename": path.name,
        "origin": origin,
        "content": content,
        "content_len": len(content),
    }


def build_prompt(frags: list, whitelist: str) -> str:
    text = PROMPT_PREFIX.replace("{whitelist}", whitelist)
    text += "\n\n"
    for i, frag in enumerate(frags, 1):
        text += f"--- 片段 {i} ---\n"
        text += f"文件: {frag['filename']}\n"
        text += f"[origin: {frag['origin']}]\n"
        text += f"{frag['content']}\n\n"
    return text


async def ask_deepseek(client: httpx.AsyncClient, env: dict, prompt: str) -> dict:
    payload = {
        "model": env.get("MODEL", "deepseek-chat"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {env['DEEPSEEK_API_KEY']}",
    }
    for attempt in range(3):
        try:
            resp = await client.post(env["DEEPSEEK_API_URL"], json=payload, headers=headers, timeout=90.0)
            resp.raise_for_status()
            outer = resp.json()
            content_str = outer["choices"][0]["message"]["content"].strip()
            if content_str.startswith("```"):
                content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
                content_str = re.sub(r"\s*```$", "", content_str)
            result = json.loads(content_str)
            return result
        except Exception:
            if attempt == 2:
                return {"groups": [], "standalone": []}
            await asyncio.sleep(1)
    return {"groups": [], "standalone": []}


async def main():
    env = load_env(ROOT / ".env")

    # Load whitelist from keep.txt
    keep_text = (ROOT / "keep.txt").read_text(encoding="utf-8")
    whitelist = set()
    for line in keep_text.split('\n'):
        line = line.strip()
        if line.startswith('|') and line.endswith('|'):
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 3 and parts[1] and parts[1] != '关键词':
                whitelist.add(parts[1])
    whitelist_str = ", ".join(sorted(whitelist))

    # Collect short fragments
    files = sorted(f for f in FRAG_DIR.glob("*.md") if "-gather" not in f.name)
    short_frags = []
    for fp in files:
        frag = parse_fragment(fp)
        if frag and frag["content_len"] < SHORT_THRESHOLD:
            short_frags.append(frag)

    print(f"共 {len(short_frags)} 个短 fragment (< {SHORT_THRESHOLD} 字符)")

    # Split into batches
    batches = [short_frags[i:i+BATCH_SIZE] for i in range(0, len(short_frags), BATCH_SIZE)]
    print(f"分成 {len(batches)} 批，每批 ~{BATCH_SIZE} 个")

    sem = asyncio.Semaphore(CONCURRENCY)
    all_groups = []
    all_standalone = []

    async def process_batch(idx, batch):
        async with sem:
            prompt = build_prompt(batch, whitelist_str)
            result = await ask_deepseek(client, env, prompt)
            print(f"  批次 {idx+1}/{len(batches)} 完成: {len(result.get('groups', []))} 组, {len(result.get('standalone', []))} 个孤立")
            return result

    async with httpx.AsyncClient() as client:
        tasks = [process_batch(i, b) for i, b in enumerate(batches)]
        results = await asyncio.gather(*tasks)

    for r in results:
        all_groups.extend(r.get("groups", []))
        all_standalone.extend(r.get("standalone", []))

    print(f"\nAI 返回: {len(all_groups)} 个聚合组, {len(all_standalone)} 个孤立 fragment")

    # Connect to DB
    db = sqlite3.connect(str(DB_PATH))

    # Create meaningless dir
    MEANINGLESS_DIR.mkdir(exist_ok=True)

    # Execute group merges
    total_merged = 0
    total_moved = 0

    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    for group in all_groups:
        members = group.get("members", [])
        kws = group.get("keywords", [])

        # Filter valid members
        valid_members = []
        for m in members:
            fp = FRAG_DIR / m
            if fp.exists():
                frag = parse_fragment(fp)
                if frag:
                    valid_members.append(frag)

        if len(valid_members) < 2:
            # Not enough to merge, treat as standalone
            for m in members:
                fp = FRAG_DIR / m
                if fp.exists() and m not in all_standalone:
                    all_standalone.append(m)
            continue

        # Clean keywords
        clean_kws = [kw for kw in kws if kw in whitelist][:5]
        if not clean_kws:
            clean_kws = ["未分类"]

        # Get earliest date
        dates = []
        for frag in valid_members:
            if frag["origin"]:
                dates.append(frag["origin"])
        earliest = min(dates) if dates else today

        # Generate gather filename
        gather_name = f"{clean_kws[0]}-{earliest}-gather.md"
        gather_name = gather_name.replace("/", "-").replace("\\", "-").replace(":", "-")
        gather_path = FRAG_DIR / gather_name

        # Sort by date
        valid_members.sort(key=lambda f: f["origin"])

        # Build content
        sections = []
        for frag in valid_members:
            section = f"### {frag['filename']} [origin: {frag['origin']}]\n\n{frag['content']}"
            sections.append(section)

        kw_chain = " ".join(f"[[{k}]]" for k in clean_kws)
        sections_text = "\n\n".join(sections)
        gather_content = (
            f'---\n'
            f'origin: "{earliest}"\n'
            f'tags:\n'
            f'  - "#gather"\n'
            f'  - "#{clean_kws[0]}"\n'
            f'created: {today}\n'
            f'published:\n'
            f'---\n'
            f'\n'
            f'{sections_text}\n'
            f'\n'
            f'{kw_chain}\n'
        )
        gather_path.write_text(gather_content, encoding="utf-8")

        # Delete originals and update DB
        for frag in valid_members:
            fp = FRAG_DIR / frag["filename"]
            fp.unlink()
            db.execute("DELETE FROM fragments WHERE filename = ?", (frag["filename"],))

        # Add gather to DB
        db.execute("""
            INSERT OR REPLACE INTO fragments
            (filename, origin, keyword, keywords, content, created, published, file_path)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """, (
            gather_name, earliest, clean_kws[0],
            json.dumps(clean_kws, ensure_ascii=False),
            '\n\n'.join(s['content'] for s in valid_members),
            today,
            str(gather_path)
        ))

        total_merged += 1
        print(f"  ✅ {gather_name} ← {len(valid_members)} 个片段")

    # Move standalone fragments to meaningless/
    standalone_set = set()
    for s in all_standalone:
        if s not in standalone_set:
            standalone_set.add(s)

    for s in sorted(standalone_set):
        src = FRAG_DIR / s
        if src.exists():
            dst = MEANINGLESS_DIR / s
            shutil.move(str(src), str(dst))
            db.execute("DELETE FROM fragments WHERE filename = ?", (s,))
            total_moved += 1

    db.commit()
    db.close()

    print(f"\n完成!")
    print(f"  生成 {total_merged} 个新 gather 文件")
    print(f"  移动 {total_moved} 个孤立 fragment 到 meaningless/")
    print(f"  剩余短 fragment: {sum(1 for f in FRAG_DIR.glob('*.md') if '-gather' not in f.name and len(parse_fragment(f)['content']) < SHORT_THRESHOLD if parse_fragment(f))}")


if __name__ == "__main__":
    asyncio.run(main())
