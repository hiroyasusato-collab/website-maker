"""Zenn からキーワードに合う記事を取る（非公式 API）。

    GET https://zenn.dev/api/search?q=<キーワード>&source=articles&order=latest&page=<n>

2026-10-07 に確認したこと:
  ・1ページ48件。page でページ送りでき、1ページで約2日分さかのぼれる
  ・order は latest（新しい順）と alltime（全期間のいいね数順）だけが効く。
    daily / weekly / liked_count を指定しても無視されて関連度順になるため使わない
  ・期間を指定するパラメータは無い → 新しい順に取って自分で7日に絞る
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.fetcher import JsonFetch
from src.models import SITE_ZENN, Article
from src.timeutil import parse_iso

logger = logging.getLogger(__name__)

SEARCH_URL = "https://zenn.dev/api/search"
SITE_ROOT = "https://zenn.dev"

# 1ページ48件 × 6ページ = 288件。実測では1ページで約2日分さかのぼれるので
# 7日分には4〜5ページで届く。6ページは安全網。
MAX_PAGES = 6


def collect(keyword: str, since: datetime, fetch_json: JsonFetch) -> list[Article]:
    """キーワードに合う記事のうち、since 以降に投稿されたものを返す。"""
    articles: list[Article] = []

    for page in range(1, MAX_PAGES + 1):
        payload = fetch_json(
            SEARCH_URL,
            params={"q": keyword, "source": "articles", "order": "latest", "page": page},
        )
        raw_items = (payload or {}).get("articles") or []
        if not raw_items:
            break

        oldest_on_page: datetime | None = None
        for raw in raw_items:
            published_at = parse_iso(raw.get("published_at") or "")
            path = raw.get("path")
            title = raw.get("title")
            if published_at is None or not path or not title:
                continue

            if oldest_on_page is None or published_at < oldest_on_page:
                oldest_on_page = published_at

            if published_at >= since:
                articles.append(
                    Article(
                        title=title,
                        url=SITE_ROOT + path,
                        score=int(raw.get("liked_count") or 0),
                        published_at=published_at,
                        site=SITE_ZENN,
                    )
                )

        # このページの最も古い記事が期間より前なら、次のページはすべて期間外。
        if oldest_on_page is not None and oldest_on_page < since:
            break
    else:
        # 期間の端に届かないまま上限に達した＝古い側を見落としている可能性がある。
        logger.warning(
            "Zenn（%s）: %dページの上限まで取得しました。"
            "期間内にこれより多くの記事があり、一部を見落としている可能性があります。",
            keyword,
            MAX_PAGES,
        )

    return articles
