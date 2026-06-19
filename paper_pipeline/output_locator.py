"""解析 arxiv2md-beta 输出目录：JSON 行、日志行、目录差分或 mtime 兜底。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

# 与 arxiv2md-beta runner 约定一致
_RESULT_PREFIX = "ARXIV2MD_RESULT_JSON="
_OUTPUT_DIR_LOG = re.compile(
    r"Output directory:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_DATE_PREFIX = re.compile(r"^([^-]+-)?\d{8}-")
_NEW_STYLE_ID = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")


def sidecar_result_path(base_output_dir: Path, arxiv_id: str) -> Path:
    """与 arxiv2md-beta ``_result_json_filename_key`` 文件名规则一致。"""
    s = arxiv_id.strip()
    m = _NEW_STYLE_ID.match(s)
    if m:
        key = m.group(1)
    else:
        key = s.replace("/", "_")
    return base_output_dir / f".arxiv2md-result-{key}.json"


def read_paper_output_dir_from_sidecar(
    base_output_dir: Path,
    arxiv_id: str,
) -> Path | None:
    """读取 ``.arxiv2md-result-{id}.json`` 侧车文件（不依赖子进程 stdio 捕获）。"""
    path = sidecar_result_path(base_output_dir, arxiv_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        p = data.get("paper_output_dir")
        if p:
            out = Path(p)
            if out.is_dir():
                return out
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return None


def parse_paper_output_dir_from_capture(text: str) -> Path | None:
    """从捕获的子进程输出中解析论文输出目录。"""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(_RESULT_PREFIX):
            try:
                payload = json.loads(line[len(_RESULT_PREFIX) :])
                p = payload.get("paper_output_dir")
                if p:
                    return Path(p)
            except (json.JSONDecodeError, TypeError):
                continue
        m = _OUTPUT_DIR_LOG.search(line)
        if m:
            return Path(m.group(1).strip())
    return None


def find_new_subdir_after_run(
    base_output_dir: Path,
    before_names: frozenset[str],
) -> Path | None:
    """
    单次运行后通过目录名差分定位新建子目录（仅适用于串行、单篇输出）。
    匹配名称中含 ``-`` 的目录（与旧逻辑一致）。
    """
    if not base_output_dir.is_dir():
        return None
    after = {p.name for p in base_output_dir.iterdir() if p.is_dir()}
    new = after - before_names
    candidates = [base_output_dir / n for n in new if "-" in n]
    if len(candidates) == 1:
        return candidates[0]
    return None


def find_arxiv_output_dir_fallback(
    base_output_dir: Path,
    *,
    arxiv_id: str | None = None,
    sleep_s: float = 0.2,
) -> Path | None:
    """
    兜底：在无法差分/解析时，从名称含 ``-`` 的子目录中选择。

    优先含 ``YYYYMMDD-`` 前缀的目录，避免误选历史遗留的 ``Unknown-...``；
    若给定 ``arxiv_id``，优先唯一匹配「主文件名含该 ID」的目录。
    """
    time.sleep(sleep_s)
    possible = [
        d
        for d in base_output_dir.iterdir()
        if d.is_dir() and "-" in d.name and not d.name.startswith(".")
    ]
    if not possible:
        return None

    base_norm = None
    if arxiv_id:
        base_norm = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id

    if base_norm:
        with_id: list[Path] = []
        for d in possible:
            for f in d.glob("*.md"):
                if f.name.endswith("_trans.md") or f.name.endswith("_translated.md"):
                    continue
                if base_norm in f.stem:
                    with_id.append(d)
                    break
        if len(with_id) == 1:
            return with_id[0]

    dated = [d for d in possible if _DATE_PREFIX.match(d.name)]
    non_unknown = [d for d in possible if not d.name.startswith("Unknown-")]

    if dated:
        pool = dated
    elif non_unknown:
        pool = non_unknown
    else:
        pool = possible

    if len(pool) == 1:
        return pool[0]
    return max(pool, key=lambda p: p.stat().st_mtime)
