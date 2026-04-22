#!/usr/bin/env python3
"""
关键词清理：用 DeepSeek 筛选出无意义/太泛的关键词。
用法: python3 clean_keywords.py
"""
import asyncio
import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
DB_PATH = ROOT / "fragments.db"
CONCURRENCY = 3

PROMPT = """你是一个关键词筛选助手。以下是一组笔记的关键词列表，请筛选出那些**无意义、太泛、不知所云**的关键词。

判断标准：
- 太泛的词：如"状态"、"完成"、"方法"、"过程"、"问题"、"记录"、"感受"、"思考"、"学习"、"准备"、"计划"、"开始"、"结束"、"目标"、"方向"、"选择"、"决定"等
- 描述性而非概念性的词：如"迈出"、"已完成"、"高效"、"低效"、"忙碌"等
- 太常见的日常词：如"吃饭"、"睡觉"、"明天"、"三点"、"周末"、"假期"等
- 单个字的词：如"曲"等
- 但以下词应该保留：具体技术名词（C++、Python、Docker等）、具体概念（协程、内存管理、智能指针等）、具体主题（原神、线性代数、北邮等）、具体情绪/心理状态（焦虑、迷茫、自律等）

请返回 JSON 格式：{"remove": ["关键词1", "关键词2", ...]}

关键词列表：
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


async def main():
    import sqlite3

    env = load_env(ROOT / ".env")

    # Get all unique keywords from DB
    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute("SELECT keywords FROM fragments").fetchall()
    db.close()

    all_kws = set()
    for row in rows:
        if row[0]:
            kws = json.loads(row[0])
            all_kws.update(kws)

    kw_list = sorted(all_kws)
    print(f"总关键词: {len(kw_list)} 个")

    # Split into batches of ~200
    batch_size = 200
    batches = [kw_list[i:i+batch_size] for i in range(0, len(kw_list), batch_size)]
    print(f"分成 {len(batches)} 批，每批 {batch_size} 个")

    sem = asyncio.Semaphore(CONCURRENCY)
    all_remove = []

    async def process_batch(batch):
        async with sem:
            kw_str = ", ".join(batch)
            prompt = PROMPT + kw_str
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
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            env["DEEPSEEK_API_URL"],
                            json=payload, headers=headers, timeout=60.0
                        )
                    resp.raise_for_status()
                    outer = resp.json()
                    content_str = outer["choices"][0]["message"]["content"].strip()
                    if content_str.startswith("```"):
                        content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
                        content_str = re.sub(r"\s*```$", "", content_str)
                    result = json.loads(content_str)
                    return result.get("remove", [])
                except Exception:
                    if attempt == 2:
                        return []
                    await asyncio.sleep(1)
            return []

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[process_batch(b) for b in batches])

    for r in results:
        all_remove.extend(r)

    # Deduplicate and filter to only keywords that actually exist
    all_remove = sorted(set(all_remove) & all_kws)

    # Save to file
    output_path = ROOT / "keywords_to_remove.json"
    output_path.write_text(json.dumps(all_remove, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n建议删除 {len(all_remove)} 个关键词：")
    for kw in all_remove:
        print(f"  - {kw}")


if __name__ == "__main__":
    asyncio.run(main())
