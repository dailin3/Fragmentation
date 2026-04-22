#!/usr/bin/env python3
import json
from pathlib import Path

suggested = json.loads(Path("keywords_to_remove.json").read_text(encoding="utf-8"))

kept_text = Path("kept_keywords.txt").read_text(encoding="utf-8")
kept = set(kept_text.split())

actual_remove = sorted(set(suggested) - kept)

Path("keywords_to_remove.json").write_text(
    json.dumps(actual_remove, ensure_ascii=False, indent=2), encoding="utf-8"
)

print(f"建议删除: {len(suggested)} 个")
print(f"用户保留: {len(kept)} 个")
print(f"实际删除: {len(actual_remove)} 个")
print("\n删除列表:")
for kw in actual_remove:
    print(f"  - {kw}")
