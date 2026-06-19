"""arXiv 流水线：arxiv2md-beta → 格式化 → 翻译。

同步入口保持向后兼容，核心逻辑已迁移到异步实现，以支持：

- 单篇论文内部的格式化/翻译并行化
- 跨论文的 asyncio 批量并发
- 基于内容哈希的翻译缓存
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from loguru import logger

from paper_pipeline.formatting import (
    MARKDOWN_FORMATTER_AVAILABLE,
    async_format_markdown_file,
    async_format_with_prettier,
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
from paper_pipeline.translation_cache import TranslationCache
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


def _read_prompt_text(prompt_file: str, ask_llm_dir: Path | None) -> str:
    """读取 prompt 文件内容；失败时回退为 prompt_file 字符串本身。"""
    if not prompt_file:
        return ""

    # 支持 @prompts/... 项目相对路径
    candidates: list[Path] = []
    if prompt_file.startswith("@") and ask_llm_dir is not None:
        candidates.append(ask_llm_dir / prompt_file[1:])
    candidates.append(Path(prompt_file))

    for p in candidates:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except OSError:
            continue
    return prompt_file


async def async_translate_md(
    md_path: Path,
    ask_llm_dir: Path | None,
    prompt_file: str,
    *,
    quiet: bool,
    use_tty: bool,
    no_stream_api: bool = True,
    cache: TranslationCache | None = None,
    cache_salt: str = "default",
) -> Path | None:
    """调用 ask-llm trans，直接生成 *_trans.md（异步、可缓存、可选非流式）。"""
    cwd: Path | None = ask_llm_dir or get_ask_llm_dir()
    if cwd is None:
        return None

    expected = md_path.parent / f"{md_path.stem}_trans.md"

    # 尝试缓存命中
    if cache is not None and expected.exists():
        try:
            source_text = md_path.read_text(encoding="utf-8")
            prompt_text = _read_prompt_text(prompt_file, cwd)
            cached = cache.get(source_text, prompt_text, cache_salt)
            if cached is not None:
                expected.write_text(cached, encoding="utf-8")
                logger.info(f"翻译缓存命中: {expected.name}")
                return expected
        except OSError:
            pass

    cmd: list[str] = [
        "ask-llm",
        "trans",
        str(md_path),
        "-o",
        str(md_path.parent),
        "-p",
        prompt_file,
        "-f",
        "--translated-suffix",
        "_trans",
    ]
    # 批量/非 TTY 模式下关闭流式进度，避免多进程冲突
    if not use_tty:
        cmd.append("--stream")
    # 若 ask_llm 支持非流式 API，则优先使用（更快的批量吞吐）
    if no_stream_api:
        cmd.append("--no-stream-api")

    rc = await asyncio.to_thread(
        run_external_command,
        cmd,
        cwd=cwd,
        quiet=quiet,
        inherit_stdio=False,
        log_component=None if quiet else "ask-llm",
    )
    if rc.returncode != 0:
        return None

    # 写入缓存
    if cache is not None and expected.exists():
        try:
            source_text = md_path.read_text(encoding="utf-8")
            prompt_text = _read_prompt_text(prompt_file, cwd)
            translated_text = expected.read_text(encoding="utf-8")
            cache.set(source_text, prompt_text, cache_salt, translated_text)
        except OSError:
            pass

    return expected if expected.exists() else None


def translate_md(
    md_path: Path,
    ask_llm_dir: Path | None,
    prompt_file: str,
    *,
    quiet: bool,
    use_tty: bool,
) -> Path | None:
    """同步包装 :func:`async_translate_md`，保持向后兼容。"""
    return asyncio.run(
        async_translate_md(
            md_path,
            ask_llm_dir,
            prompt_file,
            quiet=quiet,
            use_tty=use_tty,
        )
    )


async def _format_md_pair(
    md_path: Path,
    format_rules_file: Path | None,
    skip_formatting: bool,
    skip_prettier: bool,
    log_prefix: str,
    arxiv_id: str,
) -> None:
    """格式化单个 Markdown：regex formatter 与 prettier 并行执行。"""
    tasks: list[asyncio.Task[bool]] = []

    if (
        not skip_formatting
        and format_rules_file
        and MARKDOWN_FORMATTER_AVAILABLE
    ):
        logger.info(f"[{arxiv_id}] {log_prefix}: regex 格式化")
        tasks.append(
            asyncio.create_task(
                async_format_markdown_file(md_path, format_rules_file)
            )
        )
    if not skip_prettier:
        logger.info(f"[{arxiv_id}] {log_prefix}: Prettier 格式化")
        tasks.append(asyncio.create_task(async_format_with_prettier(md_path)))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def async_process_single_arxiv_paper(
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
    no_stream_api: bool = True,
    cache: TranslationCache | None = None,
    cache_salt: str = "default",
) -> dict:
    """
    处理单篇 arXiv 论文（异步核心实现）。

    并行化策略：
    - arxiv2md-beta 运行期间不做其他事（必须等待输出目录）。
    - arxiv2md-beta 完成后：原文的 regex formatter 与 prettier 并行。
    - 翻译正文与「附录格式化」并行。
    - 翻译附录与「正文译文格式化」并行。
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
        if "--naming-scheme" not in extra:
            extra.extend(["--naming-scheme", "paper-pipeline"])
        if no_arxiv_progress and "--no-progress" not in extra:
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

        r = await asyncio.to_thread(
            run_external_command,
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

        # 新命名方案下，arxiv2md-beta 固定输出 paper.md / Appendix.md / References.md
        md_file = output_dir / "paper.md"
        if not md_file.is_file():
            # 兼容旧命名或非常规输出的兜底查找
            md_files = [
                f
                for f in output_dir.glob("*.md")
                if not f.name.endswith("_trans.md")
                and not f.name.endswith("_translated.md")
                and not f.name.endswith("-References.md")
                and not f.name.endswith("-Appendix.md")
            ]
            if not md_files:
                raise RuntimeError("未找到 Markdown 文件")
            md_file = (
                md_files[0]
                if len(md_files) == 1
                else max(md_files, key=lambda p: p.stat().st_mtime)
            )
            if " " in md_file.name:
                new_path = md_file.parent / md_file.name.replace(" ", "-")
                md_file.rename(new_path)
                md_file = new_path

        # 步骤 2：格式化原文（regex + prettier 并行）
        await _format_md_pair(
            md_file,
            format_rules_file,
            skip_formatting,
            skip_prettier,
            "步骤 2: 格式化原始 Markdown",
            arxiv_id,
        )

        # arxiv2md-beta：Appendix.md 与正文分开；仅格式化附录源文件，不翻译 References.md
        appendix_md = md_file.parent / "Appendix.md"

        trans_file: Path | None = None
        if not skip_translation:
            logger.info(
                f"[{arxiv_id}] 步骤 3: 翻译正文 Markdown"
                + "（标题、作者、ArXiv 等元数据一同交给 ask-llm trans 翻译）"
            )

            # 正文翻译 与 附录格式化 可并行
            body_trans_task = asyncio.create_task(
                async_translate_md(
                    md_file,
                    ask_llm_dir,
                    prompt_file,
                    quiet=parallel_worker or quiet,
                    use_tty=use_tty,
                    no_stream_api=no_stream_api,
                    cache=cache,
                    cache_salt=cache_salt,
                )
            )
            appendix_format_task: asyncio.Task[None] | None = None
            if appendix_md.is_file():
                appendix_format_task = asyncio.create_task(
                    _format_md_pair(
                        appendix_md,
                        format_rules_file,
                        skip_formatting,
                        skip_prettier,
                        "步骤 2c/2d: 格式化附录 Markdown",
                        arxiv_id,
                    )
                )

            trans_file = await body_trans_task
            if appendix_format_task is not None:
                await appendix_format_task

            if trans_file:
                # 正文译文格式化（regex + prettier 并行）
                format_trans_task = asyncio.create_task(
                    _format_md_pair(
                        trans_file,
                        format_rules_file,
                        skip_formatting,
                        skip_prettier,
                        "步骤 4: 格式化翻译后的正文",
                        arxiv_id,
                    )
                )

                # 附录翻译 与 正文译文格式化 并行
                trans_appendix: Path | None = None
                if appendix_md.is_file():
                    logger.info(f"[{arxiv_id}] 步骤 3b: 翻译附录 Markdown")
                    trans_appendix = await async_translate_md(
                        appendix_md,
                        ask_llm_dir,
                        prompt_file,
                        quiet=parallel_worker or quiet,
                        use_tty=use_tty,
                        no_stream_api=no_stream_api,
                        cache=cache,
                        cache_salt=cache_salt,
                    )

                await format_trans_task

                if trans_appendix:
                    await _format_md_pair(
                        trans_appendix,
                        format_rules_file,
                        skip_formatting,
                        skip_prettier,
                        "步骤 4b: 格式化翻译后的附录",
                        arxiv_id,
                    )

        result["success"] = True
        logger.info(f"[{arxiv_id}] ✓ 处理完成: {output_dir}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[{arxiv_id}] ✗ 处理失败: {e}")

    return result


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
    """同步包装 :func:`async_process_single_arxiv_paper`，保持向后兼容。"""
    return asyncio.run(
        async_process_single_arxiv_paper(
            arxiv_id=arxiv_id,
            base_output_dir=base_output_dir,
            arxiv2md_beta_dir=arxiv2md_beta_dir,
            ask_llm_dir=ask_llm_dir,
            prompt_file=prompt_file,
            format_rules_file=format_rules_file,
            skip_translation=skip_translation,
            skip_formatting=skip_formatting,
            skip_prettier=skip_prettier,
            quiet=quiet,
            arxiv2md_extra=arxiv2md_extra,
            parallel_worker=parallel_worker,
            no_arxiv_progress=no_arxiv_progress,
        )
    )


def default_arxiv2md_cwd() -> Path | None:
    root = repo_root_from_pipeline()
    candidate = root / "academic" / "arxiv2md-beta"
    if candidate.exists():
        return candidate
    return None
