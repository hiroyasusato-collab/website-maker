"""取得の共通処理のテスト。

requests は差し替えるので、ここでも実際の Web サイトにはつながない。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.fetcher import MAX_RETRIES, FetchError, HttpFetcher


class FakeResponse:
    def __init__(self, payload: Any = None, text: str = "", error: Exception | None = None) -> None:
        self._payload = payload
        self.text = text
        self._error = error

    def raise_for_status(self) -> None:
        if self._error:
            raise self._error

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """requests.Session のふり。responses に並べたものを順に返す。"""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        item = self._responses.pop(0) if self._responses else FakeResponse({})
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """テストを待たせないため、待ち時間を無くす。"""
    monkeypatch.setattr("src.fetcher.time.sleep", lambda _seconds: None)


def _fetcher(responses: list[Any]) -> tuple[HttpFetcher, FakeSession]:
    session = FakeSession(responses)
    return HttpFetcher(session=session), session


def test_JSONを取れる() -> None:
    fetcher, _ = _fetcher([FakeResponse(payload={"ok": True})])
    assert fetcher.json("https://example.com") == {"ok": True}


def test_文字列を取れる() -> None:
    fetcher, _ = _fetcher([FakeResponse(text="<rss/>")])
    assert fetcher.text("https://example.com") == "<rss/>"


def test_名乗りを付ける() -> None:
    fetcher, session = _fetcher([FakeResponse(payload={})])
    fetcher.json("https://example.com")
    assert "website-maker" in session.headers["User-Agent"]


def test_タイムアウトを指定する() -> None:
    fetcher, session = _fetcher([FakeResponse(payload={})])
    fetcher.json("https://example.com")
    assert session.calls[0]["timeout"] > 0


def test_パラメータとヘッダを渡す() -> None:
    fetcher, session = _fetcher([FakeResponse(payload={})])
    fetcher.json("https://example.com", params={"q": "AI"}, headers={"Authorization": "Bearer x"})

    call = session.calls[0]
    assert call["params"] == {"q": "AI"}
    assert call["headers"] == {"Authorization": "Bearer x"}


def test_失敗したらやり直す() -> None:
    fetcher, session = _fetcher(
        [RuntimeError("1回目失敗"), RuntimeError("2回目失敗"), FakeResponse(payload={"ok": 1})]
    )
    assert fetcher.json("https://example.com") == {"ok": 1}
    assert len(session.calls) == 3


def test_やり直しの上限を超えたら分かるエラーにする() -> None:
    fetcher, session = _fetcher([RuntimeError("失敗")] * (MAX_RETRIES + 1))
    with pytest.raises(FetchError, match="取得に失敗"):
        fetcher.json("https://example.com")
    assert len(session.calls) == MAX_RETRIES + 1


def test_HTTPエラーもやり直しの対象になる() -> None:
    fetcher, session = _fetcher(
        [FakeResponse(error=RuntimeError("500")), FakeResponse(payload={"ok": 1})]
    )
    assert fetcher.json("https://example.com") == {"ok": 1}
    assert len(session.calls) == 2


def test_JSONでない応答は分かるエラーにする() -> None:
    fetcher, _ = _fetcher([FakeResponse(payload=ValueError("JSON ではない"))])
    with pytest.raises(FetchError, match="JSON ではありません"):
        fetcher.json("https://example.com")


def test_連続アクセスの間に待ちを入れる(monkeypatch: pytest.MonkeyPatch) -> None:
    waited: list[float] = []
    monkeypatch.setattr("src.fetcher.time.sleep", lambda seconds: waited.append(seconds))

    fetcher, _ = _fetcher([FakeResponse(payload={}), FakeResponse(payload={})])
    fetcher.json("https://example.com/1")
    assert waited == [], "1回目は待たない"

    fetcher.json("https://example.com/2")
    assert waited, "2回目以降は待つ"
