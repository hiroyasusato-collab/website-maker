"""ページ1回分を組み立てる処理の本体。

要件5のとおり「どれか1つの取得元が失敗しても、他の取得元のセクションは表示される」
ようにするため、取得元ごとに失敗を受け止めて先へ進む。失敗は黙って消さず、
ページ上に「取得できませんでした」として残す。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from src import aggregate
from src.config import Settings
from src.fetcher import JsonFetch, TextFetch
from src.models import (
    LABEL_BOOKMARKS,
    LABEL_LIKES,
    LABEL_POINTS,
    SITE_HACKER_NEWS,
    SITE_HATENA,
    SITE_NOTE,
    SITE_QIITA,
    SITE_ZENN,
    Article,
    Page,
    Ranking,
    Section,
)
from src.sources import hackernews, hatena, note_com, qiita, zenn
from src.timeutil import now_jst, period_end, period_start, to_date
from src.trend_filter import filter_ai_related, is_ai_related

logger = logging.getLogger(__name__)

TREND_HEADING = "AI業界トレンド"


def _safe_collect(
    site: str,
    collect: Callable[[], list[Article]],
) -> tuple[list[Article], str | None]:
    """1つの取得元から取る。失敗したら空の一覧と説明文を返す。

    例外の種類は問わない。ネットの不調・仕様変更・想定外の応答のどれでも、
    他の取得元の処理は続けたいため。
    """
    try:
        articles = collect()
    except Exception as error:  # noqa: BLE001 - 1つの失敗で全体を止めないため
        logger.warning("%s の取得に失敗しました: %s", site, error)
        return [], f"{site} は取得できませんでした（{type(error).__name__}）。"
    logger.info("%s: %d 件", site, len(articles))
    return articles, None


def build_keyword_section(
    keyword: str,
    since: datetime,
    until: datetime,
    settings: Settings,
    fetch_json: JsonFetch,
    used_urls: set[str],
) -> Section:
    """キーワード1つ分のセクションを作る（Zenn・Qiita・note の3つから集める）。"""
    collected: list[Article] = []
    notes: list[str] = []

    for site, collect in (
        (SITE_ZENN, lambda: zenn.collect(keyword, since, fetch_json)),
        (SITE_QIITA, lambda: qiita.collect(keyword, since, fetch_json, settings.qiita_token)),
        (SITE_NOTE, lambda: note_com.collect(keyword, since, fetch_json)),
    ):
        articles, note = _safe_collect(f"{site}（{keyword}）", collect)
        collected.extend(articles)
        if note:
            notes.append(note)

    in_window = aggregate.within_window(collected, since, until)
    # 1サイトあたりの上限を守って TOP10 を選ぶ（AI業界トレンドセクションでは使わない）。
    articles = aggregate.pick_top(in_window, used_urls, max_per_site=settings.max_per_site)

    # 他のサイトの記事が足りず、上限を超えて埋めた場合は実行した人に知らせる。
    if settings.max_per_site > 0:
        over = {
            site: count
            for site, count in aggregate.count_by_site(articles).items()
            if count > settings.max_per_site
        }
        if over:
            logger.info(
                "%s: 他のサイトの記事が足りないため、1サイトの上限（%d件）を超えて埋めました: %s",
                keyword,
                settings.max_per_site,
                "、".join(f"{site} {count}件" for site, count in over.items()),
            )

    return Section(
        heading=keyword,
        rankings=[Ranking(score_label=LABEL_LIKES, articles=articles, notes=notes)],
    )


def build_trend_section(
    since: datetime,
    until: datetime,
    settings: Settings,
    fetch_json: JsonFetch,
    fetch_text: TextFetch,
) -> Section:
    """AI業界トレンドのセクションを作る。

    はてなブックマークと Hacker News は数え方が違うので混ぜず、別々の表にする（要件3.2）。
    AI かどうかはタイトルの単語で判定する。
    """
    rankings: list[Ranking] = []

    def wanted(title: str) -> bool:
        return is_ai_related(title, settings.trend_words)

    # --- はてなブックマーク ---
    hatena_articles, hatena_note = _safe_collect(
        SITE_HATENA,
        lambda: hatena.collect(since, fetch_text, settings.hatena_min_users),
    )
    rankings.append(
        Ranking(
            caption=f"{SITE_HATENA}（ブックマーク数順）",
            score_label=LABEL_BOOKMARKS,
            # セクションをまたぐ重複除去はキーワード別セクションの話なので、
            # ここでは表の中だけで重複を見る（要件4）。
            articles=aggregate.pick_top(
                filter_ai_related(
                    aggregate.within_window(hatena_articles, since, until),
                    settings.trend_words,
                ),
                set(),
            ),
            notes=[hatena_note] if hatena_note else [],
        )
    )

    # --- Hacker News ---
    # AI 関連が TOP10 分そろうまでページを進める。全ジャンルの投稿を一定数だけ取って
    # あとから絞ると、AI 以外が続いた場合に表が埋まらなくなるため。
    hn_articles, hn_note = _safe_collect(
        SITE_HACKER_NEWS,
        lambda: hackernews.collect(
            since, fetch_json, is_wanted=wanted, needed=aggregate.TOP_N, until=until
        ),
    )
    rankings.append(
        Ranking(
            caption=f"{SITE_HACKER_NEWS}（ポイント順）",
            score_label=LABEL_POINTS,
            articles=aggregate.pick_top(
                filter_ai_related(
                    aggregate.within_window(hn_articles, since, until),
                    settings.trend_words,
                ),
                set(),
            ),
            notes=[hn_note] if hn_note else [],
        )
    )

    return Section(heading=TREND_HEADING, rankings=rankings)


def build_page(
    settings: Settings,
    fetch_json: JsonFetch,
    fetch_text: TextFetch,
    reference: datetime | None = None,
) -> Page:
    """1回分のページを組み立てる。"""
    reference = reference or now_jst()
    since = period_start(reference)
    until = period_end(reference)
    logger.info(
        "集める期間: %s 0:00 〜 %s（日本時間）",
        to_date(since).isoformat(),
        to_date(reference).isoformat(),
    )

    # 要件4：先に書かれたセクションに載った記事を覚えておき、後のセクションでは省く。
    used_urls: set[str] = set()

    sections = [
        build_keyword_section(keyword, since, until, settings, fetch_json, used_urls)
        for keyword in settings.keywords
    ]
    sections.append(build_trend_section(since, until, settings, fetch_json, fetch_text))

    return Page(
        target_date=to_date(reference),
        period_start=to_date(since),
        sections=sections,
    )
