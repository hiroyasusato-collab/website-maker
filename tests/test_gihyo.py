"""技術評論社（公式 RSS）から記事を取る処理のテスト。実際のサイトにはつながない。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from src.models import SITE_GIHYO
from src.sources import gihyo
from tests.conftest import load_fixture_text


class FeedText:
    """RSS を返す偽の取得関数。呼ばれた URL を記録する。"""

    def __init__(self, body: str | None = None) -> None:
        self.body = body if body is not None else load_fixture_text("gihyo_feed.rss")
        self.calls: list[str] = []

    def __call__(self, url: str, **kwargs: Any) -> str:
        self.calls.append(url)
        return self.body


# ---------- RSS の読み取り ----------


def test_項目を取り出せる() -> None:
    articles = gihyo.parse_rss(load_fixture_text("gihyo_feed.rss"))
    first = articles[0]

    assert first.title == (
        "Google、スマートフォンで動くマルチモーダル埋め込みモデル「EmbeddingGemma 2」を公開"
    )
    assert first.published_at.isoformat() == "2026-10-07T14:39:00+09:00"
    assert first.site == SITE_GIHYO


def test_URLはguidを使う() -> None:
    """link には ?utm_source=feed が付くので、きれいな guid を優先する。"""
    articles = gihyo.parse_rss(load_fixture_text("gihyo_feed.rss"))
    assert articles[0].url == "https://gihyo.jp/article/2026/10/embeddinggemma-2"
    assert all("utm_source" not in a.url for a in articles[:5])


def test_guidが無ければlinkを使う() -> None:
    articles = gihyo.parse_rss(load_fixture_text("gihyo_feed.rss"))
    fallback = next(a for a in articles if "no-guid" in a.url)
    assert fallback.url == "https://gihyo.jp/article/2026/10/no-guid?utm_source=feed"


def test_人気の数字が無いのでスコアは0() -> None:
    """技術評論社にはいいね数にあたる数字が無い。並べ替えは日付で行う。"""
    articles = gihyo.parse_rss(load_fixture_text("gihyo_feed.rss"))
    assert all(a.score == 0 for a in articles)


def test_項目が足りない記事は飛ばす() -> None:
    xml = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel>
      <item><title>日付が無い</title><link>https://gihyo.jp/a</link></item>
      <item><pubDate>Mon, 05 Oct 2026 09:30:00 +0900</pubDate><link>https://gihyo.jp/b</link></item>
      <item><title>そろっている</title><link>https://gihyo.jp/c</link>
        <pubDate>Mon, 05 Oct 2026 09:30:00 +0900</pubDate></item>
    </channel></rss>"""
    assert [a.title for a in gihyo.parse_rss(xml)] == ["そろっている"]


def test_読めない日付の記事は飛ばす() -> None:
    xml = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel>
      <item><title>壊れた日付</title><link>https://gihyo.jp/a</link>
        <pubDate>いつか</pubDate></item>
    </channel></rss>"""
    assert gihyo.parse_rss(xml) == []


# ---------- 取得の失敗（要件5） ----------


def test_RSSでない応答は取得失敗にする() -> None:
    """HTTP 200 で HTML が返っても「記事0件」にせず、失敗として扱う。"""
    with pytest.raises(gihyo.GihyoResponseError):
        gihyo.parse_rss("<html><body>メンテナンス中</body></html>")


def test_XMLとして壊れていても取得失敗にする() -> None:
    with pytest.raises(gihyo.GihyoResponseError):
        gihyo.parse_rss("<rss><channel><item>")


# ---------- 期間の絞り込み ----------


def test_期間より前の記事は落とす(since: datetime) -> None:
    articles = gihyo.collect(since, FeedText())
    titles = [a.title for a in articles]

    assert "生成AIで業務を変える" not in titles, "2026-09-20 の記事は7日より前"
    assert "Anthropic、Claude Sonnet 5.5を発表" in titles


def test_取得は1回だけ(since: datetime) -> None:
    """RSS に1年分以上入っているので、ページ送りは要らない。"""
    fetch = FeedText()
    gihyo.collect(since, fetch)
    assert fetch.calls == [gihyo.FEED_URL]


def test_日付の新しい順に並べ替えるのは呼び出し側(since: datetime) -> None:
    """ここでは RSS の順をそのまま返す（並べ替えは aggregate が行う）。"""
    articles = gihyo.collect(since, FeedText())
    assert articles[0].published_at > articles[1].published_at
