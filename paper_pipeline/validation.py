"""输入校验与类型检测。"""

from __future__ import annotations

import re
from pathlib import Path

ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
LEGACY_ARXIV_ID_PATTERN = re.compile(r"^[a-zA-Z\-\.]+\/\d{7}(v\d+)?$")
PDF_URL_PATTERN = re.compile(r"^https?://.+\.pdf", re.IGNORECASE)


def detect_input_type(input_str: str) -> str:
    """返回: arxiv | pdf_path | pdf_url | unknown"""
    s = input_str.strip()
    if PDF_URL_PATTERN.match(s):
        return "pdf_url"
    if s.lower().startswith(("http://", "https://")) and ".pdf" in s.lower():
        return "pdf_url"
    p = Path(s)
    if p.exists() and p.is_file() and p.suffix.lower() == ".pdf":
        return "pdf_path"
    core = s.replace("v", "").split("v")[0] if "v" in s else s
    if ARXIV_ID_PATTERN.match(core):
        return "arxiv"
    if LEGACY_ARXIV_ID_PATTERN.match(core):
        return "arxiv"
    if re.match(r"^\d{4}\.\d{4,5}", s):
        return "arxiv"
    return "unknown"


def parse_arxiv_ids(input_source: str) -> list[str]:
    """单个 ID、逗号分隔、或文件路径（每行一个）。"""
    p = Path(input_source)
    if p.exists() and p.is_file():
        return [
            line.strip()
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return [x.strip() for x in input_source.split(",") if x.strip()]
