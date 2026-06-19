"""translation_cache 模块测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_pipeline.translation_cache import (  # noqa: E402
    TranslationCache,
    _cache_key,
    get_cached_translation,
)


def test_cache_key_stable() -> None:
    k1 = _cache_key("hello", "prompt", "default")
    k2 = _cache_key("hello", "prompt", "default")
    assert k1 == k2
    assert len(k1) == 64  # sha-256 hex


def test_cache_key_salt_sensitive() -> None:
    k1 = _cache_key("hello", "prompt", "salt-a")
    k2 = _cache_key("hello", "prompt", "salt-b")
    assert k1 != k2


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = TranslationCache(tmp_path)
    assert cache.get("source", "prompt", "salt") is None
    cache.set("source", "prompt", "salt", "translated")
    assert cache.get("source", "prompt", "salt") == "translated"


def test_cache_clear(tmp_path: Path) -> None:
    cache = TranslationCache(tmp_path)
    cache.set("a", "p", "s", "t")
    cache.set("b", "p", "s", "t")
    removed = cache.clear()
    assert removed == 2
    assert cache.get("a", "p", "s") is None


def test_get_cached_translation_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    get_cached_translation("src", "prompt", "salt")
    # 主要验证不抛异常；helper 使用默认缓存目录
