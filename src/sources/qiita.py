"""Qiita からキーワードに合う記事を取る（公式 API v2）。

    GET https://qiita.com/api/v2/items?query=<キーワード> created:>=<日付>&per_page=100&page=<n>

2026-10-07 に確認したこと:
  ・created:>=YYYY-MM-DD で期間をサーバー側で絞れる（5つの取得元の中でここだけ）
  ・per_page は最大100。並び順は新しい順で、いいね数順にする指定は無い
  ・アクセス上限はトークンなしで1時間60回（応答ヘッダ Rate-Limit で確認）。
    トークンを付けると1時間1000回。キーワード6個 × 最大3ページ = 18回なので
    トークンなしでも足りる
  ・応答1件に記事の全文（body / rendered_body）が入っていて重い。
    必要な項目だけ取り出してすぐ捨てる
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.fetcher import JsonFetch
from src.models import SITE_QIITA, Article
from src.timeutil import parse_iso, to_date

logger = logging.getLogger(__name__)

ITEMS_URL = "https://qiita.com/api/v2/items"

PER_PAGE = 100

# 安全網としての上限。応答は新しい順なので、途中で打ち切ると
# 期間の古い側（＝いいねが付く時間が長かった記事）を見落とす。
# 実測では広いキーワード（「Claude」など）で7日間に400〜500件あり、
# 3ページ（300件）で打ち切ると26いいねの記事を取りこぼしていた。
# キーワード6個 × 6ページ = 36回。トークン無しの上限（1時間60回）に収まる。
MAX_PAGES = 6


def collect(
    keyword: str,
    since: datetime,
    fetch_json: JsonFetch,
    token: str | None = None,
) -> list[Article]:
    """キーワードに合う記事のうち、since 以降に投稿されたものを返す。"""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    # created:>= は日付単位なので、境界の記事を落とさないよう日付で渡し、時刻は後で絞る。
    query = f"{keyword} created:>={to_date(since).isoformat()}"

    articles: list[Article] = []
    for page in range(1, MAX_PAGES + 1):
        raw_items = fetch_json(
            ITEMS_URL,
            params={"query": query, "per_page": PER_PAGE, "page": page},
            headers=headers,
        )
        if not raw_items:
            break

        for raw in raw_items:
            published_at = parse_iso(raw.get("created_at") or "")
            url = raw.get("url")
            title = raw.get("title")
            if published_at is None or not url or not title:
                continue
            if published_at < since:
                continue
            articles.append(
                Article(
                    title=title,
                    url=url,
                    score=int(raw.get("likes_count") or 0),
                    published_at=published_at,
                    site=SITE_QIITA,
                )
            )

        # 返ってきた件数が1ページ分に満たなければ、これで最後。
        if len(raw_items) < PER_PAGE:
            break
    else:
        # 上限まで使い切った＝まだ続きがある。古い側を見落としている可能性を知らせる。
        logger.warning(
            "Qiita（%s）: %dページの上限まで取得しました。"
            "期間内にこれより多くの記事があり、一部を見落としている可能性があります。",
            keyword,
            MAX_PAGES,
        )

    return articles
