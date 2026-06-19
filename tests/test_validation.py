"""validation 模块测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_pipeline.validation import detect_input_type  # noqa: E402


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2501.11120", "arxiv"),
        ("2501.11120v2", "arxiv"),
        ("cs/0112017v1", "arxiv"),
        ("math.CO/0602026", "arxiv"),
        ("/abs/2501.11120.pdf", "unknown"),
        ("not-an-id", "unknown"),
    ],
)
def test_detect_input_type(raw: str, expected: str) -> None:
    assert detect_input_type(raw) == expected
