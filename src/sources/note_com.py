"""note からキーワードに合う記事を取る（非公式 API）。

    GET https://note.com/api/v3/searches?context=note&q=<キーワード>&size=20&start=<n>&sort=hot

2026-10-07 に確認したこと（ここは試行錯誤が必要だった）:
  ・検索の入口は /api/v3/searches。/api/v3/searchnotes は 404（ネット上の古い情報）
  ・/api/v3/notes?q=... はキーワードを無視して新着を返すだけなので使えない
  ・sort の挙動:
      hot     … 直近1週間ほどの、キーワードに合う記事を返す → これを使う
      like    … キーワードに合うが全期間のいいね数順。上位は数か月前ばかりで7日分に届かない
      popular / trend / 無指定 … 関連度順で新旧が混ざる
      new     … キーワードを無視して全新着を返す（タイトルに語が無い記事が並ぶ）
  ・size は20が上限（50や100を指定しても20件しか返らない）
  ・期間を指定するパラメータ（period / date_range / time_range）はすべて無視される

  ・【重要】note の検索は当たりが非常にゆるい。20件のうちキーワードを実際に含むのは
    3〜8件で、残りは関係の薄い記事だった。実際に返ってきた例:
        「RAG」で検索 → 「いろはかるた大喜利『ゑ』」「麻婆菜館 四川風焼きそば」
        「RAG」で検索 → 「Day⑦｜金木犀Fragrant Olive」（"F"rag"rant" の部分一致）
    そのままページに載せると無関係な記事が上位に並ぶため、
    取得後にタイトルでキーワードを確かめる（下記 _is_relevant）。

  ・【タイトルだけで判定している理由】
    本人の方針は「キーワードが本文だけにある記事も載せる」だが、note では実現できない。
    応答の body は記事の短い抜粋で、キーワードを含まないことがほぼ無い。
    実測（2026-10-07・3キーワード × 80件 = 240件）:
        タイトルだけで判定   : RAG 13件 / Claude Code 35件 / M365 13件
        タイトル＋body で判定: RAG 13件 / Claude Code 35件 / M365 13件  ← 増加 0件
    body も見るようにしても1件も増えなかったため、判定に加えていない。
    本文を確かめるには記事を1件ずつ開く必要があり（1キーワードあたり約200回の
    追加アクセス）、週1回のツールとしても非公式APIへの負荷としても見合わない。
    → note に限り「タイトル一致」で絞る。Zenn と Qiita は検索の精度が高いので絞らない。

非公式なので、仕様変更で動かなくなることを許容する（要件5）。壊れたらこのファイルだけ直す。
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.fetcher import JsonFetch
from src.models import SITE_NOTE, Article
from src.timeutil import parse_iso
from src.wordmatch import contains_word

logger = logging.getLogger(__name__)

SEARCH_URL = "https://note.com/api/v3/searches"

# size は20が上限なので、start を 0,20,40,... と動かしてページ送りする。
PAGE_SIZE = 20

# 10ページ = 200件。広いキーワードでは6ページ（120件）で足りなかったため増やした。
# sort=hot は話題の記事を先に返すので、いいね数の多い記事は前のページに出やすく、
# 日付順の Qiita ほど打ち切りの影響は大きくない。
MAX_PAGES = 10


def _article_url(raw: dict) -> str | None:
    """note の記事 URL を組み立てる: https://note.com/<ユーザー名>/n/<記事キー>"""
    key = raw.get("key")
    user = raw.get("user") or {}
    urlname = user.get("urlname")
    if not key or not urlname:
        return None
    return f"https://note.com/{urlname}/n/{key}"


def _is_relevant(title: str, keyword: str) -> bool:
    """タイトルに本当にキーワードが入っているかを確かめる。

    note の検索はキーワードを含まない記事も多く返すため、ここで絞る。
    英数字のキーワードは語の区切りを見るので、「RAG」が「Fragrant」に当たることはない。
    """
    return contains_word(title, keyword)


def collect(keyword: str, since: datetime, fetch_json: JsonFetch) -> list[Article]:
    """キーワードに合う記事のうち、since 以降に投稿されたものを返す。"""
    articles: list[Article] = []
    seen_keys: set[str] = set()

    for page in range(MAX_PAGES):
        payload = fetch_json(
            SEARCH_URL,
            params={
                "context": "note",
                "q": keyword,
                "size": PAGE_SIZE,
                "start": page * PAGE_SIZE,
                "sort": "hot",
            },
        )
        raw_items = (((payload or {}).get("data") or {}).get("notes") or {}).get("contents") or []
        if not raw_items:
            break

        for raw in raw_items:
            key = raw.get("key")
            # sort=hot は同じ記事を別ページで返すことがあるので、ここで重ねて防ぐ。
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)

            published_at = parse_iso(raw.get("publish_at") or "")
            url = _article_url(raw)
            title = raw.get("name")
            if published_at is None or not url or not title:
                continue
            if published_at < since:
                continue
            # note の検索はゆるいので、タイトルにキーワードがあることを確かめる。
            if not _is_relevant(title, keyword):
                continue

            articles.append(
                Article(
                    title=title,
                    url=url,
                    score=int(raw.get("like_count") or 0),
                    published_at=published_at,
                    site=SITE_NOTE,
                )
            )
    else:
        logger.info(
            "note（%s）: %dページの上限まで取得しました（期間内の記事が多いキーワードです）。",
            keyword,
            MAX_PAGES,
        )

    return articles
