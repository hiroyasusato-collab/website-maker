"""pytest 共通設定。

リポジトリルートを import パスに加え、`src` を解決可能にする。
あわせて、テストで使う「偽の取得関数」を用意する。
テストは実際の Web サイトに一切つながない（要件8）。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

# tests/ の1つ上（リポジトリルート）を sys.path 先頭へ。`from src...` を確実に解決する。
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.timeutil import JST  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class RecordingFetch:
    """取得関数のふり。何回目にどの応答を返すかを並べて渡す。

    pages に並べた応答を1回ごとに順に返し、足りなくなったら last を返し続ける。
    呼ばれた URL とパラメータは calls に記録するので、
    「正しい並び順の指定で呼んでいるか」もテストできる。
    """

    def __init__(self, pages: list[Any], last: Any = None) -> None:
        self._pages = list(pages)
        self._last = last
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        # 呼び出しごとの retries 指定。X が「やり直さない」ことを確かめるのに使う。
        self.retries: list[int | None] = []

    def __call__(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        retries: int | None = None,
    ) -> Any:
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        self.retries.append(retries)
        if self._pages:
            return self._pages.pop(0)
        return self._last


class FailingFetch:
    """必ず失敗する取得関数のふり。取得元が落ちたときの挙動を試す。"""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error or RuntimeError("接続できません")

    def __call__(self, url: str, **kwargs: Any) -> Any:
        raise self._error


@pytest.fixture
def since() -> datetime:
    """テストで使う期間の開始。fixtures の日付に合わせて 2026-10-01 0:00（日本時間）。"""
    return datetime(2026, 10, 1, 0, 0, 0, tzinfo=JST)


@pytest.fixture
def reference() -> datetime:
    """テストで使う実行日時。2026-10-07 10:00（日本時間）。"""
    return datetime(2026, 10, 7, 10, 0, 0, tzinfo=JST)
