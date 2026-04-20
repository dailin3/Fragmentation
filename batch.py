#!/usr/bin/env python3
"""
Batch Fragmentation: 批量并发处理 01-diary/ 下所有日记。
- asyncio + httpx 并发调用 DeepSeek API
- 每篇日记记录耗时（毫秒）
- 输出 JSONL 日志，便于后续统计
"""
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
DIARY_DIR = ROOT / "01-diary"
FRAG_DIR = ROOT / "02-fragment"
MEAN_DIR = ROOT / "Meaningless"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

VAGUE = {"未知", "模糊", "无主题", "待定", "无标题", "未定义", "无法归类"}

# ─── 配置 ───
CONCURRENCY = 5          # 并发数，可调
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = LOG_DIR / f"batch_{TIMESTAMP}.jsonl"


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def sanitize(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip() or "无标题"


def render_fragment(template_text: str, title: str, keyword: str,
                    content: str, diary_date: str, today: str) -> str:
    return (template_text
            .replace("{{DATE}}", diary_date)
            .replace("{{NOW-DATE}}", today)
            .replace("{{THEME}}", title)
            .replace("{{KEYWORD}}", keyword)
            .replace("{{CONTENT}}", content))


async def api_call(client: httpx.AsyncClient, prompt: str, env: dict) -> dict:
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
    resp = await client.post(env["DEEPSEEK_API_URL"], json=payload, headers=headers, timeout=120.0)
    resp.raise_for_status()
    outer = resp.json()
    content_str = outer["choices"][0]["message"]["content"].strip()
    if content_str.startswith("```"):
        content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
        content_str = re.sub(r"\s*```$", "", content_str)
    return json.loads(content_str)


async def process_one(
    diary_path: Path,
    env: dict,
    prompt_template: str,
    template_text: str,
    today: str,
    client: httpx.AsyncClient,
) -> dict:
    t0 = time.perf_counter()

    try:
        diary_text = diary_path.read_text(encoding="utf-8")
        prompt = f"{prompt_template.strip()}\n\n{diary_text}\n\n"

        digits = "".join(c for c in diary_path.stem if c.isdigit())
        diary_date = (f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
                      if len(digits) >= 8 else diary_path.stem)

        result = await api_call(client, prompt, env)
        fragments = result.get("fragments", [])
        total = result.get("total", len(fragments))

        used = set()
        written_count = 0
        skipped_count = 0
        written_files = []
        mean_counter = len(list(MEAN_DIR.glob(f"{diary_date.replace('-','')}-*.md")))

        for frag in fragments:
            title = frag.get("title", "").strip()
            keyword = frag.get("keyword", "").strip()
            content = frag.get("content", "").strip()
            meaningless = frag.get("meaningless", False)

            # 空内容跳过
            if not content:
                skipped_count += 1
                continue

            # 模糊/无意义 → Meaningless
            is_bad = meaningless or title in VAGUE or any(v in title for v in VAGUE)
            if is_bad:
                mean_counter += 1
                mean_title = f"{diary_date.replace('-','')}-{mean_counter:03d}"
                body = render_fragment(template_text, mean_title, "无意义",
                                       content, diary_date, today)
                (MEAN_DIR / f"{mean_title}.md").write_text(body, encoding="utf-8")
                skipped_count += 1
                continue

            if not keyword:
                keyword = title

            base = sanitize(title)
            final_title = base
            n = 1
            while final_title in used:
                n += 1
                final_title = f"{base}-{n}"
            used.add(final_title)

            body = render_fragment(template_text, final_title, keyword,
                                   content, diary_date, today)
            (FRAG_DIR / f"{final_title}.md").write_text(body, encoding="utf-8")
            written_count += 1
            written_files.append(final_title)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "diary": diary_path.name,
            "status": "ok",
            "fragments_total": total,
            "fragments_written": written_count,
            "fragments_skipped": skipped_count,
            "elapsed_ms": round(elapsed_ms),
            "error": "",
            "written_files": written_files,
        }

    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "diary": diary_path.name,
            "status": "error",
            "fragments_total": 0,
            "fragments_written": 0,
            "fragments_skipped": 0,
            "elapsed_ms": round(elapsed_ms),
            "error": str(e),
            "written_files": [],
        }


async def main():
    import sys

    env = load_env(ROOT / ".env")
    prompt_template = (ROOT / "prompt.md").read_text(encoding="utf-8")
    template_text = (ROOT / "template.md").read_text(encoding="utf-8")
    today = time.strftime("%Y-%m-%d")

    diaries = sorted(DIARY_DIR.glob("*.md"), reverse=True)
    if not diaries:
        print("❌ 01-diary/ 里没有日记文件")
        return

    # python batch.py [N] 限制处理数量
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
            diaries = diaries[:limit]
            print(f"⚠️  测试模式，只处理前 {limit} 篇")
        except ValueError:
            pass

    total = len(diaries)
    print(f"📦 找到 {total} 篇日记，并发数={CONCURRENCY}")
    print(f"📝 日志: {LOG_FILE}\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    t_start = time.perf_counter()

    async with httpx.AsyncClient() as client:
        async def run(path):
            async with sem:
                return await process_one(path, env, prompt_template,
                                        template_text, today, client)

        results = []
        for coro in asyncio.as_completed([run(p) for p in diaries]):
            result = await coro
            results.append(result)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
            mark = "✅" if result["status"] == "ok" else "❌"
            print(f"  {mark} [{result['elapsed_ms']}ms] {result['diary']} "
                  f"→ 写入 {result['fragments_written']}/{result['fragments_total']}")

    t_total = time.perf_counter() - t_start
    ok = [r for r in results if r["status"] == "ok"]
    fail = [r for r in results if r["status"] == "error"]

    print(f"\n{'='*50}")
    print(f"📊 完成！共 {len(results)} 篇，耗时 {t_total:.1f}s")
    print(f"   成功: {len(ok)} | 失败: {len(fail)}")
    print(f"   片段: 写入 {sum(r['fragments_written'] for r in ok)} | "
          f"跳过 {sum(r['fragments_skipped'] for r in ok)}")

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "success": len(ok),
        "failed": len(fail),
        "elapsed_s": round(t_total, 1),
        "concurrency": CONCURRENCY,
        "fragments_written": sum(r["fragments_written"] for r in ok),
        "fragments_skipped": sum(r["fragments_skipped"] for r in ok),
    }
    summary_file = LOG_DIR / f"summary_{TIMESTAMP}.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"📄 汇总: {summary_file}")


if __name__ == "__main__":
    asyncio.run(main())
