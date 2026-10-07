"""Hacker News から AI 関連の記事を取る（HN 公式の検索 API）。

    GET https://hn.algolia.com/api/v1/search
          ?tags=story&numericFilters=created_at_i><7日前のUNIX秒>&hitsPerPage=100&page=<n>

2026-10-07 に確認したこと:
  ・/search（/search_by_date ではない方）はポイントの多い順に返る。
    実測で 1701 → 1686 → 1565 → 938 … と降順を確認
  ・numericFilters=created_at_i>... で期間を絞れる
    → 5つの取得元の中で、ここだけ「直近7日間 × ポイント順」をサーバー側で実現できる
  ・page は 0 から始まる
  ・url が空（null）の投稿がある（Ask HN / Tell HN など。100件中2件）。
    その場合は https://news.ycombinator.com/item?id=<objectID> を使う
  ・直近7日の100件のうちタイトルが AI 関連だったのは約1割
    → 上位10件を埋めるには300件（3ページ）取れば十分
  ・公式の Firebase API もあるが記事1件ごとに1回アクセスが必要（500回近く）なので使わない
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from src.aggregate import normalize_url
from src.fetcher import JsonFetch
from src.models import SITE_HACKER_NEWS, Article
from src.timeutil import parse_unix

logger = logging.getLogger(__name__)

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://news.ycombinator.com/item?id="

HITS_PER_PAGE = 100

# 安全網としての上限。ふつうは is_wanted が needed 件そろった時点で止まる。
MAX_PAGES = 5


def collect(
    since: datetime,
    fetch_json: JsonFetch,
    is_wanted: Callable[[str], bool] | None = None,
    needed: int = 0,
    until: datetime | None = None,
) -> list[Article]:
    """直近の投稿をポイントの多い順に返す。

    is_wanted と needed を渡すと、「ほしい投稿」が needed 件そろうまでページを進める。
    HN は全ジャンルの投稿が混ざっているため、一定数だけ取ってから AI で絞ると、
    AI 以外が続いた場合に表が埋まらなくなる。それを防ぐための引数。
    AI かどうかの最終判定は呼び出し側（trend_filter）が行う。

    数えるのは「実際にページに載せられる投稿」だけにする。重複・期間外・URL が
    読めないものを数に入れると、まだ10件そろっていないのにページ送りを止めてしまう。

    ただし URL の重複そのものは、ここで記事を落とすのには使わない（数えるときだけ使う）。
    AI 判定より前に URL で間引くと、同じ URL を指す「AI でない投稿 → AI の投稿」の順に
    返ってきたとき、先の投稿が後の AI 投稿を消してしまい、
    そのあと AI 判定で先の投稿も消えて0件になる。重複の除去は呼び出し側にまとめる。
    """
    since_unix = int(since.timestamp())
    articles: list[Article] = []
    seen_ids: set[str] = set()
    counted_urls: set[str] = set()
    wanted_count = 0

    for page in range(MAX_PAGES):
        payload = fetch_json(
            SEARCH_URL,
            params={
                "tags": "story",
                # since ちょうどの投稿も含めたいので >= にする。
                "numericFilters": f"created_at_i>={since_unix}",
                "hitsPerPage": HITS_PER_PAGE,
                "page": page,
            },
        )
        hits = (payload or {}).get("hits") or []
        if not hits:
            break

        for raw in hits:
            object_id = str(raw.get("objectID") or "")
            title = raw.get("title")
            published_at = parse_unix(raw.get("created_at_i"))
            if not object_id or object_id in seen_ids or not title or published_at is None:
                continue
            seen_ids.add(object_id)
            if published_at < since:
                continue
            if until is not None and published_at >= until:
                continue

            # Ask HN / Tell HN は外部 URL を持たないので HN の投稿ページを指す。
            url = raw.get("url") or f"{ITEM_URL}{object_id}"
            # 読めない URL はどうやってもページに出せないので、ここで落とす。
            normalized = normalize_url(url)
            if not normalized:
                continue

            articles.append(
                Article(
                    title=title,
                    url=url,
                    score=int(raw.get("points") or 0),
                    published_at=published_at,
                    site=SITE_HACKER_NEWS,
                )
            )

            # 数えるのは「ほしい投稿」で、かつまだ数えていない URL のものだけ。
            # 同じ記事を指す投稿は呼び出し側で1件にまとめられるため、
            # ここで2件と数えると10件そろう前にページ送りが止まってしまう。
            if is_wanted is not None and is_wanted(title) and normalized not in counted_urls:
                counted_urls.add(normalized)
                wanted_count += 1

        # ほしい投稿が必要数そろったら、ポイント順なのでこれ以上進めなくてよい。
        if needed and wanted_count >= needed:
            break
        if len(hits) < HITS_PER_PAGE:
            break
    else:
        if needed and wanted_count < needed:
            logger.warning(
                "Hacker News: %dページ取得しても対象の投稿が %d 件しか見つかりませんでした"
                "（必要 %d 件）。",
                MAX_PAGES,
                wanted_count,
                needed,
            )

    return articles
