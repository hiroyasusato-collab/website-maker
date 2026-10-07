"""ページ送りの上限に達したとき、取りこぼしを知らせることのテスト。

実際に起きた問題：Qiita の上限を3ページ（300件）にしていたとき、
「Claude」で7日間に400件以上あり、4ページ目にあった26いいねの記事を取りこぼしていた。
黙って取りこぼすと気づけないので、警告を出すようにした。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pytest

from src.sources import note_com, qiita, zenn
from tests.conftest import RecordingFetch


def _zenn_page(count: int, published: str) -> dict[str, Any]:
    return {
        "articles": [
            {
                "title": f"記事{i}",
                "path": f"/u/articles/{published}-{i}",
                "published_at": published,
                "liked_count": i,
            }
            for i in range(count)
        ]
    }


def _qiita_page(count: int, created: str) -> list[dict[str, Any]]:
    return [
        {
            "title": f"記事{i}",
            "url": f"https://qiita.com/u/items/{created}-{i:020d}",
            "likes_count": i,
            "created_at": created,
        }
        for i in range(count)
    ]


def _note_page(count: int, published: str, offset: int = 0) -> dict[str, Any]:
    return {
        "data": {
            "notes": {
                "contents": [
                    {
                        "name": f"記事{offset + i}",
                        "key": f"n{offset + i:012d}",
                        "publish_at": published,
                        "like_count": i,
                        "user": {"urlname": "someone"},
                    }
                    for i in range(count)
                ]
            }
        }
    }


# ---------- 上限に達したら警告する ----------


def test_Qiitaが上限に達したら警告する(since: datetime, caplog: pytest.LogCaptureFixture) -> None:
    # 毎ページ満杯＝まだ続きがある状態。
    fetch = RecordingFetch([], last=_qiita_page(qiita.PER_PAGE, "2026-10-05T00:00:00+09:00"))
    with caplog.at_level(logging.WARNING):
        qiita.collect("Claude", since, fetch)

    assert len(fetch.calls) == qiita.MAX_PAGES
    assert "見落としている可能性" in caplog.text


def test_Qiitaが自然に終わったら警告しない(
    since: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    # 1ページ分に満たない＝これで全部。
    fetch = RecordingFetch([_qiita_page(5, "2026-10-05T00:00:00+09:00")], last=[])
    with caplog.at_level(logging.WARNING):
        qiita.collect("M365", since, fetch)

    assert caplog.text == ""


def test_Zennが上限に達したら警告する(since: datetime, caplog: pytest.LogCaptureFixture) -> None:
    fetch = RecordingFetch([], last=_zenn_page(48, "2026-10-05T00:00:00.000+09:00"))
    with caplog.at_level(logging.WARNING):
        zenn.collect("Claude", since, fetch)

    assert len(fetch.calls) == zenn.MAX_PAGES
    assert "見落としている可能性" in caplog.text


def test_Zennが期間の端に届いたら警告しない(
    since: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    # 期間より古い記事が出てきた＝さかのぼり切った。
    fetch = RecordingFetch(
        [_zenn_page(48, "2026-09-20T00:00:00.000+09:00")],
        last={"articles": []},
    )
    with caplog.at_level(logging.WARNING):
        zenn.collect("M365", since, fetch)

    assert caplog.text == ""


def test_noteが上限に達したら知らせる(since: datetime, caplog: pytest.LogCaptureFixture) -> None:
    # 毎ページ別の記事を返し続ける（重複除去で早く終わらないように）。
    pages = [
        _note_page(note_com.PAGE_SIZE, "2026-10-05T00:00:00.000+09:00", offset=p * 100)
        for p in range(note_com.MAX_PAGES)
    ]
    fetch = RecordingFetch(pages, last={"data": {"notes": {"contents": []}}})
    with caplog.at_level(logging.INFO):
        note_com.collect("Claude", since, fetch)

    assert len(fetch.calls) == note_com.MAX_PAGES
    assert "上限まで取得しました" in caplog.text


def test_noteが自然に終わったら知らせない(
    since: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    empty: dict[str, Any] = {"data": {"notes": {"contents": []}}}
    fetch = RecordingFetch(
        [_note_page(5, "2026-10-05T00:00:00.000+09:00"), empty],
        last=empty,
    )
    with caplog.at_level(logging.INFO):
        note_com.collect("M365", since, fetch)

    assert "上限まで取得しました" not in caplog.text


# ---------- Qiita のアクセス回数が上限内に収まること ----------


def test_Qiitaの最大アクセス回数がトークン無しの上限に収まる() -> None:
    """トークン無しの Qiita は1時間60回まで。キーワード6個でも収まること。"""
    keywords = 6
    assert keywords * qiita.MAX_PAGES <= 60
