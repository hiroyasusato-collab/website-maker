"""GitHub から、直近に作られた AI 関連のリポジトリを取る（GitHub 公式 API）。

    GET https://api.github.com/search/repositories
          ?q=created:>=<日付>&sort=stars&order=desc&per_page=100&page=<n>

2026-10-07 に確認したこと:
  ・公式 API なので利用規約・robots.txt の心配がない
  ・sort=stars&order=desc で**サーバー側がスター数の多い順に返す**
    （Hacker News と同じく、並べ替えを自分でしなくてよい取得元）
  ・q=created:>=YYYY-MM-DD で作成日を絞れる。**この日付は UTC で解釈される**ので、
    日本時間の 0:00〜9:00 に作られたリポジトリを落とさないよう1日前から指定し、
    正確な期間の絞り込みは呼び出し側（aggregate.within_window）に任せる
  ・per_page は最大100。合言葉なしのアクセス上限は検索 API で**1分に10回**
    （応答ヘッダ X-RateLimit-Limit: 10 で実測確認）。ここは最大3回なので余裕がある
  ・1ページ（100件）の中に AI 関連が40件以上あった（実測）。ふつうは1回で足りる

AI かどうかの判定は、ほかの取得元と同じく ai_trend_words.txt の単語で行う。
リポジトリ名だけでは中身が分からないことが多いので、**名前と説明文をつないだもの**を
タイトルとして表に出す。ただし長い説明文は表示のために切るので、
**判定には切る前の全文を使う**（Article.match_text）。切ったあとで判定すると、
落とした部分にだけ AI の単語があったリポジトリを取りこぼす。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from src.aggregate import normalize_url
from src.fetcher import JsonFetch
from src.models import SITE_GITHUB, Article
from src.timeutil import parse_iso, to_date

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.github.com/search/repositories"

# GitHub API の作法。版を明示しておくと、仕様が変わっても急に挙動が変わらない。
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

PER_PAGE = 100

# 安全網としての上限。検索 API は合言葉なしで1分に10回までなので、小さくしてある。
MAX_PAGES = 3

# タイトル（名前＋説明文）の長さの上限。2列表示で行が長くなりすぎないようにする。
TITLE_MAX_CHARS = 120


class GitHubIncompleteError(Exception):
    """検索が時間切れで打ち切られ、結果が1件も返らなかった。

    GitHub の検索 API は時間切れになると、HTTP 200 のまま
    `incomplete_results: true` と途中までの結果（ときには空）を返す。
    それを「期間内に該当するリポジトリが無かった」として扱うと、
    取得に失敗したことが分からなくなる。要件5のとおり黙って消さないために、
    例外にして呼び出し側（pipeline）で「取得できませんでした」と記録させる。
    """


def build_full_text(full_name: str, description: str | None) -> str:
    """名前と説明文をつないだ全文: `所有者/リポジトリ名 — 説明文`

    **切らずに**返す。AI 判定にはこちらを使う。
    説明文が無いリポジトリも多いので、その場合は名前だけにする。
    """
    text = (description or "").strip().replace("\n", " ")
    return f"{full_name} — {text}" if text else full_name


def build_title(full_name: str, description: str | None) -> str:
    """表に出すタイトルを作る。長すぎる場合は切って末尾に「…」を付ける。

    **切るのは表示のためだけ**。AI 判定は build_full_text の全文に対して行う。
    切ったあとの文字列で判定すると、落とした部分にだけ AI の単語があった
    リポジトリ（説明文が長いものに多い）を取りこぼす。
    """
    title = build_full_text(full_name, description)
    if len(title) > TITLE_MAX_CHARS:
        title = title[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return title


def collect(
    since: datetime,
    fetch_json: JsonFetch,
    is_wanted: Callable[[str], bool] | None = None,
    needed: int = 0,
    until: datetime | None = None,
) -> list[Article]:
    """直近に作られたリポジトリを、スター数の多い順に返す。

    is_wanted と needed を渡すと、「ほしいリポジトリ」が needed 件そろうまでページを
    進める（Hacker News と同じ考え方）。AI 以外のリポジトリが続いても表が埋まるようにする。
    AI かどうかの最終判定は呼び出し側（trend_filter）が行う。
    """
    # created:>= は UTC の日付で解釈されるため、1日前から広く取って後で正確に絞る。
    since_date = to_date(since - timedelta(days=1)).isoformat()

    articles: list[Article] = []
    seen_urls: set[str] = set()
    wanted_count = 0
    incomplete = False

    for page in range(1, MAX_PAGES + 1):
        payload = fetch_json(
            SEARCH_URL,
            params={
                "q": f"created:>={since_date}",
                "sort": "stars",
                "order": "desc",
                "per_page": PER_PAGE,
                "page": page,
            },
            headers=HEADERS,
        )
        data = payload or {}
        # GitHub は検索が時間切れになると「途中までの結果」とこの印を返す（公式仕様）。
        # 印が付いたら、続きは取れないので進めるのをやめる。
        if data.get("incomplete_results"):
            incomplete = True

        raw_items = data.get("items") or []
        if not raw_items:
            break

        for raw in raw_items:
            full_name = raw.get("full_name")
            url = raw.get("html_url")
            published_at = parse_iso(raw.get("created_at") or "")
            if not full_name or not url or published_at is None:
                continue

            normalized = normalize_url(url)
            # 読めない URL はページに出せないので落とす。同じリポジトリは1回だけ数える。
            if not normalized or normalized in seen_urls:
                continue
            seen_urls.add(normalized)

            if published_at < since:
                continue
            if until is not None and published_at >= until:
                continue

            # 表示用は切る。AI 判定には切る前の全文を使う（match_text）。
            description = raw.get("description")
            full_text = build_full_text(full_name, description)
            articles.append(
                Article(
                    title=build_title(full_name, description),
                    url=url,
                    score=int(raw.get("stargazers_count") or 0),
                    published_at=published_at,
                    site=SITE_GITHUB,
                    match_text=full_text,
                )
            )

            if is_wanted is not None and is_wanted(full_text):
                wanted_count += 1

        if incomplete:
            break
        # スター数の多い順に返ってくるので、必要数そろったらこれ以上進めなくてよい。
        if needed and wanted_count >= needed:
            break
        if len(raw_items) < PER_PAGE:
            break
    else:
        if needed and wanted_count < needed:
            logger.warning(
                "GitHub: %dページ取得しても対象のリポジトリが %d 件しか見つかりませんでした"
                "（必要 %d 件）。",
                MAX_PAGES,
                wanted_count,
                needed,
            )

    if incomplete:
        # 1件も取れていないなら「期間内に該当なし」と区別できないので、
        # 取得失敗として扱う（はてなブックマークが RSS でない応答を返したときと同じ考え方）。
        if not articles:
            raise GitHubIncompleteError(
                "GitHub の検索が時間切れで打ち切られ、結果が1件も返りませんでした"
            )
        logger.warning(
            "GitHub: 検索が時間切れで打ち切られました（incomplete_results）。"
            "取れたのは %d 件で、本来より少ない可能性があります。",
            len(articles),
        )

    return articles
