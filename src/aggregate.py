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


def pick_top(
    articles: Iterable[Article],
    used_urls: set[str],
    limit: int = TOP_N,
) -> list[Article]:
    """1つのセクションに載せる記事を決める。

    要件4のとおり、同じ記事は keywords.txt で先に書かれたセクションにだけ載せる。
    そのため、

      1. すでに他のセクションに「載った」記事を除く
      2. セクション内の重複を1件にまとめる
      3. いいね数順に並べて上位 limit 件を取る
      4. 実際に載せた記事の URL だけを used_urls に加える

    の順で処理する。4 を最後に行うのが大事で、ここで候補すべてを used_urls に入れて
    しまうと、載らなかった記事まで後のセクションから消えてしまう。
    """
    candidates = dedupe_within(exclude_used(articles, used_urls))
    top = rank(candidates, limit)
    used_urls.update(normalize_url(a.url) for a in top)
    return top
