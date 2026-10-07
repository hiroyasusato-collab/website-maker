"""Zenn の取得のテスト。実際の Web サイトにはつながない。"""

from __future__ import annotations

from datetime import datetime

from src.models import SITE_ZENN
from src.sources import zenn
from tests.conftest import RecordingFetch, load_fixture_json


def test_必要な4項目を取り出す(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("zenn_search.json")], last={"articles": []})
    articles = zenn.collect("Claude Code", since, fetch)

    titles = [a.title for a in articles]
    assert titles == ["Claude Codeの「Claude Mods」とは？", "俺のAIプログラミング手法"]

    first = articles[0]
    assert first.url == "https://zenn.dev/yoshihiko555/articles/ea2db6070058b3"
    assert first.score == 46
    assert first.published_at.isoformat() == "2026-10-05T02:22:57.853000+09:00"
    assert first.site == SITE_ZENN


def test_期間より古い記事は落とす(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("zenn_search.json")], last={"articles": []})
    articles = zenn.collect("Claude Code", since, fetch)
    assert all("期間より古い" not in a.title for a in articles)


def test_pathが無い記事は落とす(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("zenn_search.json")], last={"articles": []})
    articles = zenn.collect("Claude Code", since, fetch)
    assert all("path が無い" not in a.title for a in articles)


def test_新しい順を指定して呼ぶ(since: datetime) -> None:
    """order=latest 以外は無視されるため、必ず latest で呼ぶ。"""
    fetch = RecordingFetch([{"articles": []}])
    zenn.collect("RAG", since, fetch)

    url, params, _ = fetch.calls[0]
    assert url == zenn.SEARCH_URL
    assert params["order"] == "latest"
    assert params["source"] == "articles"
    assert params["q"] == "RAG"
    assert params["page"] == 1


def test_期間より古いページまで来たらページ送りをやめる(since: datetime) -> None:
    old_page = {
        "articles": [
            {
                "title": "古い記事",
                "path": "/x/articles/old",
                "published_at": "2026-09-01T00:00:00.000+09:00",
                "liked_count": 1,
            }
        ]
    }
    fetch = RecordingFetch([old_page], last={"articles": []})
    zenn.collect("AI", since, fetch)
    # 1ページ目で期間外に到達したので、2ページ目は取りに行かない。
    assert len(fetch.calls) == 1


def test_記事が無ければページ送りをやめる(since: datetime) -> None:
    fetch = RecordingFetch([{"articles": []}], last={"articles": []})
    zenn.collect("AI", since, fetch)
    assert len(fetch.calls) == 1


def test_ページ上限を超えて取りに行かない(since: datetime) -> None:
    """毎ページ新しい記事だけが返り続けても、MAX_PAGES で打ち切る。"""
    page = {
        "articles": [
            {
                "title": "新しい記事",
                "path": "/x/articles/new",
                "published_at": "2026-10-06T00:00:00.000+09:00",
                "liked_count": 1,
            }
        ]
    }
    fetch = RecordingFetch([], last=page)
    zenn.collect("AI", since, fetch)
    assert len(fetch.calls) == zenn.MAX_PAGES


def test_応答が空でも落ちない(since: datetime) -> None:
    assert zenn.collect("AI", since, RecordingFetch([None], last=None)) == []
    assert zenn.collect("AI", since, RecordingFetch([{}], last={})) == []
