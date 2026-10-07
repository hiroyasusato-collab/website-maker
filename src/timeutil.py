"""日時の取り扱い。取得元ごとに形式が違うので、ここで日本時間にそろえる。

取得元ごとの実際の形式（2026-10-07 に確認）:
    Zenn   published_at  2026-10-05T13:59:07.666+09:00
    Qiita  created_at    2026-10-07T09:04:31+09:00
    note   publish_at    2026-08-22T13:26:20.000+09:00
    はてブ  dc:date       2026-10-06T07:38:26Z         （UTC）
    HN     created_at_i  1790728885                   （UNIX秒・UTC基準）
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# 要件4「実行した日から直近7日間」の数え方。
# 実行日を含めた7日間とするので、さかのぼるのは6日。
PERIOD_DAYS = 7


def now_jst() -> datetime:
    return datetime.now(JST)


def period_start(reference: datetime) -> datetime:
    """集める期間の始まり（日本時間のその日の 0:00）を返す。

    実行時刻の端数で結果が揺れないように、日付の 0:00 にそろえる。
    """
    start_day = reference.astimezone(JST).date() - timedelta(days=PERIOD_DAYS - 1)
    return datetime.combine(start_day, datetime.min.time(), tzinfo=JST)


def period_end(reference: datetime) -> datetime:
    """集める期間の終わり（実行日の翌日 0:00・日本時間）を返す。この時刻は含まない。

    上限を決めておかないと、予約投稿などで投稿日が未来になっている記事が入り、
    ページに書いた期間と中身が合わなくなる。実行が日付をまたいだ場合にも効く。
    """
    next_day = reference.astimezone(JST).date() + timedelta(days=1)
    return datetime.combine(next_day, datetime.min.time(), tzinfo=JST)


def parse_iso(value: str) -> datetime | None:
    """ISO 8601 形式の文字列を日本時間の datetime にする。読めなければ None。

    末尾が Z（UTC）の形式にも対応する。
    """
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # タイムゾーンが書かれていない場合は日本時間として扱う。
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def parse_unix(value: object) -> datetime | None:
    """UNIX 秒を日本時間の datetime にする。読めなければ None。"""
    if not isinstance(value, (int, float, str)):
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(JST)


def to_date(value: datetime) -> date:
    return value.astimezone(JST).date()
