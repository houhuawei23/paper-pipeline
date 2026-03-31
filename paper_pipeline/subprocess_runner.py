"""子进程执行：TTY 下继承 stdio；非 TTY 下捕获输出并启用纯文本环境变量。"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from loguru import logger

from paper_pipeline.logging_setup import relay_subprocess_output


@dataclass(frozen=True)
class ExternalCommandResult:
    """外部命令执行结果。"""

    returncode: int
    stdout: str | None = None
    """捕获模式下的合并输出；继承模式或 quiet 丢弃时为 None。"""


def _plain_env(base: Mapping[str, str]) -> dict[str, str]:
    env = dict(base)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["TQDM_DISABLE"] = "1"
    env["DISABLE_TQDM"] = "1"
    env.setdefault("FORCE_COLOR", "0")
    return env


def run_external_command(
    cmd: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    quiet: bool = False,
    inherit_stdio: bool | None = None,
    log_component: str | None = None,
) -> ExternalCommandResult:
    """
    运行外部命令。

    - ``inherit_stdio`` 为 None 时：若 ``sys.stdout.isatty()`` 为真则继承子进程 stdio。
    - 非 TTY：捕获 stdout/stderr 合并解析；子进程环境启用无 tqdm 的纯文本模式。
    - ``quiet=True``：不打印命令行；stdout/stderr 导向 DEVNULL，避免 PIPE 死锁（适合批量并行）。
    - ``log_component``：捕获模式下将子进程合并输出经 loguru 转发，便于与 ``pipeline`` 日志区分；
      继承终端模式下子进程直接写 tty，无法加前缀。
    """
    if not quiet:
        cmd_str = " ".join(shlex.quote(str(a)) for a in cmd)
        logger.debug(f"执行命令: {cmd_str}")
        if cwd is not None:
            logger.debug(f"工作目录: {cwd}")

    use_inherit = inherit_stdio if inherit_stdio is not None else (
        sys.stdout.isatty() and not quiet
    )
    cwd_s = str(cwd) if cwd is not None else None
    cmd_list = [str(x) for x in cmd]
    child_env = dict(os.environ if env is None else env)

    try:
        if quiet:
            rc = subprocess.run(
                cmd_list,
                cwd=cwd_s,
                env=child_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            return ExternalCommandResult(returncode=rc, stdout=None)

        if use_inherit:
            rc = subprocess.call(cmd_list, cwd=cwd_s, env=child_env)
            return ExternalCommandResult(returncode=rc, stdout=None)

        cap_env = _plain_env(child_env)
        # 合并 stderr→stdout，流式按行转发，避免 capture_output 整段缓冲导致「卡住」
        proc = subprocess.Popen(
            cmd_list,
            cwd=cwd_s,
            env=cap_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        chunks: list[str] = []
        try:
            for line in proc.stdout:
                chunks.append(line)
                if log_component and line.strip():
                    relay_subprocess_output(line, log_component)
        finally:
            proc.stdout.close()
        rc = proc.wait()
        out = "".join(chunks)
        return ExternalCommandResult(returncode=rc, stdout=out)
    except KeyboardInterrupt:
        logger.error("命令被用户中断")
        raise
