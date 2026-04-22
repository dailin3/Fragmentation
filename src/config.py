"""加载 .env 配置，定义项目路径常量。"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

_env_path = ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
DEEPSEEK_MODEL = os.environ.get("MODEL", "deepseek-chat")

DIARY_DIR = ROOT / "01-diary"
NOTES_DIR = ROOT / "02-notes"
TREE_FILE = ROOT / "tree.md"
TREE_DIR = NOTES_DIR / "tree"
EXTRACT_RULES_FILE = ROOT / "extract_rules.md"
DB_PATH = ROOT / "fragments.db"
LOGS_DIR = ROOT / "logs"
TEMPLATES_DIR = ROOT / "templates"
