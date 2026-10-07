"""日時の取り扱いのテスト。取得元ごとに形式が違うので、ここを間違えると7日の判定がずれる。"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.timeutil import JST, parse_iso, parse_rfc822, parse_unix, period_end, period_start, to_date


def test_期間の始まりは実行日を含む7日前の0時() -> None:
    reference = datetime(2026, 10, 7, 10, 30, 45, tzinfo=JST)
    start = period_start(reference)

    assert start.isoformat() == "2026-10-01T00:00:00+09:00"
    # 実行日を含めて 10/1〜10/7 の7日間。
    assert (to_date(reference) - to_date(start)).days == 6


@pytest.mark.parametrize("hour", [0, 9, 12, 23])
def test_実行時刻が変わっても期間の始まりは同じ(hour: int) -> None:
    """時刻の端数で結果が揺れないこと。"""
    start = period_start(datetime(2026, 10, 7, hour, 59, tzinfo=JST))
    assert start.isoformat() == "2026-10-01T00:00:00+09:00"


def test_月をまたぐ期間も正しい() -> None:
    start = period_start(datetime(2026, 10, 3, 10, 0, tzinfo=JST))
    assert start.isoformat() == "2026-09-27T00:00:00+09:00"


def test_期間の終わりは実行日の翌日0時() -> None:
    """未来の投稿日を持つ記事（note の予約投稿など）を落とすための上限。"""
    end = period_end(datetime(2026, 10, 7, 23, 59, tzinfo=JST))
    assert end.isoformat() == "2026-10-08T00:00:00+09:00"


def test_期間の長さがちょうど7日になる() -> None:
    reference = datetime(2026, 10, 7, 15, 0, tzinfo=JST)
    assert (period_end(reference) - period_start(reference)).days == 7


def test_月末をまたぐ期間の終わり() -> None:
    end = period_end(datetime(2026, 10, 31, 12, 0, tzinfo=JST))
    assert end.isoformat() == "2026-11-01T00:00:00+09:00"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Zenn
        ("2026-10-05T13:59:07.666+09:00", "2026-10-05T13:59:07.666000+09:00"),
        # Qiita
        ("2026-10-07T09:04:31+09:00", "2026-10-07T09:04:31+09:00"),
        # note
        ("2026-08-22T13:26:20.000+09:00", "2026-08-22T13:26:20+09:00"),
        # はてブ（UTC → 日本時間に直す）
        ("2026-10-06T07:38:26Z", "2026-10-06T16:38:26+09:00"),
        ("2026-10-06T07:38:26z", "2026-10-06T16:38:26+09:00"),
        # 別のタイムゾーン
        ("2026-10-06T00:00:00-05:00", "2026-10-06T14:00:00+09:00"),
    ],
)
def test_各取得元の日時形式を日本時間に直す(raw: str, expected: str) -> None:
    parsed = parse_iso(raw)
    assert parsed is not None
    assert parsed.isoformat() == expected


def test_タイムゾーンが無ければ日本時間として扱う() -> None:
    parsed = parse_iso("2026-10-06T12:00:00")
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-06T12:00:00+09:00"


@pytest.mark.parametrize("raw", ["", "   ", "きのう", "2026/10/06", "not a date"])
def test_読めない日時はNoneを返す(raw: str) -> None:
    assert parse_iso(raw) is None


def test_UNIX秒を日本時間に直す() -> None:
    # 1791292549 = 2026-10-06T13:15:49Z
    parsed = parse_unix(1791292549)
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-06T22:15:49+09:00"


def test_UNIX秒が文字列でも読める() -> None:
    parsed = parse_unix("1791292549")
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-06T22:15:49+09:00"


@pytest.mark.parametrize("raw", [None, "", "abc", [], {}])
def test_読めないUNIX秒はNoneを返す(raw: object) -> None:
    assert parse_unix(raw) is None


# ---------- RSS 2.0 の日付（技術評論社）----------


def test_RSS2の日付を日本時間に直す() -> None:
    parsed = parse_rfc822("Wed, 07 Oct 2026 14:39:00 +0900")
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-07T14:39:00+09:00"


def test_RSS2の日付がUTCでも日本時間に直す() -> None:
    parsed = parse_rfc822("Wed, 07 Oct 2026 00:00:00 +0000")
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-07T09:00:00+09:00"


def test_RSS2の日付にタイムゾーンが無ければ日本時間として扱う() -> None:
    parsed = parse_rfc822("Wed, 07 Oct 2026 14:39:00")
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-07T14:39:00+09:00"


@pytest.mark.parametrize("raw", ["", "   ", "いつか", "2026-10-07"])
def test_読めないRSS2の日付はNoneを返す(raw: str) -> None:
    assert parse_rfc822(raw) is None
