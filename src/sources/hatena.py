"""はてなブックマークから AI 関連の記事を取る（検索の RSS）。

    GET https://b.hatena.ne.jp/search/text?q=AI&mode=rss&users=10&date_range=1w&page=<n>

2026-10-07 に確認したこと:
  ・「テクノロジー」カテゴリの RSS（hotentry/it.rss）では7日分が取れない。
    30件・約1日分しか返らず、?date= / ?page= / ?of= / ?sort= / ?threshold= は
    すべて無視されて同じ30件が返る。そのため検索の RSS を使う（本人確認済み）
  ・検索の RSS では page が効く。1ページ40件、1ページで約1〜1.5日分
    → page 1〜8 で7日分に届く（実測で page 7 が 2026-09-30 まで到達）
  ・date_range=1w と users=<数> は効く
  ・sort / target / category は無視される（常に新着順・全カテゴリ・本文も検索対象）

検索語は AI の1語だけにしている。本文も検索対象なので AI 関連記事はこれでほぼ集まり、
そのあとタイトルを ai_trend_words.txt で絞り込む（要件3.2「判定はタイトルの単語で行う」）。
"""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree

from src.fetcher import TextFetch
from src.models import SITE_HATENA, Article
from src.timeutil import parse_iso

SEARCH_URL = "https://b.hatena.ne.jp/search/text"

# 既定の検索語。ここを増やすとアクセス回数も増えるので1語にしてある。
DEFAULT_QUERIES = ("AI",)

MAX_PAGES = 8

# RSS 1.0（RDF）の名前空間。
NS = {
    "rss": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "hatena": "http://www.hatena.ne.jp/info/xmlns#",
}


RDF_ROOT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"


class HatenaResponseError(Exception):
    """応答が RSS ではなかった。

    はてブは障害時などに HTTP 200 のまま HTML のエラーページを返すことがある。
    それを「記事0件」として扱うと、ページに「該当する記事はありませんでした」と出て
    取得に失敗したことが分からなくなる。要件5のとおり黙って消さないために、
    例外にして呼び出し側（pipeline）で「取得できませんでした」と記録させる。
    """


def parse_rss(xml_text: str) -> list[Article]:
    """はてブの RSS から記事を取り出す。

    タイトル中の文字参照（&#x30C6; など）は ElementTree が日本語に戻してくれる。
    中身が RSS でなければ HatenaResponseError を投げる（0件とは区別する）。
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as error:
        raise HatenaResponseError(f"RSS として読めませんでした: {error}") from error

    if root.tag != RDF_ROOT:
        raise HatenaResponseError(f"RSS ではない応答が返りました（最上位の要素: {root.tag}）")

    articles: list[Article] = []
    for item in root.findall("rss:item", NS):
        title = (item.findtext("rss:title", default="", namespaces=NS) or "").strip()
        url = (item.findtext("rss:link", default="", namespaces=NS) or "").strip()
        published_at = parse_iso(item.findtext("dc:date", default="", namespaces=NS) or "")
        if not title or not url or published_at is None:
            continue

        raw_count = (item.findtext("hatena:bookmarkcount", default="", namespaces=NS) or "").strip()
        try:
            score = int(raw_count)
        except ValueError:
            score = 0

        articles.append(
            Article(
                title=title,
                url=url,
                score=score,
                published_at=published_at,
                site=SITE_HATENA,
            )
        )
    return articles


def collect(
    since: datetime,
    fetch_text: TextFetch,
    min_users: int,
    queries: tuple[str, ...] = DEFAULT_QUERIES,
) -> list[Article]:
    """AI 関連の候補記事のうち、since 以降のものを返す。

    AI かどうかの最終判定は呼び出し側（trend_filter）が行う。ここは候補集めだけ。
    """
    articles: list[Article] = []

    for query in queries:
        for page in range(1, MAX_PAGES + 1):
            xml_text = fetch_text(
                SEARCH_URL,
                params={
                    "q": query,
                    "mode": "rss",
                    "users": min_users,
                    "date_range": "1w",
                    "page": page,
                },
            )
            page_articles = parse_rss(xml_text)
            if not page_articles:
                break

            articles.extend(a for a in page_articles if a.published_at >= since)

            # このページの最も古い記事が期間より前なら、次のページはすべて期間外。
            if min(a.published_at for a in page_articles) < since:
                break

    return articles
