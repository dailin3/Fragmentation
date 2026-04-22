#!/usr/bin/env python3
"""
Phase 2: 语义聚合
用 DeepSeek 判断同主题短 fragment 是否可逻辑连贯聚合，生成新的 gather 文件。
用法: python3 phase2_merge.py
"""
import asyncio
import json
import re
import sqlite3
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
FRAG_DIR = ROOT / "02-fragment"
DB_PATH = ROOT / "fragments.db"
CONCURRENCY = 5
SHORT_THRESHOLD = 100  # 正文字符阈值

PROMPT_PREFIX = """你是一个笔记聚合助手。以下是一组相同主题的短笔记片段，请判断它们是否可以逻辑连贯地聚合在一起。

要求：
1. 如果片段主题相关、语义连贯，可以合并为一个笔记，请将它们分组
2. 分组时考虑：主题一致性、内容互补性、时间线连贯性
3. 为每组选 3-5 个关键词（只能从以下白名单中选）：
   {whitelist}
4. 如果某些片段无法与任何组聚合，就让它单独成组
5. 返回 JSON 格式，不要其他任何文字

输出格式：
{
  "groups": [
    {{
      "members": ["文件名1.md", "文件名2.md"],
      "merged_keywords": ["关键词1", "关键词2", "关键词3"],
      "reason": "为什么这些片段可以聚合"
    }}
  ]
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
    """解析 fragment 文件，返回 frontmatter 信息和正文"""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        return None
    fm, body = m.group(1), m.group(2)

    origin_m = re.search(r'origin:\s*"([^"]+)"', fm)
    origin = origin_m.group(1) if origin_m else ""
    tags = re.findall(r'-\s*"#([^"]+)"', fm)
    keyword = tags[1] if len(tags) > 1 else ""

    # Extract body without keyword lines at bottom
    lines = body.strip().split('\n')
    content_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip lines that are keyword-style (space-separated [[...]])
        if stripped.startswith("[[") and " " in stripped:
            continue
        content_lines.append(line)

    content = '\n'.join(content_lines).strip()

    return {
        "filename": path.name,
        "origin": origin,
        "keyword": keyword,
        "content": content,
        "content_len": len(content),
    }


async def ask_deepseek(client: httpx.AsyncClient, env: dict, prompt: str) -> dict:
    """调用 DeepSeek API，返回 JSON 解析结果"""
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
                return {"groups": []}
            await asyncio.sleep(1)
    return {"groups": []}


def build_prompt(frags: list, whitelist: str) -> str:
    """构建 DeepSeek prompt"""
    text = PROMPT_PREFIX.replace("{whitelist}", whitelist)
    text += "\n\n"
    for i, frag in enumerate(frags, 1):
        content = frag["content"][:800]  # 截断避免过长
        text += f"--- 片段 {i} ---\n"
        text += f"文件: {frag['filename']}\n"
        text += f"[origin: {frag['origin']}]\n"
        text += f"{content}\n\n"
    return text


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    return name.replace("/", "-").replace("\\", "-").replace(":", "-")


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

    # Connect to DB
    db = sqlite3.connect(str(DB_PATH))

    # Get all non-gather fragments with their keywords
    frag_rows = db.execute("""
        SELECT filename, origin, keywords FROM fragments
        WHERE filename NOT LIKE '%-gather%'
    """).fetchall()

    print(f"共 {len(frag_rows)} 个非 gather fragment")

    # Find short fragments and group by keyword
    kw_to_frags = {}
    for filename, origin, keywords_str in frag_rows:
        if not keywords_str:
            continue
        kws = json.loads(keywords_str)
        fp = FRAG_DIR / filename
        if not fp.exists():
            continue
        frag = parse_fragment(fp)
        if not frag:
            continue

        if frag["content_len"] < SHORT_THRESHOLD:
            for kw in kws:
                if kw in whitelist:  # 只考虑白名单中的关键词
                    kw_to_frags.setdefault(kw, []).append(frag)

    # Filter keywords that have multiple short fragments (聚合有意义)
    merge_candidates = {kw: frags for kw, frags in kw_to_frags.items() if len(frags) >= 3}
    print(f"有 {len(merge_candidates)} 个关键词下有 3+ 个短 fragment")

    # Also handle keywords with fewer fragments (2)
    merge_small = {kw: frags for kw, frags in kw_to_frags.items() if len(frags) == 2}
    print(f"有 {len(merge_small)} 个关键词下只有 2 个短 fragment")

    # Process each keyword group through DeepSeek
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    sem = asyncio.Semaphore(CONCURRENCY)
    all_merge_results = []  # (keyword, groups)
    processed_kw = 0

    # Sort by number of fragments (most first, more meaningful)
    sorted_candidates = sorted(merge_candidates.items(), key=lambda x: len(x[1]), reverse=True)
    if limit:
        sorted_candidates = sorted_candidates[:limit]
        print(f"⚠️  测试模式：只处理前 {limit} 个关键词")

    async def process_keyword(kw, frags):
        nonlocal processed_kw
        async with sem:
            prompt = build_prompt(frags, whitelist_str)
            result = await ask_deepseek(client, env, prompt)
            processed_kw += 1
            if processed_kw % 10 == 0:
                print(f"  已处理 {processed_kw}/{len(merge_candidates)} 个关键词")
            if result.get("groups"):
                return (kw, result["groups"])
            return None

    async with httpx.AsyncClient() as client:
        tasks = [process_keyword(kw, frags) for kw, frags in merge_candidates.items()]
        results = await asyncio.gather(*tasks)

    for r in results:
        if r:
            all_merge_results.append(r)

    print(f"\nDeepSeek 返回了 {len(all_merge_results)} 个可聚合的关键词组")

    # Execute merges
    total_merged = 0
    total_fragments_deleted = 0
    all_merged_files = set()

    for kw, groups in all_merge_results:
        for group in groups:
            members = group.get("members", [])
            merged_kws = group.get("merged_keywords", [])

            # Filter to valid members that exist
            valid_members = []
            for m in members:
                fp = FRAG_DIR / m
                if fp.exists():
                    valid_members.append(m)

            if len(valid_members) < 2:
                continue  # 至少需要 2 个 fragment 才聚合

            # Deduplicate keywords from whitelist
            clean_kws = [kw for kw in merged_kws if kw in whitelist][:5]
            if not clean_kws:
                continue

            # Get earliest date
            dates = []
            for m in valid_members:
                fp = FRAG_DIR / m
                frag = parse_fragment(fp)
                if frag and frag["origin"]:
                    dates.append(frag["origin"])
            earliest = min(dates) if dates else "unknown"

            # Generate gather filename
            gather_name = sanitize_filename(f"{clean_kws[0]}-{earliest}-gather.md")
            gather_path = FRAG_DIR / gather_name

            # Build gather content
            # Sort by date
            member_frags = []
            for m in valid_members:
                fp = FRAG_DIR / m
                frag = parse_fragment(fp)
                if frag:
                    member_frags.append(frag)
            member_frags.sort(key=lambda f: f["origin"])

            # Build content
            sections = []
            for frag in member_frags:
                section = f"### {frag['filename']} [origin: {frag['origin']}]\n\n{frag['content']}"
                sections.append(section)

            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")

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

            # Delete original fragments
            for m in valid_members:
                fp = FRAG_DIR / m
                fp.unlink()
                all_merged_files.add(m)

            # Update DB: delete old, add new
            for m in valid_members:
                db.execute("DELETE FROM fragments WHERE filename = ?", (m,))

            db.execute("""
                INSERT OR REPLACE INTO fragments
                (filename, origin, keyword, keywords, content, created, published, file_path)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """, (
                gather_name, earliest, clean_kws[0],
                json.dumps(clean_kws, ensure_ascii=False),
                '\n\n'.join(s['content'] for s in member_frags),
                today,
                str(gather_path)
            ))

            total_merged += 1
            total_fragments_deleted += len(valid_members)
            print(f"  ✅ {gather_name} ← {len(valid_members)} 个片段")

    db.commit()
    db.close()

    print(f"\n聚合完成!")
    print(f"  生成 {total_merged} 个新 gather 文件")
    print(f"  删除 {total_fragments_deleted} 个 fragment 文件")


if __name__ == "__main__":
    asyncio.run(main())
