"""集めた記事を、ページに載せる形に整える。

やること:
  ・URL の表記の揺れをそろえる（重複を見つけるため）
  ・同じ記事が複数のセクションに出ないようにする（要件4）
  ・いいね数の多い順に並べて上位10件に切る（要件3）
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.models import Article

TOP_N = 10

# 広告・流入計測用のパラメータ。記事の中身とは関係ないので、重複判定では無視する。
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"})


def normalize_url(url: str) -> str:
    """同じ記事を同じ文字列にそろえる。

    ・http と https の違いを無視する
    ・ホスト名の大文字小文字を無視する
    ・utm_source などの計測用パラメータを落とす
    ・末尾の / と #... を落とす

    読み取れない URL は空文字を返す。呼び出し側はそれを「載せられない記事」として落とす。
    壊れた URL が1件混ざっただけでページ全体の作成が止まらないようにするため
    （要件5：1つの取得元の問題で他のセクションを失わない）。
    """
    text = (url or "").strip()
    if not text:
        return ""

    try:
        parts = urlsplit(text)
    except ValueError:
        # 例: "https://[broken" は urlsplit が ValueError を投げる。
        return ""
    # scheme は https にそろえる（同じ記事が http/https 両方で来ても1つと見なす）
    scheme = "https" if parts.scheme in ("http", "https", "") else parts.scheme
    netloc = parts.netloc.lower()

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
        and not key.lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    query = urlencode(kept)

    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def within_window(articles: Iterable[Article], since: datetime, until: datetime) -> list[Article]:
    """期間内（since 以上 until 未満）の記事だけを残す。

    下限は各取得元でも見ているが、上限はここでまとめて見る。
    予約投稿などで投稿日が未来になっている記事を落とすため。
    """
    return [a for a in articles if since <= a.published_at < until]


def dedupe_within(articles: Iterable[Article]) -> list[Article]:
    """同じ URL の記事が2件以上あれば1件にする。並び順は変えない。"""
    seen: set[str] = set()
    result: list[Article] = []
    for article in articles:
        key = normalize_url(article.url)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(article)
    return result


def exclude_used(articles: Iterable[Article], used_urls: set[str]) -> list[Article]:
    """すでに他のセクションに載った記事を除く。used_urls は書き換えない。"""
    return [a for a in articles if normalize_url(a.url) not in used_urls]


def rank(articles: Iterable[Article], limit: int = TOP_N) -> list[Article]:
    """いいね数の多い順に並べて上位 limit 件を返す。

    いいね数が同じときは新しい記事を先にし、それも同じならタイトル順にする。
    （同じ入力なら毎回同じ結果になるようにするため）
    """
    ordered = sorted(articles, key=lambda a: (-a.score, -a.published_at.timestamp(), a.title))
    return ordered[:limit]


def select_with_site_cap(
    articles: Iterable[Article],
    limit: int = TOP_N,
    max_per_site: int = 0,
) -> list[Article]:
    """いいね数順に上位 limit 件を選ぶ。ただし同じサイトからは max_per_site 件まで。

    note のスキ（いいね）は読者層が広く押されやすく、技術者向けの Zenn・Qiita より
    数が大きくなりやすい。そのまま並べると note が上位を占めてしまうため、
    1サイトあたりの件数に上限を設けて他のサイトの記事を拾えるようにする。

    max_per_site が 0 以下のときは上限なし（この絞り込みをしない）。

    **他のサイトの記事を使い切っても limit に満たない場合は、上限を超えて埋める。**
    上限は「1つのサイトが独占しないようにする」ためのもので、他に出せる記事が
    無いなら件数を減らす意味がない。たとえば M365 のように note しか記事が無い
    キーワードで、7件あるのに4件しか出さないのは情報が減るだけになる。
    """
    ordered = sorted(articles, key=lambda a: (-a.score, -a.published_at.timestamp(), a.title))

    if max_per_site <= 0:
        return ordered[:limit]

    chosen: list[Article] = []
    skipped: list[Article] = []
    per_site: dict[str, int] = {}

    # 1回目：上限を守りながら、いいね数の多い順に取る。
    for article in ordered:
        if len(chosen) >= limit:
            break
        if per_site.get(article.site, 0) >= max_per_site:
            skipped.append(article)
            continue
        chosen.append(article)
        per_site[article.site] = per_site.get(article.site, 0) + 1

    # 2回目：まだ limit に届かないなら、上限で飛ばした記事で埋める。
    for article in skipped:
        if len(chosen) >= limit:
            break
        chosen.append(article)

    # 表示はいいね数順にそろえる。
    return sorted(chosen, key=lambda a: (-a.score, -a.published_at.timestamp(), a.title))


def count_by_site(articles: Iterable[Article]) -> dict[str, int]:
    """サイトごとの件数を数える。上限を超えて埋めたかどうかの確認に使う。"""
    counts: dict[str, int] = {}
    for article in articles:
        counts[article.site] = counts.get(article.site, 0) + 1
    return counts


def pick_top(
    articles: Iterable[Article],
    used_urls: set[str],
    limit: int = TOP_N,
    max_per_site: int = 0,
) -> list[Article]:
    """1つのセクションに載せる記事を決める。

    要件4のとおり、同じ記事は keywords.txt で先に書かれたセクションにだけ載せる。
    そのため、

      1. すでに他のセクションに「載った」記事を除く
      2. セクション内の重複を1件にまとめる
      3. いいね数順に並べて上位 limit 件を取る（1サイトあたりの上限を守る）
      4. 実際に載せた記事の URL だけを used_urls に加える

    の順で処理する。4 を最後に行うのが大事で、ここで候補すべてを used_urls に入れて
    しまうと、載らなかった記事まで後のセクションから消えてしまう。
    """
    candidates = dedupe_within(exclude_used(articles, used_urls))
    top = select_with_site_cap(candidates, limit, max_per_site)
    used_urls.update(normalize_url(a.url) for a in top)
    return top
