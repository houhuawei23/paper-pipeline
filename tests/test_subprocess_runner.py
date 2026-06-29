"""subprocess_runner 模块测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_pipeline.subprocess_runner import run_external_command  # noqa: E402


def test_quiet_mode_captures_output_on_failure() -> None:
    """quiet=True 时，命令成功不保留输出；命令失败应返回合并输出以便定位原因。"""
    result_ok = run_external_command(
        ["python", "-c", "print('hello')"],
        quiet=True,
    )
    assert result_ok.returncode == 0
    assert result_ok.stdout is None

    result_fail = run_external_command(
        ["python", "-c", "import sys; print('error-detail'); sys.exit(1)"],
        quiet=True,
    )
    assert result_fail.returncode == 1
    assert result_fail.stdout is not None
    assert "error-detail" in result_fail.stdout
