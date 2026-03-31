"""PDF 流水线：MinerU → 格式化 → 翻译 → 整理输出。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from loguru import logger

from paper_pipeline.formatting import (
    MARKDOWN_FORMATTER_AVAILABLE,
    format_markdown_file,
    format_with_prettier,
)
from paper_pipeline.arxiv_flow import translate_md
from paper_pipeline.subprocess_runner import run_external_command
from paper_pipeline.utils import get_ask_llm_dir


def rename_pdf_spaces_to_dashes(pdf_path: Path, yes: bool = False) -> Path:
    if " " not in pdf_path.name:
        return pdf_path
    new_name = pdf_path.name.replace(" ", "-")
    new_path = pdf_path.parent / new_name
    if new_path.exists() and new_path != pdf_path and not yes:
        logger.warning(f"目标文件已存在: {new_path}，跳过重命名")
        return pdf_path
    pdf_path.rename(new_path)
    logger.info(f"已重命名: {pdf_path.name} -> {new_path.name}")
    return new_path


def parse_pdf_with_mineru(pdf_path: Path, *, quiet: bool) -> Path:
    logger.info(f"正在使用 MinerU 解析 PDF: {pdf_path.name}")
    use_tty = sys.stdout.isatty() and not quiet
    cmd = ["mineru-parse", "parse", str(pdf_path)]
    rc = run_external_command(
        cmd,
        quiet=quiet,
        inherit_stdio=use_tty,
        log_component=None if (use_tty or quiet) else "mineru-parse",
    ).returncode
    if rc != 0:
        raise RuntimeError(f"MinerU 解析失败 (返回码: {rc})")
    return pdf_path.parent / f"{pdf_path.stem}_parsed"


def rename_full_md_to_pdf_name(
    parsed_dir: Path, pdf_stem: str, yes: bool = False
) -> Path:
    full_md = parsed_dir / "full.md"
    if not full_md.exists():
        raise FileNotFoundError(f"未找到 full.md: {full_md}")
    target = parsed_dir / f"{pdf_stem}.md"
    if target.exists() and target != full_md and not yes:
        logger.warning(f"目标已存在: {target}，跳过重命名")
        return full_md
    full_md.rename(target)
    return target


def cleanup_and_organize_pdf(
    pdf_path: Path,
    parsed_dir: Path,
    md_path: Path,
    trans_path: Path | None,
    output_dir: Path,
    yes: bool = False,
) -> None:
    logger.info("正在整理文件...")
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_stem = pdf_path.stem

    final_pdf = output_dir / pdf_path.name
    final_md = output_dir / f"{pdf_stem}.md"
    final_trans = output_dir / f"{pdf_stem}_trans.md"

    if pdf_path != final_pdf:
        shutil.copy2(pdf_path, final_pdf)
    if md_path.exists():
        shutil.copy2(md_path, final_md)
    if trans_path and trans_path.exists():
        shutil.copy2(trans_path, final_trans)

    images_dir = parsed_dir / "images"
    if images_dir.exists():
        dst = output_dir / "images"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(images_dir, dst)

    zip_file = pdf_path.parent / f"{pdf_stem}_parsed.zip"
    if zip_file.exists():
        zip_file.unlink()

    if parsed_dir.exists() and yes:
        shutil.rmtree(parsed_dir)
        logger.info(f"已删除临时目录: {parsed_dir}")
    elif parsed_dir.exists():
        logger.info(f"临时目录保留: {parsed_dir}")

    logger.info(f"所有文件已整理到: {output_dir}")


def process_single_pdf(
    pdf_path: Path,
    output_dir: Path,
    ask_llm_dir: Path | None,
    prompt_file: str,
    format_rules_file: Path | None,
    skip_translation: bool,
    skip_formatting: bool,
    skip_prettier: bool,
    skip_cleanup: bool,
    yes: bool,
    quiet: bool,
) -> dict:
    result: dict = {
        "pdf": str(pdf_path),
        "success": False,
        "error": None,
        "output_dir": None,
    }
    use_tty = sys.stdout.isatty() and not quiet

    try:
        logger.info(f"开始处理 PDF: {pdf_path.name}")

        pdf_path = rename_pdf_spaces_to_dashes(pdf_path, yes=yes)
        parsed_dir = parse_pdf_with_mineru(pdf_path, quiet=quiet)

        if not parsed_dir.exists():
            raise RuntimeError(f"解析目录不存在: {parsed_dir}")

        md_path = rename_full_md_to_pdf_name(parsed_dir, pdf_path.stem, yes=yes)

        if (
            not skip_formatting
            and format_rules_file
            and MARKDOWN_FORMATTER_AVAILABLE
        ):
            format_markdown_file(md_path, format_rules_file)

        if not skip_prettier:
            format_with_prettier(md_path)

        trans_path: Path | None = None
        if not skip_translation:
            trans_path = translate_md(
                md_path,
                ask_llm_dir or get_ask_llm_dir(),
                prompt_file,
                quiet=quiet,
                use_tty=use_tty,
            )
            if (
                trans_path
                and not skip_formatting
                and format_rules_file
                and MARKDOWN_FORMATTER_AVAILABLE
            ):
                format_markdown_file(trans_path, format_rules_file)
            if trans_path and not skip_prettier:
                format_with_prettier(trans_path)

        if not skip_cleanup:
            cleanup_and_organize_pdf(
                pdf_path, parsed_dir, md_path, trans_path, output_dir, yes=yes
            )
            result["output_dir"] = output_dir
        else:
            result["output_dir"] = parsed_dir

        result["success"] = True
        logger.info(f"✓ PDF 处理完成: {output_dir}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"✗ PDF 处理失败: {e}")

    return result
