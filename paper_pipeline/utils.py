"""路径、文件名与项目根目录辅助函数。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def repo_root_from_pipeline() -> Path:
    """
    推断仓库根目录。

    优先使用 ``PAPER_PIPELINE_REPO_ROOT``，否则按源码相对路径回退。
    """
    env_root = os.environ.get("PAPER_PIPELINE_REPO_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parent.parent.parent


def get_ask_llm_dir() -> Path | None:
    try:
        import ask_llm

        return Path(ask_llm.__file__).resolve().parent.parent.parent
    except ImportError:
        return None


def sanitize_for_fs(s: str, max_len: int = 200) -> str:
    if not s:
        return ""
    safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "" for c in s)
    safe = safe.strip().replace(" ", "-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe.strip("-")
    return safe[:max_len] if len(safe) > max_len else safe


def build_pdf_output_dir_name(
    pdf_stem: str,
    source: str = "PDF",
    short: Optional[str] = None,
) -> str:
    if source or short:
        date_str = datetime.now().strftime("%Y%m%d")
        safe_source = sanitize_for_fs(source or "PDF", 80)
        safe_short = sanitize_for_fs(short, 80) if short else ""
        safe_stem = sanitize_for_fs(pdf_stem, 150)
        if safe_short:
            return f"{date_str}-{safe_source}-{safe_short}-{safe_stem}"
        return f"{date_str}-{safe_source}-{safe_stem}"
    return sanitize_for_fs(pdf_stem, 200)
