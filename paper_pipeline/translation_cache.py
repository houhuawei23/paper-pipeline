"""按内容哈希缓存 ask-llm 翻译结果，避免重复 API 调用。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional


_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "paper-pipeline-beta" / "translation_cache"


def _default_cache_dir() -> Path:
    base = Path(
        os.environ.get(
            "XDG_CACHE_HOME",
            str(Path.home() / ".cache"),
        )
    )
    return base / "paper-pipeline-beta" / "translation_cache"


def _cache_key(source_text: str, prompt_text: str, model_key: str) -> str:
    """生成稳定的缓存键。

    model_key 建议为 ``provider/model`` 或任何能区分模型/provider 的字符串。
    """
    payload = f"{model_key}\n{prompt_text}\n{source_text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class TranslationCache:
    """磁盘翻译缓存。"""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or _default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # 按前两位分目录，避免单目录文件过多
        return self.cache_dir / key[:2] / f"{key}.md"

    def get(
        self,
        source_text: str,
        prompt_text: str,
        model_key: str,
    ) -> str | None:
        path = self._path(_cache_key(source_text, prompt_text, model_key))
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def set(
        self,
        source_text: str,
        prompt_text: str,
        model_key: str,
        translated_text: str,
    ) -> None:
        path = self._path(_cache_key(source_text, prompt_text, model_key))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(translated_text, encoding="utf-8")

    def clear(self) -> int:
        """清空缓存，返回删除文件数。"""
        removed = 0
        for p in self.cache_dir.rglob("*.md"):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        return removed


# 全局默认实例（线程安全：仅读/写文件）
_default_cache: Optional[TranslationCache] = None


def get_translation_cache(cache_dir: Path | None = None) -> TranslationCache:
    global _default_cache
    if _default_cache is None or cache_dir is not None:
        return TranslationCache(cache_dir)
    return _default_cache


def cache_translation_result(
    source_text: str,
    prompt_text: str,
    model_key: str,
    translated_text: str,
    cache_dir: Path | None = None,
) -> None:
    get_translation_cache(cache_dir).set(source_text, prompt_text, model_key, translated_text)


def get_cached_translation(
    source_text: str,
    prompt_text: str,
    model_key: str,
    cache_dir: Path | None = None,
) -> str | None:
    return get_translation_cache(cache_dir).get(source_text, prompt_text, model_key)
