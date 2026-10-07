"""Hacker News の取得のテスト。実際の Web サイトにはつながない。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pytest

from src.models import SITE_HACKER_NEWS
from src.sources import hackernews
from tests.conftest import RecordingFetch, load_fixture_json

EMPTY: dict[str, Any] = {"hits": []}


def test_必要な4項目を取り出す(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("hn_search.json")], last=EMPTY)
    articles = hackernews.collect(since, fetch)

    first = articles[0]
    assert first.title == "Mistral Large 4"
    assert first.url == "https://mistral.ai/news/mistral-large-4"
    assert first.score == 1565
    assert first.site == SITE_HACKER_NEWS
    # created_at_i = 1791299749 は日本時間 2026-10-06 22:15:49
    assert first.published_at.isoformat() == "2026-10-06T22:15:49+09:00"


def test_URLが空ならHNの投稿ページを指す(since: datetime) -> None:
    """Ask HN / Tell HN は外部 URL を持たない。"""
    fetch = RecordingFetch([load_fixture_json("hn_search.json")], last=EMPTY)
    articles = hackernews.collect(since, fetch)
    ask = next(a for a in articles if a.title.startswith("Ask HN"))
    assert ask.url == "https://news.ycombinator.com/item?id=49984025"


def test_期間より古い投稿は落とす(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("hn_search.json")], last=EMPTY)
    articles = hackernews.collect(since, fetch)
    assert all("期間より古い" not in a.title for a in articles)


def test_ポイント順の検索条件で呼ぶ(since: datetime) -> None:
    """search_by_date（新着順）ではなく search（ポイント順）を使う。"""
    fetch = RecordingFetch([EMPTY])
    hackernews.collect(since, fetch)

    url, params, _ = fetch.calls[0]
    assert url == hackernews.SEARCH_URL
    assert "search_by_date" not in url
    assert params["tags"] == "story"
    # since ちょうどの投稿も含めたいので >= を使う。
    assert params["numericFilters"] == f"created_at_i>={int(since.timestamp())}"
    assert params["hitsPerPage"] == hackernews.HITS_PER_PAGE
    # Algolia の page は 0 から始まる。
    assert params["page"] == 0


def test_1ページに満たなければページ送りをやめる(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("hn_search.json")], last=EMPTY)
    hackernews.collect(since, fetch)
    assert len(fetch.calls) == 1


def test_ページ上限を超えて取りに行かない(since: datetime) -> None:
    full = {
        "hits": [
            {
                "objectID": str(i),
                "title": f"story {i}",
                "url": f"https://example.com/{i}",
                "points": 10,
                "created_at_i": 1791299749,
            }
            for i in range(hackernews.HITS_PER_PAGE)
        ]
    }
    fetch = RecordingFetch([], last=full)
    hackernews.collect(since, fetch)
    assert len(fetch.calls) == hackernews.MAX_PAGES
    pages = [params["page"] for _, params, _ in fetch.calls]
    assert pages == list(range(hackernews.MAX_PAGES))


def test_ほしい投稿が必要数そろえばページ送りをやめる(since: datetime) -> None:
    """HN は全ジャンルが混ざるので、AI 投稿が10件そろうまで進める。"""

    def page_of(prefix: str, offset: int) -> dict[str, Any]:
        return {
            "hits": [
                {
                    "objectID": str(offset + i),
                    "title": f"{prefix} {offset + i}",
                    "url": f"https://example.com/{offset + i}",
                    "points": 100 - i,
                    "created_at_i": 1791292549,
                }
                for i in range(hackernews.HITS_PER_PAGE)
            ]
        }

    # 1ページ目は AI 以外ばかり、2ページ目に AI が並ぶ。
    fetch = RecordingFetch([page_of("cooking", 0), page_of("AI model", 1000)], last=EMPTY)
    hackernews.collect(since, fetch, is_wanted=lambda t: "AI" in t, needed=10)

    # 2ページ目で10件そろうので、3ページ目には行かない。
    assert len(fetch.calls) == 2


def test_重複や期間外を数に入れずページ送りを続ける(since: datetime) -> None:
    """載せられない投稿を数えてしまうと、10件そろう前にページ送りが止まる。"""

    def page(tag: str, same_url: bool) -> dict[str, Any]:
        hits = []
        for i in range(hackernews.HITS_PER_PAGE):
            is_ai = i < 10
            hits.append(
                {
                    "objectID": f"{tag}-{i}",
                    "title": "AI model" if is_ai else "cooking recipes",
                    # 1ページ目の AI 投稿は全部同じ記事を指している（重複）。
                    "url": (
                        "https://example.com/same"
                        if (is_ai and same_url)
                        else f"https://example.com/{tag}-{i}"
                    ),
                    "points": 100 - i,
                    "created_at_i": 1791292549,
                }
            )
        return {"hits": hits}

    fetch = RecordingFetch(
        [page("p1", same_url=True), page("p2", same_url=False)],
        last=EMPTY,
    )
    articles = hackernews.collect(since, fetch, is_wanted=lambda t: "AI" in t, needed=10)

    # 1ページ目の AI 投稿は重複で1件しか残らないので、2ページ目まで進むこと。
    assert len(fetch.calls) == 2
    ai_articles = [a for a in articles if "AI" in a.title]
    assert len(ai_articles) >= 10


def test_期間の上限を超える投稿は落とす(since: datetime) -> None:
    """未来日の投稿を数に入れてしまうとページ送りが早く止まる。"""
    from src.timeutil import JST

    until = datetime(2026, 10, 8, 0, 0, tzinfo=JST)
    payload = {
        "hits": [
            {
                "objectID": "1",
                "title": "AI の未来の投稿",
                "url": "https://example.com/future",
                "points": 999,
                "created_at_i": int(datetime(2026, 12, 1, tzinfo=JST).timestamp()),
            },
            {
                "objectID": "2",
                "title": "AI の期間内の投稿",
                "url": "https://example.com/ok",
                "points": 10,
                "created_at_i": 1791292549,
            },
        ]
    }
    fetch = RecordingFetch([payload], last=EMPTY)
    articles = hackernews.collect(since, fetch, until=until)
    assert [a.title for a in articles] == ["AI の期間内の投稿"]


def test_読めないURLの投稿は落とす(since: datetime) -> None:
    payload = {
        "hits": [
            {
                "objectID": "1",
                "title": "壊れたURL",
                "url": "https://[broken",
                "points": 999,
                "created_at_i": 1791292549,
            },
            {
                "objectID": "2",
                "title": "ふつうの投稿",
                "url": "https://example.com/ok",
                "points": 10,
                "created_at_i": 1791292549,
            },
        ]
    }
    fetch = RecordingFetch([payload], last=EMPTY)
    articles = hackernews.collect(since, fetch)
    assert [a.title for a in articles] == ["ふつうの投稿"]


def test_同じURLの投稿はここでは落とさない(since: datetime) -> None:
    """重複の除去は呼び出し側にまとめる。

    AI 判定より前に URL で間引くと、同じ URL を指す「AI でない投稿 → AI の投稿」の順で
    返ってきたとき、先の投稿が後の AI 投稿を消し、そのあと AI 判定で先の投稿も消えて
    0件になってしまう。
    """
    payload = {
        "hits": [
            {
                "objectID": "1",
                "title": "New breakthrough",  # AI 語を含まない
                "url": "https://example.com/same",
                "points": 100,
                "created_at_i": 1791292549,
            },
            {
                "objectID": "2",
                "title": "AI model breakthrough",  # 同じ URL だが AI 語を含む
                "url": "https://example.com/same",
                "points": 99,
                "created_at_i": 1791292549,
            },
        ]
    }
    fetch = RecordingFetch([payload], last=EMPTY)
    articles = hackernews.collect(since, fetch, is_wanted=lambda t: "AI" in t, needed=10)

    # 両方残す（絞り込みと重複除去は呼び出し側の仕事）。
    assert [a.title for a in articles] == ["New breakthrough", "AI model breakthrough"]

    # 呼び出し側の処理を通すと、AI の投稿が1件残る。
    from src.aggregate import pick_top
    from src.trend_filter import filter_ai_related

    shown = pick_top(filter_ai_related(articles, ["AI"]), set())
    assert [a.title for a in shown] == ["AI model breakthrough"]


def test_同じURLのほしい投稿は1件として数える(since: datetime) -> None:
    """同じ記事を指す投稿を2件と数えると、10件そろう前にページ送りが止まる。"""

    def page(tag: str) -> dict[str, Any]:
        return {
            "hits": [
                {
                    "objectID": f"{tag}-{i}",
                    "title": "AI model",
                    # 1ページ目は全部同じ記事を指す。
                    "url": (
                        "https://example.com/same"
                        if tag == "p1"
                        else f"https://example.com/{tag}-{i}"
                    ),
                    "points": 100 - i,
                    "created_at_i": 1791292549,
                }
                for i in range(hackernews.HITS_PER_PAGE)
            ]
        }

    fetch = RecordingFetch([page("p1"), page("p2")], last=EMPTY)
    hackernews.collect(since, fetch, is_wanted=lambda t: "AI" in t, needed=10)
    # 1ページ目は実質1件しか載せられないので、2ページ目まで進む。
    assert len(fetch.calls) == 2


def test_ほしい投稿がそろわなければ上限まで進める(
    since: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    full: dict[str, Any] = {
        "hits": [
            {
                "objectID": f"{p}-{i}",
                "title": "cooking recipes",
                "url": f"https://example.com/{p}-{i}",
                "points": 10,
                "created_at_i": 1791292549,
            }
            for p in range(hackernews.MAX_PAGES)
            for i in range(hackernews.HITS_PER_PAGE)
        ]
    }
    fetch = RecordingFetch([], last=full)
    with caplog.at_level(logging.WARNING):
        hackernews.collect(since, fetch, is_wanted=lambda t: "AI" in t, needed=10)

    assert len(fetch.calls) == hackernews.MAX_PAGES
    assert "件しか見つかりませんでした" in caplog.text


def test_同じ投稿が重なっても1件にする(since: datetime) -> None:
    page = {
        "hits": [
            {
                "objectID": "1",
                "title": "same story",
                "url": "https://example.com/1",
                "points": 10,
                "created_at_i": 1791299749,
            }
        ]
    }
    fetch = RecordingFetch([page, page], last=EMPTY)
    assert len(hackernews.collect(since, fetch)) == 1


def test_AI判定はここでは行わない(since: datetime) -> None:
    """ここは候補集めだけ。AI でないタイトルも含めて返す。"""
    fetch = RecordingFetch([load_fixture_json("hn_search.json")], last=EMPTY)
    articles = hackernews.collect(since, fetch)
    assert any("Ghostty" in a.title for a in articles)


def test_応答が空でも落ちない(since: datetime) -> None:
    assert hackernews.collect(since, RecordingFetch([None], last=None)) == []
    assert hackernews.collect(since, RecordingFetch([{}], last={})) == []
