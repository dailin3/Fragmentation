#!/usr/bin/env python3
"""Fragmentation: 打碎日记成碎片，写入 Obsidian 格式。"""
import json
import re
import sys
import time
from pathlib import Path
from urllib import error, request


def load_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api_call(prompt: str, env: dict[str, str]) -> dict:
    payload = {
        "model": env.get("MODEL", "deepseek-chat"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        env["DEEPSEEK_API_URL"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {env['DEEPSEEK_API_KEY']}",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    outer = json.loads(raw)
    content_str = outer["choices"][0]["message"]["content"].strip()
    if content_str.startswith("```"):
        content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
        content_str = re.sub(r"\s*```$", "", content_str)
    return json.loads(content_str)


def sanitize(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip() or "无标题"


def render_fragment(
    template_text: str,
    title: str,
    keyword: str,
    content: str,
    keywords: list[str],
    diary_date: str,
    today: str,
) -> str:
    # keywords 末尾追加 [[...]] 双链
    kw链 = " ".join(f"[[{k}]]" for k in keywords)
    body = (
        template_text.replace("{{DATE}}", diary_date)
        .replace("{{NOW-DATE}}", today)
        .replace("{{THEME}}", title)
        .replace("{{KEYWORD}}", keyword)
        .replace("{{CONTENT}}", content)
    )
    if kw链:
        body = body.rstrip() + "\n\n" + kw链
    return body


def main():
    root = Path(__file__).parent.resolve()

    if len(sys.argv) > 1:
        diary_path = Path(sys.argv[1])
    else:
        diaries = sorted((root / "01-diary").glob("*.md"), reverse=True)
        if not diaries:
            print("❌ 01-diary/ 里没有日记文件")
            return
        diary_path = diaries[0]

    if not diary_path.is_absolute():
        diary_path = root / diary_path

    env = load_env(root / ".env")
    diary_text = diary_path.read_text(encoding="utf-8")
    today = time.strftime("%Y-%m-%d")
    frag_dir = root / "02-fragment"
    frag_dir.mkdir(exist_ok=True)
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)

    prompt_template = (root / "prompt.md").read_text(encoding="utf-8")
    template_text = (root / "template.md").read_text(encoding="utf-8")

    prompt = f"{prompt_template.strip()}\n\n{diary_text.strip()}"

    digits = re.sub(r"\D", "", diary_path.stem)
    diary_date = (
        f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        if len(digits) >= 8
        else diary_path.stem
    )
    log_path = log_dir / f"{diary_path.stem}.log"

    print(f"→ 处理日记: {diary_path.name}")
    t0 = time.time()
    result = api_call(prompt, env)
    elapsed = time.time() - t0

    fragments = result.get("fragments", [])
    total = result.get("total", len(fragments))

    used = set()
    written = []
    skipped = []

    for frag in fragments:
        title = frag.get("title", "").strip()
        keyword = frag.get("keyword", "").strip() or title
        keywords = frag.get("keywords", [])
        content = frag.get("content", "").strip()

        if not content:
            skipped.append(f"{title} (空内容)")
            continue

        # content 必须是原文子串（不是 AI 幻觉）
        if content not in diary_text:
            skipped.append(f"{title} (非原文)")
            continue

        base = sanitize(title)
        final_title = base
        n = 1
        while final_title in used:
            n += 1
            final_title = f"{base}-{n}"
        used.add(final_title)

        body = render_fragment(
            template_text, final_title, keyword,
            content, keywords, diary_date, today,
        )
        out_path = frag_dir / f"{final_title}.md"
        out_path.write_text(body, encoding="utf-8")
        print(f"  → {final_title}")
        written.append(out_path)

    print(f"\n📊 共 {total} 个片段 → 写入 {len(written)} 个 | 跳过 {len(skipped)} 个 ({elapsed:.1f}s)")
    if skipped:
        for s in skipped:
            print(f"  ! {s}")
    print(f"✅ 完成！log → {log_path}")

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"=== {diary_path.name} ===\n")
        f.write(f"API 返回 {total} 个片段 ({elapsed:.1f}s)\n")
        for p in written:
            f.write(f"→ {p.stem}\n")
        for s in skipped:
            f.write(f"! {s}\n")
        f.write(f"📊 共 {total} 个片段 → 写入 {len(written)} 个 | 跳过 {len(skipped)} 个\n")


if __name__ == "__main__":
    main()
