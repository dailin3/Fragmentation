#!/usr/bin/env python3
"""
关键词精炼：用 DeepSeek 对 gather 文件提取 3~8 个核心关键词。
用法: python3 refine_keywords.py [N]    测试前 N 个
"""
import asyncio
import json
import re
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
FRAG_DIR = ROOT / "02-fragment"
DB_PATH = ROOT / "fragments.db"

CONCURRENCY = 5

PROMPT = """你是一个关键词提取专家。阅读以下笔记内容，提取 3~8 个最能概括其核心主题的关键词。

要求：
- 关键词要具体、有信息量，不要过于宽泛的词（如"记录"、"思考"、"学习"等）
- 优先保留原文中出现过的关键词
- 输出纯 JSON 格式，不要其他任何文字

输出格式：{"keywords": ["关键词1", "关键词2", ...]}

笔记内容：
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


async def refine_keywords(client: httpx.AsyncClient, env: dict, content: str) -> list[str]:
    prompt = PROMPT + content[:3000]
    payload = {
        "model": env.get("MODEL", "deepseek-chat"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {env['DEEPSEEK_API_KEY']}",
    }
    for attempt in range(3):
        resp = await client.post(env["DEEPSEEK_API_URL"], json=payload, headers=headers, timeout=30.0)
        resp.raise_for_status()
        outer = resp.json()
        content_str = outer["choices"][0]["message"]["content"].strip()
        if content_str.startswith("```"):
            content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
            content_str = re.sub(r"\s*```$", "", content_str)
        try:
            result = json.loads(content_str)
            kws = result.get("keywords", [])
            return [k.strip() for k in kws if k.strip()][:8]
        except json.JSONDecodeError:
            if attempt == 2:
                return []
            await asyncio.sleep(1)
    return []


async def main():
    import sys

    env = load_env(ROOT / ".env")
    tpl_path = ROOT / "template_gather.md"
    template = tpl_path.read_text(encoding="utf-8")
    today = time.strftime("%Y-%m-%d")

    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute("""
        SELECT filename, origin, keyword, keywords FROM fragments
        WHERE filename LIKE '%-gather%' ORDER BY origin, filename
    """).fetchall()

    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
            rows = rows[:limit]
            print(f"⚠️  测试模式，只处理前 {limit} 个")
        except ValueError:
            pass

    print(f"📦 找到 {len(rows)} 个 gather 文件")

    sem = asyncio.Semaphore(CONCURRENCY)

    async def process_one(row):
        async with sem:
            filename = row[0]
            origin = row[1]
            keyword = row[2]
            db_links = json.loads(row[3]) if row[3] else []

            # 从文件读取，提取 links（非关键词的 [[...]] 是链接，但 merge 后已混在一起）
            fp = FRAG_DIR / filename
            if not fp.exists():
                return
            text = fp.read_text(encoding="utf-8")
            # 去掉 frontmatter
            m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
            body = m.group(2).strip() if m else text.strip()
            # 去掉所有 [[...]] 得到纯文本内容
            body_text = re.sub(r"\[\[[^\]]+\]\]", "", body).strip()
            # 提取所有 [[...]]（含 links + 旧 keywords）
            all_links = re.findall(r"\[\[([^\]]+)\]\]", body)

            if not body_text and all_links:
                body_text = "  ".join(all_links)

            # 用纯文本让 AI 提取关键词
            kws = await refine_keywords(client, env, body_text)
            if not kws:
                return

            # 重建文件：保留原始 links（去重）+ 新 keywords
            unique_links = []
            seen = set()
            for ln in all_links:
                if ln not in seen:
                    unique_links.append(ln)
                    seen.add(ln)

            links_str = "\n".join(f"[[{ln}]]" for ln in unique_links)
            kw_chain = " ".join(f"[[{k}]]" for k in kws)

            content = (template
                       .replace("{{DATE}}", origin)
                       .replace("{{NOW-DATE}}", today)
                       .replace("{{KEYWORD}}", keyword)
                       .replace("{{links}}", links_str))
            if kw_chain:
                content = content.rstrip() + "\n\n" + kw_chain + "\n"
            fp.write_text(content, encoding="utf-8")

            # 更新数据库
            db.execute("UPDATE fragments SET keywords = ? WHERE filename = ?",
                       (json.dumps(kws, ensure_ascii=False), filename))
            print(f"  ✅ {filename} → {kws}")

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[process_one(r) for r in rows])

    db.commit()
    db.close()
    print(f"\n✅ 完成！")


if __name__ == "__main__":
    asyncio.run(main())
