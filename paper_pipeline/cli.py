"""Paper pipeline CLI."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer
from loguru import logger

from paper_pipeline.arxiv_flow import default_arxiv2md_cwd, process_single_arxiv_paper
from paper_pipeline.logging_setup import configure_pipeline_logging
from paper_pipeline.pdf_flow import process_single_pdf
from paper_pipeline.utils import build_pdf_output_dir_name, get_ask_llm_dir
from paper_pipeline.validation import detect_input_type, parse_arxiv_ids


def _arxiv2md_installed() -> bool:
    return importlib.util.find_spec("arxiv2md_beta") is not None


async def _download_pdf_from_url(url: str, dest_dir: Path) -> Path:
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("下载 PDF 需要 httpx：pip install httpx") from e

    parsed = urlparse(url)
    path_name = Path(parsed.path).name or "downloaded.pdf"
    if "?" in path_name:
        path_name = path_name.split("?")[0]
    if not path_name.lower().endswith(".pdf"):
        path_name = path_name + ".pdf"

    dest_path = dest_dir / path_name

    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
            logger.warning(f"Content-Type 为 {content_type}，可能不是 PDF")
        dest_path.write_bytes(resp.content)

    logger.info(f"已下载 PDF: {dest_path}")
    return dest_path


def main(
    input_value: str = typer.Argument(
        ...,
        metavar="INPUT",
        help="arXiv ID（可逗号分隔或文件）、PDF 路径或 PDF URL",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="输出目录（arXiv 必填；PDF 默认在 PDF 旁建子目录）",
    ),
    source: str = typer.Option("Arxiv", "--source", help="文章来源（会议/期刊）"),
    short: Optional[str] = typer.Option(None, "--short", help="文章简称"),
    parser: str = typer.Option(
        "html",
        "--parser",
        help="arxiv2md 解析：html 或 latex",
    ),
    no_images: bool = typer.Option(False, "--no-images", help="跳过图片"),
    remove_refs: bool = typer.Option(False, "--remove-refs", help="移除参考文献"),
    remove_toc: bool = typer.Option(False, "--remove-toc", help="移除目录"),
    remove_inline_citations: bool = typer.Option(
        False,
        "--remove-inline-citations",
        help="移除行内引用",
    ),
    ask_llm_dir: Optional[str] = typer.Option(
        None,
        "--ask-llm-dir",
        help="ask_llm 项目根（@prompts/），默认自动推断",
    ),
    prompt_file: str = typer.Option(
        "@prompts/tech-paper-trans-compact.md",
        "--prompt-file",
        help="翻译提示模板",
    ),
    format_rules: str = typer.Option(
        "config/markdown-regex-replace.txt",
        "--format-rules",
        help="Markdown 正则格式化规则",
    ),
    threads: int = typer.Option(1, "--threads", "-T", help="arXiv 批量并发数"),
    skip_translation: bool = typer.Option(False, "--skip-translation"),
    skip_formatting: bool = typer.Option(False, "--skip-formatting"),
    skip_prettier: bool = typer.Option(False, "--skip-prettier"),
    skip_cleanup: bool = typer.Option(
        False,
        "--skip-cleanup",
        help="仅 PDF：不整理到输出目录",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="自动确认"),
    no_arxiv_progress: bool = typer.Option(
        False,
        "--no-arxiv-progress",
        help="向 arxiv2md-beta 传入 --no-progress（减少 tqdm，适合 TTY 单篇）",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="DEBUG 日志"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="仅 ERROR"),
) -> None:
    """论文处理流水线。"""
    if verbose and quiet:
        typer.echo("不能同时使用 --verbose 与 --quiet", err=True)
        raise typer.Exit(2)
    if parser not in ("html", "latex"):
        typer.echo("--parser 须为 html 或 latex", err=True)
        raise typer.Exit(2)

    configure_pipeline_logging(verbose=verbose, quiet=quiet)

    input_type = detect_input_type(input_value)
    arxiv2md_cwd = default_arxiv2md_cwd()

    if input_type == "arxiv":
        if not output:
            logger.error("arXiv 模式需要 --output")
            raise typer.Exit(1)
        if not _arxiv2md_installed():
            logger.error("未找到 arxiv2md_beta，请先安装该依赖")
            raise typer.Exit(1)

        arxiv_ids = parse_arxiv_ids(input_value)
        if not arxiv_ids:
            logger.error("未找到有效的 arXiv ID")
            raise typer.Exit(1)

        ask_root = Path(ask_llm_dir).resolve() if ask_llm_dir else get_ask_llm_dir()
        if ask_root is None and not skip_translation:
            logger.error("未找到 ask_llm，请先安装该依赖或传入 --ask-llm-dir")
            raise typer.Exit(1)

        out_dir = Path(output).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        format_rules_path: Optional[Path] = None
        if not skip_formatting:
            for c in (Path.cwd() / format_rules, Path(format_rules)):
                if c.exists():
                    format_rules_path = c
                    break

        arxiv2md_extra = ["--parser", parser, "--source", source]
        if short:
            arxiv2md_extra.extend(["--short", short])
        if no_images:
            arxiv2md_extra.append("--no-images")
        if remove_refs:
            arxiv2md_extra.append("--remove-refs")
        if remove_toc:
            arxiv2md_extra.append("--remove-toc")
        if remove_inline_citations:
            arxiv2md_extra.append("--remove-inline-citations")

        # 并行模式下必须关闭 arxiv2md-beta 的进度条，避免多进程 TUI 冲突
        force_no_arxiv_progress = no_arxiv_progress or threads > 1

        results: list[dict] = []
        if threads == 1:
            for aid in arxiv_ids:
                results.append(
                    process_single_arxiv_paper(
                        arxiv_id=aid,
                        base_output_dir=out_dir,
                        arxiv2md_beta_dir=arxiv2md_cwd,
                        ask_llm_dir=ask_root,
                        prompt_file=prompt_file,
                        format_rules_file=format_rules_path,
                        skip_translation=skip_translation,
                        skip_formatting=skip_formatting,
                        skip_prettier=skip_prettier,
                        quiet=quiet,
                        arxiv2md_extra=arxiv2md_extra,
                        parallel_worker=False,
                        no_arxiv_progress=force_no_arxiv_progress,
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futs = {
                    ex.submit(
                        process_single_arxiv_paper,
                        arxiv_id=aid,
                        base_output_dir=out_dir,
                        arxiv2md_beta_dir=arxiv2md_cwd,
                        ask_llm_dir=ask_root,
                        prompt_file=prompt_file,
                        format_rules_file=format_rules_path,
                        skip_translation=skip_translation,
                        skip_formatting=skip_formatting,
                        skip_prettier=skip_prettier,
                        quiet=True,
                        arxiv2md_extra=arxiv2md_extra,
                        parallel_worker=True,
                        no_arxiv_progress=force_no_arxiv_progress,
                    ): aid
                    for aid in arxiv_ids
                }
                for fut in as_completed(futs):
                    results.append(fut.result())

        ok = [r for r in results if r["success"]]
        logger.info(f"\n成功: {len(ok)}/{len(results)}")
        for r in results:
            if not r["success"]:
                logger.error(f"  ✗ {r['arxiv_id']}: {r.get('error')}")
        if len(ok) < len(results):
            raise typer.Exit(1)

    elif input_type in ("pdf_path", "pdf_url"):
        if not shutil.which("mineru-parse"):
            logger.error("未找到 mineru-parse，请先安装该依赖")
            raise typer.Exit(1)

        ask_root = Path(ask_llm_dir).resolve() if ask_llm_dir else get_ask_llm_dir()
        if ask_root is None and not skip_translation:
            logger.error("未找到 ask_llm，请先安装该依赖或传入 --ask-llm-dir")
            raise typer.Exit(1)

        if input_type == "pdf_url":
            base = Path(output).resolve() if output else Path.cwd()
            download_dir = base.parent if base.suffix.lower() == ".pdf" else base
            download_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = asyncio.run(_download_pdf_from_url(input_value.strip(), download_dir))
        else:
            pdf_path = Path(input_value).resolve()
            if not pdf_path.is_file():
                logger.error(f"PDF 不存在: {pdf_path}")
                raise typer.Exit(1)

        if output:
            base_out = Path(output).resolve()
            base_out = base_out.parent if base_out.suffix.lower() == ".pdf" else base_out
        else:
            base_out = pdf_path.parent

        pdf_out = base_out / build_pdf_output_dir_name(
            pdf_path.stem, source=source, short=short
        )

        format_rules_path: Optional[Path] = None
        if not skip_formatting:
            for c in (Path.cwd() / format_rules, Path(format_rules)):
                if c.exists():
                    format_rules_path = c
                    break

        res = process_single_pdf(
            pdf_path=pdf_path,
            output_dir=pdf_out,
            ask_llm_dir=ask_root,
            prompt_file=prompt_file,
            format_rules_file=format_rules_path,
            skip_translation=skip_translation,
            skip_formatting=skip_formatting,
            skip_prettier=skip_prettier,
            skip_cleanup=skip_cleanup,
            yes=yes,
            quiet=quiet,
        )
        if not res["success"]:
            logger.error(res.get("error", "未知错误"))
            raise typer.Exit(1)
    else:
        logger.error(f"无法识别输入: {input_value}")
        raise typer.Exit(2)


def app() -> None:
    """Console script entrypoint."""
    typer.run(main)

