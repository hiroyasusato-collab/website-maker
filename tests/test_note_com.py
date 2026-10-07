"""note の取得のテスト。実際の Web サイトにはつながない。"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from src.models import SITE_NOTE
from src.sources import note_com
from tests.conftest import RecordingFetch, load_fixture_json

EMPTY: dict[str, Any] = {"data": {"notes": {"contents": []}}}


def test_必要な4項目を取り出す(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("note_searches.json")], last=EMPTY)
    articles = note_com.collect("Claude", since, fetch)

    titles = [a.title for a in articles]
    assert titles == ["Claude Code超入門", "ChatGPTとClaudeからSlack経由でdotsに頼む"]

    first = articles[0]
    # URL は https://note.com/<ユーザー名>/n/<記事キー> の形に組み立てる。
    assert first.url == "https://note.com/hoshimama3/n/n599ef409bf2c"
    assert first.score == 47
    assert first.published_at.isoformat() == "2026-10-05T18:00:00+09:00"
    assert first.site == SITE_NOTE


def test_期間より古い記事は落とす(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_json("note_searches.json")], last=EMPTY)
    articles = note_com.collect("Claude", since, fetch)
    assert all("期間より古い" not in a.title for a in articles)


def test_ユーザー名が無い記事は落とす(since: datetime) -> None:
    """URL を組み立てられない記事はページに出せないので落とす。"""
    fetch = RecordingFetch([load_fixture_json("note_searches.json")], last=EMPTY)
    articles = note_com.collect("Claude", since, fetch)
    assert all("ユーザー名が無い" not in a.title for a in articles)


def test_sortはhotで呼ぶ(since: datetime) -> None:
    """sort=new はキーワードを無視するため、必ず hot で呼ぶ。"""
    fetch = RecordingFetch([EMPTY])
    note_com.collect("RAG", since, fetch)

    url, params, _ = fetch.calls[0]
    assert url == note_com.SEARCH_URL
    assert params["sort"] == "hot"
    assert params["context"] == "note"
    assert params["q"] == "RAG"
    assert params["size"] == note_com.PAGE_SIZE
    assert params["start"] == 0


def test_startでページ送りする(since: datetime) -> None:
    page = load_fixture_json("note_searches.json")
    fetch = RecordingFetch([], last=page)
    note_com.collect("AI", since, fetch)

    starts = [params["start"] for _, params, _ in fetch.calls]
    assert starts == [i * note_com.PAGE_SIZE for i in range(note_com.MAX_PAGES)]


def test_別ページで同じ記事が返っても1件にする(since: datetime) -> None:
    """sort=hot は同じ記事を別ページで返すことがある。"""
    page = load_fixture_json("note_searches.json")
    # 毎ページ同じ中身を返す。
    fetch = RecordingFetch([], last=copy.deepcopy(page))
    articles = note_com.collect("Claude", since, fetch)
    assert len(articles) == 2


def test_記事が無ければページ送りをやめる(since: datetime) -> None:
    fetch = RecordingFetch([EMPTY], last=EMPTY)
    note_com.collect("AI", since, fetch)
    assert len(fetch.calls) == 1


def test_キーワードを含まない記事は落とす(since: datetime) -> None:
    """note の検索はゆるく、無関係な記事を多く返す。実際に返ってきたタイトルで確かめる。"""
    payload = {
        "data": {
            "notes": {
                "contents": [
                    {
                        "name": title,
                        "key": f"n{i:012d}",
                        "publish_at": "2026-10-05T12:00:00.000+09:00",
                        "like_count": 999,
                        "user": {"urlname": "someone"},
                    }
                    for i, title in enumerate(
                        [
                            "いろはかるた大喜利『ゑ』＆きのころサークル無料見学会のご案内",
                            "🌶️麻婆菜館 四川風焼きそば ある日の夕飯メニュー",
                            "Day⑦｜金木犀Fragrant Olive",  # "F(rag)rant" の部分一致
                            "ラジオに熱中した「人生の夏休み」",
                            "RAG の構成を見直した話",  # これだけ残るべき
                        ]
                    )
                ]
            }
        }
    }
    fetch = RecordingFetch([payload], last=EMPTY)
    articles = note_com.collect("RAG", since, fetch)

    assert [a.title for a in articles] == ["RAG の構成を見直した話"]


def test_日本語キーワードは部分一致で残す(since: datetime) -> None:
    payload = {
        "data": {
            "notes": {
                "contents": [
                    {
                        "name": "AI駆動開発により新しいV字モデルが生まれた",
                        "key": "n000000000001",
                        "publish_at": "2026-10-05T12:00:00.000+09:00",
                        "like_count": 20,
                        "user": {"urlname": "someone"},
                    },
                    {
                        "name": "まったく関係のない日記",
                        "key": "n000000000002",
                        "publish_at": "2026-10-05T12:00:00.000+09:00",
                        "like_count": 500,
                        "user": {"urlname": "someone"},
                    },
                ]
            }
        }
    }
    fetch = RecordingFetch([payload], last=EMPTY)
    articles = note_com.collect("AI駆動開発", since, fetch)
    assert [a.title for a in articles] == ["AI駆動開発により新しいV字モデルが生まれた"]


def test_応答の形が崩れていても落ちない(since: datetime) -> None:
    broken_payloads: tuple[Any, ...] = (
        None,
        {},
        {"data": None},
        {"data": {"notes": None}},
        {"data": {"notes": {}}},
    )
    for broken in broken_payloads:
        assert note_com.collect("AI", since, RecordingFetch([broken], last=broken)) == []
