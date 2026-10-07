"""ページ1回分を組み立てる処理の本体。

要件5のとおり「どれか1つの取得元が失敗しても、他の取得元のセクションは表示される」
ようにするため、取得元ごとに失敗を受け止めて先へ進む。失敗は黙って消さず、
ページ上に「取得できませんでした」として残す。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from src import aggregate
from src.config import KeywordGroup, Settings
from src.fetcher import JsonFetch, TextFetch
from src.models import (
    KIND_RESOURCES,
    KIND_TREND,
    LABEL_BOOKMARKS,
    LABEL_LIKES,
    LABEL_POINTS,
    LABEL_STARS,
    SITE_GIHYO,
    SITE_GITHUB,
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
    gap_section,
)
from src.sources import gihyo, github_repos, hackernews, hatena, note_com, qiita, x_posts, zenn
from src.timeutil import now_jst, period_end, period_start, to_date
from src.trend_filter import filter_ai_related, is_ai_related

logger = logging.getLogger(__name__)

TREND_HEADING = "AI業界トレンド"
RESOURCE_HEADING = "技術資料・リポジトリ"

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
    group: KeywordGroup,
    since: datetime,
    until: datetime,
    settings: Settings,
    fetch_json: JsonFetch,
    used_urls: set[str],
) -> Section:
    """キーワードのまとまり1つ分のセクションを作る（Zenn・Qiita・note の3つから集める）。

    keywords.txt の1行に複数の単語が書かれている場合（例：RAG, ナレッジグラフ）は、
    単語ごとに検索して結果を1つの表にまとめる。どちらかに当たる記事が並ぶ。
    """
    collected: list[Article] = []
    notes: list[str] = []

    for word in group.words:
        # lambda の中の word は「呼ばれたとき」の値になってしまうため、
        # 既定の引数として今の値を固定しておく（繰り返しの中で lambda を作るときの定石）。
        for site, collect in (
            (SITE_ZENN, lambda word=word: zenn.collect(word, since, fetch_json)),  # type: ignore[misc]
            (
                SITE_QIITA,
                lambda word=word: qiita.collect(  # type: ignore[misc]
                    word, since, fetch_json, settings.qiita_token
                ),
            ),
            (SITE_NOTE, lambda word=word: note_com.collect(word, since, fetch_json)),  # type: ignore[misc]
        ):
            articles, note = _safe_collect(f"{site}（{word}）", collect)
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
                group.name,
                settings.max_per_site,
                "、".join(f"{site} {count}件" for site, count in over.items()),
            )

    return Section(
        heading=group.name,
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

    return Section(heading=TREND_HEADING, rankings=rankings, kind=KIND_TREND)


def build_resource_section(
    since: datetime,
    until: datetime,
    settings: Settings,
    fetch_json: JsonFetch,
    fetch_text: TextFetch,
) -> Section:
    """技術資料・リポジトリのセクションを作る（GitHub・技術評論社）。

    数字の意味がキーワード別の表と違う（スター数／数字なし）ので、
    AI業界トレンドと同じように独立した表にして混ぜない。
    """
    rankings: list[Ranking] = []

    def wanted(title: str) -> bool:
        return is_ai_related(title, settings.trend_words)

    # --- GitHub（直近7日に作られたリポジトリ・スター数順）---
    # AI 関連が TOP10 分そろうまでページを進める（Hacker News と同じ考え方）。
    repos, repos_note = _safe_collect(
        SITE_GITHUB,
        lambda: github_repos.collect(
            since, fetch_json, is_wanted=wanted, needed=aggregate.TOP_N, until=until
        ),
    )
    rankings.append(
        Ranking(
            caption=f"{SITE_GITHUB}（スター数順）",
            score_label=LABEL_STARS,
            articles=aggregate.pick_top(
                filter_ai_related(
                    aggregate.within_window(repos, since, until), settings.trend_words
                ),
                set(),
            ),
            notes=[repos_note] if repos_note else [],
        )
    )

    # --- 技術評論社（新着順）---
    # 人気の数字が無い取得元なので、数の列を出さず（score_label=None）新着順に並べる。
    gihyo_articles, gihyo_note = _safe_collect(SITE_GIHYO, lambda: gihyo.collect(since, fetch_text))
    rankings.append(
        Ranking(
            caption=f"{SITE_GIHYO}（新着順）",
            score_label=None,
            articles=aggregate.pick_latest(
                filter_ai_related(
                    aggregate.within_window(gihyo_articles, since, until), settings.trend_words
                ),
                set(),
            ),
            notes=[gihyo_note] if gihyo_note else [],
        )
    )

    return Section(heading=RESOURCE_HEADING, rankings=rankings, kind=KIND_RESOURCES)


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


def arrange_for_display(
    keywords: Sequence[str], display_order: Sequence[str | None]
) -> list[str | None]:
    """キーワードを「ページに出す順番」に並べ替える。

    display_order.txt に書かれた順を先に使い、**書かれていないキーワードは末尾に足す**。
    キーワードを増やしたときに display_order.txt へ書き忘れても、ページから消えない。
    display_order.txt にしか無いキーワード（keywords.txt から消したものなど）は無視する。

    display_order に入っている **None は「表を置かない位置」**（「（空き）」と書いた行）で、
    そのまま結果に残す。2列表示で片側を空け、次の表を左列に送るために使う。
    末尾の None は見た目に影響しないので取り除く。

    この並べ替えは**表示だけ**に効く。どの記事がどのセクションに載るかを決める
    優先順は keywords.txt の順のままで変わらない（要件4）。
    """
    remaining = list(keywords)
    ordered: list[str | None] = []

    for name in display_order:
        if name is None:
            ordered.append(None)
            continue
        if name in remaining:
            remaining.remove(name)
            ordered.append(name)

    # display_order.txt に無いものは、keywords.txt の順で末尾に足す。
    ordered.extend(remaining)

    # 末尾の「（空き）」は意味が無いので落とす（空の枠がページ下部に残らないように）。
    while ordered and ordered[-1] is None:
        ordered.pop()
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
    by_name = {
        group.name: build_keyword_section(group, since, until, settings, fetch_json, used_urls)
        for group in settings.keywords
    }

    # 2) 表示用に並べ替える（None は「表を置かない位置」）
    display_names = arrange_for_display(list(by_name), settings.display_order)
    keyword_sections = [gap_section() if name is None else by_name[name] for name in display_names]

    # AI業界トレンド → 技術資料・リポジトリ → キーワード別 の順に並べる。
    sections = [
        build_trend_section(since, until, settings, fetch_json, fetch_text),
        build_resource_section(since, until, settings, fetch_json, fetch_text),
    ]
    sections.extend(keyword_sections)

    return Page(
        target_date=to_date(reference),
        period_start=to_date(since),
        sections=sections,
        # 取得はせず、ページにリンクを置くだけ（reference_links.txt）。
        reference_links=settings.reference_links,
    )
