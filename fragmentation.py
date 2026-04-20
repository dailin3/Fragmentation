#!/usr/bin/env python3
"""Fragmentation: 打碎日记成碎片，写入 Obsidian 格式。"""
import json
import re
import sys
import time
from pathlib import Path
from urllib import error, request

VAGUE = {"未知", "模糊", "无主题", "待定", "无标题", "未定义", "无法归类"}


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
    # 去掉模型可能返回的 markdown 代码块包裹
    if content_str.startswith("```"):
        content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
        content_str = re.sub(r"\s*```$", "", content_str)
    return json.loads(content_str)


def sanitize(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip() or "无标题"


def build_prompt(prompt_template: str, diary_text: str, existing_fragments: str) -> str:
    # prompt.md 末尾已有"日记文本："占位，直接拼接
    return (
        f"{prompt_template.strip()}\n\n"
        f"{diary_text}\n\n"
        f"已有 fragments:\n{existing_fragments}"
    )


def render_fragment(
    template_text: str,
    title: str,
    keyword: str,
    content: str,
    diary_date: str,
    today: str,
) -> str:
    return (
        template_text.replace("{{DATE}}", diary_date)
        .replace("{{NOW-DATE}}", today)
        .replace("{{THEME}}", title)
        .replace("{{KEYWORD}}", keyword)
        .replace("{{CONTENT}}", content)  # content 本身，不要加 # title
    )


def write_log(log_path: Path, lines: list[str]):
    """同时写 stdout 和 log 文件。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        for line in lines:
            print(line)
            f.write(line + "\n")


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
    mean_dir = root / "Meaningless"
    frag_dir.mkdir(exist_ok=True)
    mean_dir.mkdir(exist_ok=True)
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)

    prompt_template = (root / "prompt.md").read_text(encoding="utf-8")
    template_text = (root / "template.md").read_text(encoding="utf-8")

    frag_block = "\n".join(
        f"- {p.stem}"
        for p in sorted(frag_dir.glob("*.md"))
    ) or "(无)"

    prompt = build_prompt(prompt_template, diary_text, frag_block)

    digits = re.sub(r"\D", "", diary_path.stem)
    diary_date = (
        f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        if len(digits) >= 8
        else diary_path.stem
    )
    log_path = log_dir / f"{diary_path.stem}.log"

    log_lines = []
    log_lines.append(f"=== {diary_path.name} ===")

    print(f"→ 处理日记: {diary_path.name}")
    t0 = time.time()
    result = api_call(prompt, env)
    elapsed = time.time() - t0

    fragments = result.get("fragments", [])
    total = result.get("total", len(fragments))
    log_lines.append(f"API 返回 {total} 个片段 ({elapsed:.1f}s)")

    used = set()
    written = []
    meaningless_list = []

    for frag in fragments:
        title = frag.get("title", "").strip()
        keyword = frag.get("keyword", "").strip()
        content = frag.get("content", "").strip()
        meaningless = frag.get("meaningless", False)

        # 空内容跳过
        if not content:
            log_lines.append(f"  ! 跳过（空内容）: {title}")
            continue

        # 模糊或无意义 → Meaningless
        is_bad = meaningless or title in VAGUE or any(v in title for v in VAGUE)
        if is_bad:
            mean_num = len(meaningless_list) + 1
            mean_title = f"{diary_date.replace('-','')}-{mean_num:03d}"
            body = render_fragment(
                template_text, mean_title, "无意义",
                content, diary_date, today,
            )
            out_path = mean_dir / f"{mean_title}.md"
            out_path.write_text(body, encoding="utf-8")
            reason = "无意义" if meaningless else "模糊标题"
            log_lines.append(f"  ! 跳过（{reason}）: {title} — {content[:40]}")
            meaningless_list.append(mean_title)
            continue

        if not keyword:
            keyword = title

        # 文件名去重
        base = sanitize(title)
        final_title = base
        n = 1
        while final_title in used:
            n += 1
            final_title = f"{base}-{n}"
        used.add(final_title)

        body = render_fragment(
            template_text, final_title, keyword,
            content, diary_date, today,
        )
        out_path = frag_dir / f"{final_title}.md"
        out_path.write_text(body, encoding="utf-8")

        log_lines.append(f"  → {final_title}")
        written.append(out_path)

    log_lines.append(f"📊 共 {total} 个片段 → 写入 {len(written)} 个 | 跳过 {len(meaningless_list)} 个（无意义/模糊）")

    # 写 log 文件
    write_log(log_path, log_lines)
    print(f"\n📊 共 {total} 个片段 → 写入 {len(written)} 个 | 跳过 {len(meaningless_list)} 个（无意义/模糊）")
    print(f"✅ 完成！log → {log_path}")


if __name__ == "__main__":
    main()
