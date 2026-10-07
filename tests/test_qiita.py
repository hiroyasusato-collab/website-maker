"""Qiita の取得のテスト。実際の Web サイトにはつながない。"""

from __future__ import annotations

from datetime import datetime

from src.models import SITE_QIITA
from src.sources import qiita
from tests.conftest import RecordingFetch, load_fixture_json


def test_必要な4項目を取り出す(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("qiita_items.json")], last=[])
    articles = qiita.collect("Claude Code", since, fetch)

    titles = [a.title for a in articles]
    assert titles == [
        "Genie Code CLIでDatabricksを操作してみた",
        "権限で拒否されたフォルダの切り分けメモ",
    ]

    first = articles[0]
    assert first.url == "https://qiita.com/taka_yayoi/items/c6de36677c884dae1300"
    assert first.score == 3
    assert first.published_at.isoformat() == "2026-10-06T09:02:23+09:00"
    assert first.site == SITE_QIITA


def test_期間より古い記事とURLが無い記事は落とす(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("qiita_items.json")], last=[])
    articles = qiita.collect("Claude Code", since, fetch)
    assert all("落ちるべき" not in a.title for a in articles)


def test_検索条件に期間を入れて呼ぶ(since: datetime) -> None:
    """created:>= で期間をサーバー側で絞れるのは Qiita だけなので必ず使う。"""
    fetch = RecordingFetch([[]])
    qiita.collect("RAG", since, fetch)

    url, params, headers = fetch.calls[0]
    assert url == qiita.ITEMS_URL
    assert params["query"] == "RAG created:>=2026-10-01"
    assert params["per_page"] == qiita.PER_PAGE
    assert params["page"] == 1
    # トークン未指定のときは Authorization を付けない。
    assert "Authorization" not in headers


def test_トークンがあればAuthorizationを付ける(since: datetime) -> None:
    fetch = RecordingFetch([[]])
    qiita.collect("RAG", since, fetch, token="dummy-token")
    _, _, headers = fetch.calls[0]
    assert headers["Authorization"] == "Bearer dummy-token"


def test_1ページに満たなければページ送りをやめる(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("qiita_items.json")], last=[])
    qiita.collect("AI", since, fetch)
    # fixture は4件（PER_PAGE=100 未満）なので1回で終わる。
    assert len(fetch.calls) == 1


def test_ページ上限を超えて取りに行かない(since: datetime) -> None:
    full_page = [
        {
            "title": f"記事{i}",
            "url": f"https://qiita.com/u/items/{i:032d}",
            "likes_count": 1,
            "created_at": "2026-10-06T00:00:00+09:00",
        }
        for i in range(qiita.PER_PAGE)
    ]
    fetch = RecordingFetch([], last=full_page)
    qiita.collect("AI", since, fetch)
    assert len(fetch.calls) == qiita.MAX_PAGES


def test_応答が空でも落ちない(since: datetime) -> None:
    assert qiita.collect("AI", since, RecordingFetch([None], last=None)) == []
    assert qiita.collect("AI", since, RecordingFetch([[]], last=[])) == []
