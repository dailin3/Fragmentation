import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib import error, request


@dataclass
class ModelClient:
    api_key: str
    api_url: str
    model: str = "deepseek-chat"

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.api_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model request failed: {exc.code} {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"model request failed: {exc.reason}") from exc

        data = json.loads(raw)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected model response: {raw}") from exc


def create_model_client_from_env(env_path: Path) -> ModelClient:
    env = load_env_file(env_path)
    api_key = env.get("API_KEY") or env.get("DEEPSEEK_API_KEY")
    api_url = env.get("API_URL") or env.get("DEEPSEEK_API_URL")
    model = env.get("MODEL") or env.get("DEEPSEEK_MODEL") or "deepseek-chat"

    if not api_key:
        raise ValueError(f"missing API key in {env_path}")
    if not api_url:
        raise ValueError(f"missing API url in {env_path}")

    return ModelClient(api_key=api_key, api_url=api_url, model=model)


def load_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def analyze_single_diary(
    diary_path: Path,
    fragment_dir: Path,
    prompt_path: Path,
    template_path: Path,
    model_client: ModelClient,
    current_date: Optional[str] = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    diary_text = diary_path.read_text(encoding="utf-8")
    if not diary_text.strip():
        raise ValueError(f"diary is empty: {diary_path}")

    prompt_template = prompt_path.read_text(encoding="utf-8")
    markdown_template = template_path.read_text(encoding="utf-8")
    existing_fragments = read_existing_fragments(fragment_dir)

    today = current_date or date.today().isoformat()
    diary_date = normalize_diary_date(diary_path)
    log_path = fragment_dir / f"{diary_path.stem}.log"
    errors: list[str] = []

    for attempt in range(1, max_attempts + 1):
        prompt = build_prompt(
            prompt_template=prompt_template,
            diary_text=diary_text,
            existing_fragments=existing_fragments,
            previous_errors=errors,
        )
        response_text = model_client.generate(prompt)
        try:
            payload = parse_and_validate_response(
                response_text=response_text,
                diary_text=diary_text,
                existing_titles={item["title"] for item in existing_fragments},
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue

        written_files = write_fragments(
            fragments=payload["fragments"],
            fragment_dir=fragment_dir,
            template_text=markdown_template,
            diary_date=diary_date,
            current_date=today,
        )

        # Write skipped (vague title) fragments to a review log
        skipped = payload.get("skipped", [])
        skipped_log_path = None
        if skipped:
            skipped_log_path = write_skipped_log(
                skipped=skipped,
                diary_text=diary_text,
                diary_date=diary_date,
                current_date=today,
                output_dir=fragment_dir,
                diary_stem=diary_path.stem,
            )

        log_lines = [f"attempt {index + 1} invalid: {message}" for index, message in enumerate(errors)]
        log_lines.append(f"attempt {attempt} succeeded")
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        print(f"analyzed {diary_path.name} in {attempt} attempt(s)")
        for path in written_files:
            print(f"wrote {path}")
        if skipped_log_path:
            print(f"wrote skipped log {skipped_log_path}")
        return {
            "attempts": attempt,
            "written_files": written_files,
            "skipped_log_path": skipped_log_path,
            "log_path": log_path,
            "payload": payload,
        }

    log_lines = [f"attempt {index + 1} invalid: {message}" for index, message in enumerate(errors)]
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    raise RuntimeError(f"failed to analyze diary after {max_attempts} attempts")


def build_prompt(
    prompt_template: str,
    diary_text: str,
    existing_fragments: list[dict[str, str]],
    previous_errors: list[str],
) -> str:
    fragments_block = "\n\n".join(
        f"FILE: {item['file_name']}\nTITLE: {item['title']}\nCONTENT:\n{item['content']}"
        for item in existing_fragments
    )
    if not fragments_block:
        fragments_block = "(none)"

    prompt = (
        f"{prompt_template.strip()}\n\n"
        f"日记文本:\n{diary_text}\n\n"
        f"已有 fragments:\n{fragments_block}\n"
    )
    if previous_errors:
        prompt += "\n上一次输出存在这些错误, 你必须修复后重新生成:\n"
        prompt += "\n".join(f"- {message}" for message in previous_errors)
        prompt += "\n"
    return prompt


def read_existing_fragments(fragment_dir: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for path in sorted(fragment_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        items.append(
            {
                "file_name": path.name,
                "title": extract_title_from_fragment(content) or path.stem,
                "content": content,
            }
        )
    return items


def extract_title_from_fragment(content: str) -> Optional[str]:
    match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


# Titles that indicate vague/ambiguous content — these fragments go to log instead of folder
VAGUE_TITLES = {"未知", "模糊", "无主题", "待定", "无标题", "未定义", "无法归类"}
VAGUE_KEYWORDS = {"未知", "模糊", "无主题", "待定", "无标题", "未定义"}


def is_vague_title(title: str) -> bool:
    t = title.strip()
    if t in VAGUE_TITLES:
        return True
    for kw in VAGUE_KEYWORDS:
        if kw in t:
            return True
    return False


def parse_and_validate_response(
    response_text: str,
    diary_text: str,
    existing_titles: set[str],
) -> dict[str, Any]:
    # Strip markdown code block wrapper that models often add (e.g. ```json ... ```)
    cleaned = re.sub(r"^```json\s*", "", response_text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("response must be a JSON object")

    total = payload.get("total")
    fragments = payload.get("fragments")
    if not isinstance(fragments, list) or not fragments:
        raise ValueError("fragments must be a non-empty list")

    if not isinstance(total, int):
        raise ValueError(f"total must be an integer, got {type(total).__name__}")

    used_titles = set(existing_titles)
    normalized_fragments: list[dict[str, Any]] = []
    skipped_fragments: list[dict[str, Any]] = []

    for index, item in enumerate(fragments, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"fragment {index} must be an object")

        raw_title = item.get("title")
        duplicate = item.get("duplicate", False)
        content = item.get("content")
        if not isinstance(raw_title, str) or not raw_title.strip():
            raise ValueError(f"fragment {index} missing title")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"fragment {index} missing content")
        if content.count("[[") != content.count("]]"):
            raise ValueError(f"fragment {index} missing closing brackets")

        plain_content = content.replace("[[", "").replace("]]", "")
        if plain_content not in diary_text:
            raise ValueError(f"fragment {index} content is not contained in diary text")

        title = uniquify_title(raw_title.strip(), used_titles)
        used_titles.add(title)

        frag = {"title": title, "duplicate": bool(duplicate), "content": content}

        if is_vague_title(raw_title):
            skipped_fragments.append(frag)
        else:
            normalized_fragments.append(frag)

    if total != len(fragments):
        raise ValueError(f"total ({total}) does not match fragments count ({len(fragments)})")

    return {
        "total": total,
        "fragments": normalized_fragments,
        "skipped": skipped_fragments,
    }


def uniquify_title(title: str, used_titles: set[str]) -> str:
    if title not in used_titles:
        return title
    suffix = 1
    while f"{title}-{suffix}" in used_titles:
        suffix += 1
    return f"{title}-{suffix}"


def write_fragments(
    fragments: list[dict[str, Any]],
    fragment_dir: Path,
    template_text: str,
    diary_date: str,
    current_date: str,
) -> list[Path]:
    written_files: list[Path] = []
    for fragment in fragments:
        dup_flag = " [重复]" if fragment.get("duplicate") else ""
        output_text = render_fragment_markdown(
            template_text=template_text,
            title=fragment["title"] + dup_flag,
            content=fragment["content"],
            diary_date=diary_date,
            current_date=current_date,
        )
        base_name = fragment["title"]
        output_path = fragment_dir / f"{sanitize_file_name(base_name)}.md"
        output_path.write_text(output_text, encoding="utf-8")
        written_files.append(output_path)
    return written_files


def write_skipped_log(
    skipped: list[dict[str, Any]],
    diary_text: str,
    diary_date: str,
    current_date: str,
    output_dir: Path,
    diary_stem: str,
) -> Path:
    """Write skipped fragments to a log file for human review."""
    log_lines = [
        f"=== Skipped Fragments Review Log ===",
        f"Diary: {diary_stem}",
        f"Diary Date: {diary_date}",
        f"Generated: {current_date}",
        f"Total Skipped: {len(skipped)}",
        "",
        "=" * 60,
        "",
    ]
    for i, frag in enumerate(skipped, 1):
        log_lines.extend([
            f"--- Skipped Fragment #{i} ---",
            f"Title: {frag['title']}",
            f"Duplicate: {frag.get('duplicate', False)}",
            "",
            f"Content:",
            frag["content"],
            "",
            f"--- Raw Diary Context ---",
            # Show surrounding context in the original diary
            _find_context_in_diary(frag["content"], diary_text),
            "",
            "=" * 60,
            "",
        ])

    log_path = output_dir / f"{diary_stem}-skipped.md"
    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    return log_path


def _find_context_in_diary(content: str, diary_text: str) -> str:
    """Find the surrounding context of content in the diary."""
    plain = content.replace("[[", "").replace("]]", "")
    idx = diary_text.find(plain[:50])
    if idx < 0:
        return "(context not found in diary)"
    start = max(0, idx - 100)
    end = min(len(diary_text), idx + len(plain) + 100)
    return diary_text[start:end]


def render_fragment_markdown(
    template_text: str,
    title: str,
    content: str,
    diary_date: str,
    current_date: str,
) -> str:
    return (
        template_text.replace("{{DATE}}", diary_date)
        .replace("{{NOW-DATE}}", current_date)
        .replace("{{THEME}}", title)
        .replace("{{CONTENT}}", f"# {title}\n\n{content}")
    )


def sanitize_file_name(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "-", title).strip()
    return cleaned or "unknown"


def normalize_diary_date(diary_path: Path) -> str:
    digits = re.sub(r"\D", "", diary_path.stem)
    if len(digits) >= 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return diary_path.stem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze one diary file into fragments.")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--diary", required=True, help="Path to one diary markdown file")
    parser.add_argument("--current-date", default=None, help="Override today's date in YYYY-MM-DD")
    parser.add_argument("--max-attempts", type=int, default=3, help="Maximum model retry attempts")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    diary_path = Path(args.diary).resolve()
    fragment_dir = project_root / "02-fragment"
    prompt_path = project_root / "prompt.md"
    template_path = project_root / "template.md"
    env_path = project_root / ".env"

    client = create_model_client_from_env(env_path)
    result = analyze_single_diary(
        diary_path=diary_path,
        fragment_dir=fragment_dir,
        prompt_path=prompt_path,
        template_path=template_path,
        model_client=client,
        current_date=args.current_date,
        max_attempts=args.max_attempts,
    )

    print(f"done: wrote {len(result['written_files'])} fragment file(s)")
    for path in result["written_files"]:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
