"""Markdown 正则格式化与 Prettier。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_tools_dir = Path(__file__).resolve().parent.parent.parent / "tools"
if _tools_dir.is_dir() and str(_tools_dir) not in sys.path:
    sys.path.insert(0, str(_tools_dir))

try:
    from markdown_regex_replace import MarkdownProcessor, RegexRuleParser

    MARKDOWN_FORMATTER_AVAILABLE = True
except ImportError:
    MARKDOWN_FORMATTER_AVAILABLE = False


def format_markdown_file(md_path: Path, rules_file: Path) -> bool:
    if not MARKDOWN_FORMATTER_AVAILABLE or not md_path.exists():
        return False
    rf = rules_file
    if not rf.is_absolute():
        for candidate in (Path.cwd() / rf, rf):
            if candidate.exists():
                rf = candidate
                break
    if not rf.exists():
        return False
    try:
        rules = RegexRuleParser.parse_rules_file(rf)
        if not rules:
            return False
        all_valid, _ = RegexRuleParser.validate_rules(rules)
        if not all_valid:
            return False
        processor = MarkdownProcessor(rules)
        success, _ = processor.process_file(md_path)
        return success
    except OSError:
        return False


def format_with_prettier(md_path: Path) -> bool:
    if not md_path.exists():
        return False
    for cmd in (
        ["npx", "prettier", "--write", str(md_path)],
        ["prettier", "--write", str(md_path)],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


async def async_format_markdown_file(md_path: Path, rules_file: Path) -> bool:
    """异步包装 :func:`format_markdown_file`，在默认线程池中执行。"""
    import asyncio

    return await asyncio.to_thread(format_markdown_file, md_path, rules_file)


async def async_format_with_prettier(md_path: Path) -> bool:
    """异步包装 :func:`format_with_prettier`，在默认线程池中执行。"""
    import asyncio

    return await asyncio.to_thread(format_with_prettier, md_path)
