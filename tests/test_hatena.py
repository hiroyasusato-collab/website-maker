"""はてなブックマークの取得のテスト。実際の Web サイトにはつながない。"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.models import SITE_HATENA
from src.sources import hatena
from tests.conftest import RecordingFetch, load_fixture_text

EMPTY_RSS = '<?xml version="1.0" encoding="UTF-8"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"></rdf:RDF>'  # noqa: E501


def test_RSSから必要な4項目を取り出す() -> None:
    articles = hatena.parse_rss(load_fixture_text("hatena_search.rss"))

    assert len(articles) == 5
    first = articles[0]
    # 文字参照（&#x30AA; など）が日本語に戻っていること。
    assert first.title == "オープンAIのエージェントが暴走"
    assert first.url == "https://www.publickey1.jp/blog/26/fdeai7fde.html"
    assert first.score == 99
    assert first.published_at.isoformat() == "2026-10-06T16:38:26+09:00"
    assert first.site == SITE_HATENA


def test_ブックマーク数が無い記事は0件として扱う() -> None:
    articles = hatena.parse_rss(load_fixture_text("hatena_search.rss"))
    target = next(a for a in articles if "ブックマーク数が無い" in a.title)
    assert target.score == 0


def test_UTCの日付を日本時間に直す() -> None:
    articles = hatena.parse_rss(load_fixture_text("hatena_search.rss"))
    # RSS の 2026-10-06T07:38:26Z は日本時間で 16:38
    assert articles[0].published_at.hour == 16


def test_RSSでない応答は取得失敗として扱う() -> None:
    """はてブは障害時に HTTP 200 で HTML を返すことがある。

    0件と区別しないと、ページに「該当する記事はありませんでした」と出てしまい
    取得に失敗したことが分からなくなる（要件5）。
    """
    with pytest.raises(hatena.HatenaResponseError):
        hatena.parse_rss("これはXMLではありません")
    with pytest.raises(hatena.HatenaResponseError):
        hatena.parse_rss("")
    with pytest.raises(hatena.HatenaResponseError, match="RSS ではない"):
        hatena.parse_rss("<html><body>メンテナンス中</body></html>")


def test_中身が空のRSSは0件として扱う() -> None:
    """形は正しくて記事が無いだけなら、取得失敗ではない。"""
    assert hatena.parse_rss(EMPTY_RSS) == []


def test_項目が欠けた記事は落とす() -> None:
    """タイトル・リンク・日付のどれかが無い item は、ページに出せないので落とす。"""
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:hatena="http://www.hatena.ne.jp/info/xmlns#">
<item rdf:about="https://example.com/no-title">
<link>https://example.com/no-title</link>
<dc:date>2026-10-05T01:00:00Z</dc:date>
<hatena:bookmarkcount>50</hatena:bookmarkcount>
</item>
<item rdf:about="https://example.com/no-link">
<title>リンクが無い記事</title>
<dc:date>2026-10-05T01:00:00Z</dc:date>
<hatena:bookmarkcount>50</hatena:bookmarkcount>
</item>
<item rdf:about="https://example.com/no-date">
<title>日付が無い記事</title>
<link>https://example.com/no-date</link>
<hatena:bookmarkcount>50</hatena:bookmarkcount>
</item>
<item rdf:about="https://example.com/ok">
<title>そろっている記事</title>
<link>https://example.com/ok</link>
<dc:date>2026-10-05T01:00:00Z</dc:date>
<hatena:bookmarkcount>50</hatena:bookmarkcount>
</item>
</rdf:RDF>"""
    assert [a.title for a in hatena.parse_rss(rss)] == ["そろっている記事"]


def test_RSSでない応答は取得側でも例外になる(since: datetime) -> None:
    fetch = RecordingFetch(["<html>エラー</html>"], last=EMPTY_RSS)
    with pytest.raises(hatena.HatenaResponseError):
        hatena.collect(since, fetch, min_users=10)


def test_期間より古い記事は落とす(since: datetime) -> None:
    fetch = RecordingFetch([load_fixture_text("hatena_search.rss")], last=EMPTY_RSS)
    articles = hatena.collect(since, fetch, min_users=10)
    assert all("期間より古い" not in a.title for a in articles)


def test_検索の指定が正しい(since: datetime) -> None:
    """テクノロジーのRSSでは7日分が取れないため、検索RSSを使う。"""
    fetch = RecordingFetch([EMPTY_RSS])
    hatena.collect(since, fetch, min_users=25)

    url, params, _ = fetch.calls[0]
    assert url == hatena.SEARCH_URL
    assert params["q"] == "AI"
    assert params["mode"] == "rss"
    assert params["users"] == 25
    assert params["date_range"] == "1w"
    assert params["page"] == 1


def test_期間より古いページまで来たらページ送りをやめる(since: datetime) -> None:
    # fixture には 2026-09-18 の記事が入っているので、1ページ目で打ち切られる。
    fetch = RecordingFetch([load_fixture_text("hatena_search.rss")], last=EMPTY_RSS)
    hatena.collect(since, fetch, min_users=10)
    assert len(fetch.calls) == 1


def test_記事が無ければページ送りをやめる(since: datetime) -> None:
    fetch = RecordingFetch([EMPTY_RSS], last=EMPTY_RSS)
    hatena.collect(since, fetch, min_users=10)
    assert len(fetch.calls) == 1


def test_検索語を複数指定できる(since: datetime) -> None:
    fetch = RecordingFetch([], last=EMPTY_RSS)
    hatena.collect(since, fetch, min_users=10, queries=("AI", "LLM"))
    queries = [params["q"] for _, params, _ in fetch.calls]
    assert queries == ["AI", "LLM"]


def test_AI判定はここでは行わない(since: datetime) -> None:
    """ここは候補集めだけ。AI でないタイトルも含めて返す（絞るのは trend_filter）。"""
    fetch = RecordingFetch([load_fixture_text("hatena_search.rss")], last=EMPTY_RSS)
    articles = hatena.collect(since, fetch, min_users=10)
    assert any("JetBrains" in a.title for a in articles)
