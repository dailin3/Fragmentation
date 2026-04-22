"""简单日志模块。"""
import logging
from pathlib import Path

from src.config import LOGS_DIR

LOGS_DIR.mkdir(exist_ok=True)

_extract_logger = logging.getLogger("extract")
_handler = logging.FileHandler(LOGS_DIR / "extract.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_extract_logger.addHandler(_handler)
_extract_logger.setLevel(logging.INFO)


def log_extract(source: str, status: str, notes: list = None, error: str = None):
    """记录提取操作。"""
    msg = f"extract {source} -> {status}"
    if notes:
        msg += f" notes={notes}"
    if error:
        msg += f" error={error}"
    _extract_logger.info(msg)


def log_tree_change(action: str, detail: str):
    """记录知识树变更。"""
    logger = logging.getLogger("tree")
    handler = logging.FileHandler(LOGS_DIR / "tree_changes.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info(f"tree {action}: {detail}")
