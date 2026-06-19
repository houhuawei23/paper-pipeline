"""arXiv 流水线：arxiv2md-beta → 格式化 → 翻译。"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from paper_pipeline.formatting import (
    MARKDOWN_FORMATTER_AVAILABLE,
    format_markdown_file,
    format_with_prettier,
)
from paper_pipeline.output_locator import (
    find_arxiv_output_dir_fallback,
    find_new_subdir_after_run,
    parse_paper_output_dir_from_capture,
    read_paper_output_dir_from_sidecar,
)
from paper_pipeline.subprocess_runner import run_external_command
from paper_pipeline.utils import get_ask_llm_dir, repo_root_from_pipeline


def resolve_paper_output_dir(
    base_output_dir: Path,
    arxiv_id: str,
    captured_stdout: str | None,
    before_names: frozenset[str] | None,
) -> Path | None:
    """确定 arxiv2md-beta 生成的论文目录。"""
    p = read_paper_output_dir_from_sidecar(base_output_dir, arxiv_id)
    if p is not None:
        return p
    if captured_stdout:
        p = parse_paper_output_dir_from_capture(captured_stdout)
        if p is not None and p.is_dir():
            return p
    if before_names is not None:
        p = find_new_subdir_after_run(base_output_dir, before_names)
        if p is not None:
            return p
    return find_arxiv_output_dir_fallback(base_output_dir, arxiv_id=arxiv_id)


def translate_md(
    md_path: Path,
    ask_llm_dir: Path | None,
    prompt_file: str,
    *,
    quiet: bool,
    use_tty: bool,
) -> Path | None:
    """调用 ask-llm trans。"""
    cwd: Path | None = ask_llm_dir or get_ask_llm_dir()
    if cwd is None:
        return None
    cmd: list[str] = [
        "ask-llm",
        "trans",
        str(md_path),
        "-o",
        str(md_path.parent),
        "-p",
        prompt_file,
        "-f",
    ]
    if not use_tty:
        cmd.append("--stream")
    rc = run_external_command(
        cmd,
        cwd=cwd,
        quiet=quiet,
        inherit_stdio=False,
        log_component=None if quiet else "ask-llm",
    ).returncode
    if rc != 0:
        return None
    for name in (f"{md_path.stem}_translated.md", f"{md_path.stem}_trans.md"):
        p = md_path.parent / name
        if p.exists():
            return p
    return None


def process_single_arxiv_paper(
    arxiv_id: str,
    base_output_dir: Path,
    arxiv2md_beta_dir: Path | None,
    ask_llm_dir: Path | None,
    prompt_file: str,
    format_rules_file: Path | None,
    skip_translation: bool,
    skip_formatting: bool,
    skip_prettier: bool,
    quiet: bool,
    arxiv2md_extra: list[str],
    *,
    parallel_worker: bool = False,
    no_arxiv_progress: bool = False,
) -> dict:
    """
    处理单篇 arXiv 论文。

    - parallel_worker: 批量并行中的工作线程（安静、丢弃子进程输出，目录用 mtime 兜底）。
    - no_arxiv_progress: 为 True 时向 arxiv2md-beta 传入 ``--no-progress``（仅单线程 TTY 有意义）。
    """
    result: dict = {
        "arxiv_id": arxiv_id,
        "success": False,
        "error": None,
        "output_dir": None,
    }
    use_tty = sys.stdout.isatty() and not parallel_worker and not quiet

    try:
        logger.info(f"开始处理: {arxiv_id}")

        extra = list(arxiv2md_extra)
        if no_arxiv_progress:
            extra.append("--no-progress")
        # 始终发出 JSON 行 + 侧车文件；子进程 stdout/stderr 捕获解析，避免 TTY 下无法解析目录
        extra.append("--emit-result-json")

        cmd: list[str] = [
            sys.executable,
            "-m",
            "arxiv2md_beta",
            "convert",
            arxiv_id,
            "--output",
            str(base_output_dir),
            *extra,
        ]

        before_names: frozenset[str] | None = None
        if use_tty:
            before_names = frozenset(
                p.name for p in base_output_dir.iterdir() if p.is_dir()
            )

        r = run_external_command(
            cmd,
            cwd=arxiv2md_beta_dir,
            quiet=parallel_worker or quiet,
            inherit_stdio=False,
            log_component=None
            if (parallel_worker or quiet)
            else "arxiv2md-beta",
        )

        if r.returncode != 0:
            raise RuntimeError(f"arxiv2md-beta 处理失败 (返回码: {r.returncode})")

        output_dir = resolve_paper_output_dir(
            base_output_dir,
            arxiv_id,
            r.stdout,
            before_names,
        )
        if output_dir is None:
            raise RuntimeError("未找到输出目录")

        result["output_dir"] = output_dir
        logger.info(f"[{arxiv_id}] 找到输出目录: {output_dir.name}")

        md_files = [
            f
            for f in output_dir.glob("*.md")
            if not f.name.endswith("_trans.md")
            and not f.name.endswith("_translated.md")
        ]
        if not md_files:
            raise RuntimeError("未找到 Markdown 文件")

        main_candidates = [
            f
            for f in md_files
            if not f.name.endswith("-References.md")
            and not f.name.endswith("-Appendix.md")
        ]
        if main_candidates:
            md_file = (
                main_candidates[0]
                if len(main_candidates) == 1
                else max(main_candidates, key=lambda p: p.stat().st_mtime)
            )
        else:
            md_file = md_files[0]
        if " " in md_file.name:
            new_path = md_file.parent / md_file.name.replace(" ", "-")
            md_file.rename(new_path)
            md_file = new_path

        if (
            not skip_formatting
            and format_rules_file
            and MARKDOWN_FORMATTER_AVAILABLE
        ):
            logger.info(f"[{arxiv_id}] 步骤 2: 格式化原始 Markdown")
            format_markdown_file(md_file, format_rules_file)

        if not skip_prettier:
            logger.info(f"[{arxiv_id}] 步骤 2b: Prettier 格式化")
            format_with_prettier(md_file)

        # arxiv2md-beta：{basename}-Appendix.md 与正文分开；仅格式化附录源文件，不翻译 -References.md
        appendix_md = md_file.parent / f"{md_file.stem}-Appendix.md"
        if appendix_md.is_file():
            if (
                not skip_formatting
                and format_rules_file
                and MARKDOWN_FORMATTER_AVAILABLE
            ):
                logger.info(f"[{arxiv_id}] 步骤 2c: 格式化附录 Markdown")
                format_markdown_file(appendix_md, format_rules_file)
            if not skip_prettier:
                logger.info(f"[{arxiv_id}] 步骤 2d: Prettier 附录")
                format_with_prettier(appendix_md)

        trans_file: Path | None = None
        if not skip_translation:
            logger.info(
                f"[{arxiv_id}] 步骤 3: 翻译正文 Markdown"
                + "（标题、作者、ArXiv 等元数据一同交给 ask-llm trans 翻译）"
            )
            trans_file = translate_md(
                md_file,
                ask_llm_dir,
                prompt_file,
                quiet=parallel_worker or quiet,
                use_tty=use_tty,
            )
            if trans_file:
                if (
                    not skip_formatting
                    and format_rules_file
                    and MARKDOWN_FORMATTER_AVAILABLE
                ):
                    logger.info(f"[{arxiv_id}] 步骤 4: 格式化翻译后的正文")
                    format_markdown_file(trans_file, format_rules_file)
                if not skip_prettier:
                    format_with_prettier(trans_file)
                if trans_file.name.endswith("_translated.md"):
                    new_path = trans_file.parent / f"{md_file.stem}_trans.md"
                    if new_path.exists() and new_path != trans_file:
                        new_path.unlink()
                    trans_file.rename(new_path)
                    trans_file = new_path

            if appendix_md.is_file():
                logger.info(f"[{arxiv_id}] 步骤 3b: 翻译附录 Markdown")
                trans_appendix = translate_md(
                    appendix_md,
                    ask_llm_dir,
                    prompt_file,
                    quiet=parallel_worker or quiet,
                    use_tty=use_tty,
                )
                if trans_appendix:
                    if (
                        not skip_formatting
                        and format_rules_file
                        and MARKDOWN_FORMATTER_AVAILABLE
                    ):
                        logger.info(f"[{arxiv_id}] 步骤 4b: 格式化翻译后的附录")
                        format_markdown_file(trans_appendix, format_rules_file)
                    if not skip_prettier:
                        format_with_prettier(trans_appendix)
                    if trans_appendix.name.endswith("_translated.md"):
                        new_app = trans_appendix.parent / f"{appendix_md.stem}_trans.md"
                        if new_app.exists() and new_app != trans_appendix:
                            new_app.unlink()
                        trans_appendix.rename(new_app)

        result["success"] = True
        logger.info(f"[{arxiv_id}] ✓ 处理完成: {output_dir}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[{arxiv_id}] ✗ 处理失败: {e}")

    return result


def default_arxiv2md_cwd() -> Path | None:
    root = repo_root_from_pipeline()
    candidate = root / "academic" / "arxiv2md-beta"
    if candidate.exists():
        return candidate
    return None
