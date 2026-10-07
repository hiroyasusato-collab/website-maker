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
    SITE_X,
    SITE_ZENN,
    Article,
    Page,
    Ranking,
    Section,
)
from src.sources import hackernews, hatena, note_com, qiita, x_posts, zenn
from src.timeutil import now_jst, period_end, period_start, to_date
from src.trend_filter import filter_ai_related, is_ai_related

logger = logging.getLogger(__name__)

TREND_HEADING = "AI業界トレンド"

# X の表の見出しに使う言語名。
X_LANGUAGE_LABELS = {"ja": "日本語", "en": "英語"}


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

    # --- X（旧 Twitter）---
    # お金がかかる取得元なので、止まっているときは接続そのものを行わず、表も出さない。
    if settings.x_enabled:
        rankings.extend(_build_x_rankings(since, until, settings, fetch_json))
    else:
        logger.info("X は止めてあります（.env の X_ENABLED）。接続せず、表も出しません。")

    return Section(heading=TREND_HEADING, rankings=rankings, is_trend=True)


def _build_x_rankings(
    since: datetime,
    until: datetime,
    settings: Settings,
    fetch_json: JsonFetch,
) -> list[Ranking]:
    """X の表を言語ごとに作る（日本語・英語）。

    読み取り件数の枠（budget）は**日本語・英語で1つを共有する**。
    言語ごとに別の枠にすると、合計が X_MAX_POSTS を超えてしまう。
    """
    rankings: list[Ranking] = []
    budget = x_posts.PostBudget(settings.x_max_posts)

    for lang in x_posts.LANGUAGES:
        label = X_LANGUAGE_LABELS.get(lang, lang)
        articles, note = _safe_collect(
            f"{SITE_X}（{label}）",
            lambda lang=lang: x_posts.collect(  # type: ignore[misc]
                lang,
                settings.trend_words,
                fetch_json,
                settings.x_bearer_token,
                budget,
                settings.x_require_link,
            ),
        )
        rankings.append(
            Ranking(
                caption=f"{SITE_X}（{label}・いいね数順）",
                score_label=LABEL_LIKES,
                articles=aggregate.pick_top(aggregate.within_window(articles, since, until), set()),
                notes=[note] if note else [],
            )
        )
    return rankings


def arrange_for_display(keywords: list[str], display_order: list[str]) -> list[str]:
    """キーワードを「ページに出す順番」に並べ替える。

    display_order.txt に書かれた順を先に使い、**書かれていないキーワードは末尾に足す**。
    キーワードを増やしたときに display_order.txt へ書き忘れても、ページから消えない。
    display_order.txt にしか無いキーワード（keywords.txt から消したものなど）は無視する。

    この並べ替えは**表示だけ**に効く。どの記事がどのセクションに載るかを決める
    優先順は keywords.txt の順のままで変わらない（要件4）。
    """
    remaining = list(keywords)
    ordered: list[str] = []

    for keyword in display_order:
        if keyword in remaining:
            remaining.remove(keyword)
            ordered.append(keyword)

    # display_order.txt に無いものは、keywords.txt の順で末尾に足す。
    ordered.extend(remaining)
    return ordered


def build_page(
    settings: Settings,
    fetch_json: JsonFetch,
    fetch_text: TextFetch,
    reference: datetime | None = None,
) -> Page:
    """1回分のページを組み立てる。

    集めるのは keywords.txt の順（＝重複を省く優先順）で行い、
    そのあと表示用に並べ替える。この2つを分けておくことが大事で、
    表示の並びを変えても「どの記事がどのセクションに載るか」は変わらない。
    """
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

    # 1) keywords.txt の順に集める（優先順）
    by_keyword = {
        keyword: build_keyword_section(keyword, since, until, settings, fetch_json, used_urls)
        for keyword in settings.keywords
    }

    # 2) 表示用に並べ替える
    display_keywords = arrange_for_display(settings.keywords, settings.display_order)
    keyword_sections = [by_keyword[keyword] for keyword in display_keywords]

    # AI業界トレンドを先に出し、そのあとキーワード別セクションを並べる。
    sections = [build_trend_section(since, until, settings, fetch_json, fetch_text)]
    sections.extend(keyword_sections)

    return Page(
        target_date=to_date(reference),
        period_start=to_date(since),
        sections=sections,
    )
