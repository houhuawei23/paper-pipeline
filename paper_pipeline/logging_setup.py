"""loguru 配置：控制台精简、文件详尽，并区分 ``component``。"""

from __future__ import annotations

import sys
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from loguru import logger

# 保证未调用 configure_pipeline_logging 前记录也有 component，避免 format 中 {extra[component]} 缺失
logger.configure(extra={"component": "pipeline"})

# 与 academic/arxiv2md-beta/src/arxiv2md_beta/config/default_config.yml 中 logging.console_format 对齐，
# 并增加一列 {extra[component]} 标明来源（pipeline / arxiv2md-beta / ask-llm 等）。
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<cyan>{extra[component]}</cyan> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
)

_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {extra[component]} | {level: <8} | {message}"
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CHILD_LEVEL_RE = re.compile(r"\|\s*(DEBUG|INFO|SUCCESS|WARNING|ERROR)\s*\|")
_RICH_SPINNER_PREFIX = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def _is_progress_noise(line: str) -> bool:
    """
    判定是否为高频进度刷新噪声（默认不写入日志文件）。

    保留：
    - 完成态（100% / ✓ Complete）
    - 失败/告警（由上层 WARNING/ERROR 分支处理）
    """
    # Rich / tqdm 常见进度条字符
    has_bar = "━" in line or "█" in line or "▏" in line or "▎" in line
    has_spinner = line.startswith(_RICH_SPINNER_PREFIX)
    looks_progress = has_bar or has_spinner
    if not looks_progress:
        return False

    keep_completion = ("100%" in line) or ("✓ Complete" in line)
    return not keep_completion


def _default_log_file() -> Path:
    xdg_state_home = Path(
        os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    )
    log_dir = xdg_state_home / "paper-pipeline-beta" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    return log_dir / f"paper-pipeline-beta-{stamp}.log"


def relay_subprocess_output(text: str, component: str) -> None:
    """
    将子进程捕获的 stdout/stderr 按行写入 loguru，使用独立 ``component``，避免与流水线日志混淆。

    行内容使用 ``{}`` 占位转义，避免花括号破坏 loguru 格式化。
    """
    if not text or not text.strip():
        return
    child = logger.bind(component=component)
    file_only = child.bind(to_console=False)
    prev_line: str | None = None
    for line in text.splitlines():
        line = _ANSI_RE.sub("", line).replace("\r", "").rstrip()
        if not line:
            continue
        # 连续重复行去重
        if line == prev_line:
            continue
        prev_line = line

        # 过滤高频进度刷新噪声，显著降低日志体积
        if _is_progress_noise(line):
            continue

        m = _CHILD_LEVEL_RE.search(line)
        child_level = m.group(1) if m else None
        if child_level in {"WARNING", "ERROR"}:
            child.log(child_level, "{}", line)
        else:
            # 子进程 INFO/进度细节仅写文件，避免刷屏。
            file_only.debug("{}", line)


def configure_pipeline_logging(
    *,
    verbose: bool = False,
    quiet: bool = False,
    level: Literal["DEBUG", "INFO", "ERROR"] | None = None,
    component: str = "pipeline",
    log_file: Path | None = None,
) -> None:
    """
    配置流水线日志。

    - quiet: 仅 ERROR
    - verbose: DEBUG
    - 默认: INFO
    所有级别均写入 **stderr**，避免与 tqdm 争用 stdout。
    每条记录带 ``component``，默认 ``pipeline``；子进程经 :func:`relay_subprocess_output` 绑定各自名称。
    """
    logger.remove()
    logger.configure(extra={"component": component, "to_console": True})

    if level:
        eff = level
    elif quiet:
        eff = "ERROR"
    elif verbose:
        eff = "DEBUG"
    else:
        eff = "INFO"

    logger.add(
        sys.stderr,
        level=eff,
        format=_CONSOLE_FORMAT,
        colorize=True,
        filter=lambda r: bool(r["extra"].get("to_console", True)),
    )

    file_path = (log_file or _default_log_file()).resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(file_path),
        level="DEBUG",
        format=_FILE_FORMAT,
        colorize=False,
        encoding="utf-8",
        enqueue=False,
    )
    logger.info(f"日志文件: {file_path}")
