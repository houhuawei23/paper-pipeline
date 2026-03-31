"""output_locator 解析逻辑单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# 将 pipelines 加入 path 以便导入
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_pipeline.output_locator import (  # noqa: E402
    find_arxiv_output_dir_fallback,
    parse_paper_output_dir_from_capture,
    read_paper_output_dir_from_sidecar,
    sidecar_result_path,
)


def test_parse_json_line() -> None:
    payload = {"paper_output_dir": "/tmp/out/paper-dir"}
    text = f"ARXIV2MD_RESULT_JSON={json.dumps(payload)}\n"
    p = parse_paper_output_dir_from_capture(text)
    assert p == Path("/tmp/out/paper-dir")


def test_parse_output_directory_log() -> None:
    text = "2026-03-26 18:57:27 | INFO     | Output directory: /home/u/out/20170612-Arxiv-Foo\n"
    p = parse_paper_output_dir_from_capture(text)
    assert p == Path("/home/u/out/20170612-Arxiv-Foo")


def test_parse_prefers_json_over_log() -> None:
    payload = {"paper_output_dir": "/json/path"}
    text = (
        f"ARXIV2MD_RESULT_JSON={json.dumps(payload)}\n"
        "Output directory: /log/path\n"
    )
    p = parse_paper_output_dir_from_capture(text)
    assert p == Path("/json/path")


def test_sidecar_path_strips_version_suffix() -> None:
    p = sidecar_result_path(Path("/out"), "2505.22954v2")
    assert p.name == ".arxiv2md-result-2505.22954.json"


def test_read_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "20250529-Arxiv-Foo"
    target.mkdir()
    sc = tmp_path / ".arxiv2md-result-2505.22954.json"
    sc.write_text(
        json.dumps({"paper_output_dir": str(target), "result_key": "2505.22954"}),
        encoding="utf-8",
    )
    assert read_paper_output_dir_from_sidecar(tmp_path, "2505.22954v1") == target


def test_fallback_prefers_dated_over_unknown(tmp_path: Path) -> None:
    u = tmp_path / "Unknown-Arxiv-Old"
    d = tmp_path / "20250529-Arxiv-New"
    u.mkdir()
    d.mkdir()
    # 旧目录 mtime 更新，仍应选日期前缀
    (u / "x.txt").write_text("touch", encoding="utf-8")
    got = find_arxiv_output_dir_fallback(tmp_path, arxiv_id=None, sleep_s=0)
    assert got == d
