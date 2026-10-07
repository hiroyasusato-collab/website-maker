"""技術評論社（gihyo.jp）から AI 関連の記事を取る（公式の RSS）。

    GET https://gihyo.jp/feed/rss2

2026-10-07 に確認したこと:
  ・**公式の RSS を使う**。同社のサイトには下部に「ページ内容の全部あるいは一部を
    無断で利用することを禁止します」という表示があるため、HTML を解析する方法は取らず、
    同社が配信のために公開している RSS だけを読む（本人確認のうえ決定）
  ・RSS には873件・1年分以上が入っていて、**1回の取得で7日分に十分届く**
  ・1件あたり title / link / pubDate / description / guid が取れる
      pubDate  Wed, 07 Oct 2026 14:39:00 +0900（RSS 2.0 の形式。時刻まで入る）
      guid     https://gihyo.jp/article/2026/10/embeddinggemma-2（きれいな URL）
      link     上と同じだが末尾に ?utm_source=feed が付く → guid を優先して使う
  ・**カテゴリの情報は RSS に入っていない**（rss1 / rss2 / atom の3つとも確認）。
    そのため「機械学習・AI」カテゴリで絞ることはできず、ほかの取得元と同じように
    ai_trend_words.txt の単語でタイトルを判定する（本人確認のうえ決定）
  ・人気の数字（いいね・ブックマーク数にあたるもの）は無い → **新着順**で並べる

AI かどうかの最終判定と並べ替えは呼び出し側（pipeline）が行う。ここは候補集めだけ。
"""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree

from src.fetcher import TextFetch
from src.models import SITE_GIHYO, Article
from src.timeutil import parse_rfc822

FEED_URL = "https://gihyo.jp/feed/rss2"

# RSS 2.0 の最上位の要素。これ以外が返ってきたら取得失敗として扱う。
RSS_ROOT = "rss"


class GihyoResponseError(Exception):
    """応答が RSS ではなかった。

    障害時などに HTTP 200 のまま HTML のエラーページが返ることがある。
    それを「記事0件」として扱うと取得の失敗が分からなくなるため、
    はてなブックマークと同じく例外にして呼び出し側に記録させる（要件5）。
    """


def parse_rss(xml_text: str) -> list[Article]:
    """技術評論社の RSS から記事を取り出す。

    人気の数字が無い取得元なので score は 0 のままにし、並べ替えは日付で行う。
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as error:
        raise GihyoResponseError(f"RSS として読めませんでした: {error}") from error

    if root.tag != RSS_ROOT:
        raise GihyoResponseError(f"RSS ではない応答が返りました（最上位の要素: {root.tag}）")

    articles: list[Article] = []
    for item in root.iter("item"):
        title = (item.findtext("title", default="") or "").strip()
        # guid は ?utm_source=feed が付かないきれいな URL。無ければ link を使う。
        guid = (item.findtext("guid", default="") or "").strip()
        link = (item.findtext("link", default="") or "").strip()
        url = guid if guid.startswith("http") else link
        published_at = parse_rfc822(item.findtext("pubDate", default="") or "")
        if not title or not url or published_at is None:
            continue

        articles.append(
            Article(
                title=title,
                url=url,
                score=0,
                published_at=published_at,
                site=SITE_GIHYO,
            )
        )
    return articles


def collect(since: datetime, fetch_text: TextFetch) -> list[Article]:
    """since 以降に公開された記事を返す（取得は1回だけ）。"""
    articles = parse_rss(fetch_text(FEED_URL))
    return [article for article in articles if article.published_at >= since]
