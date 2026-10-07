"""記事タイトルが AI 関連かどうかを判定する（要件3.2）。

判定は記事タイトルに対して行う（要件どおり）。
「単語があるか」の判定そのものは src/wordmatch.py にある。
英数字だけの単語を部分一致で探すと誤爆する理由は、そちらに書いてある。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from src.models import Article
from src.wordmatch import contains_word


def matched_words(title: str, words: Sequence[str]) -> list[str]:
    """タイトルに一致した単語を、words に書かれた順で返す。"""
    return [word for word in words if contains_word(title, word)]


def is_ai_related(title: str, words: Sequence[str]) -> bool:
    """タイトルが AI 関連かどうか。"""
    return any(contains_word(title, word) for word in words)


def text_for_matching(article: Article) -> str:
    """その記事の AI 判定に使う文字列を返す。

    ふつうはタイトル。ただし GitHub のように表示用のタイトルを短く切っている
    取得元では、切る前の全文（match_text）を使う。切ったあとの文字列で判定すると、
    落とした部分にだけ AI の単語があった記事を取りこぼす。
    """
    return article.match_text or article.title


def filter_ai_related(articles: Iterable[Article], words: Sequence[str]) -> list[Article]:
    """AI 関連の記事だけを残す。並び順は変えない。"""
    return [article for article in articles if is_ai_related(text_for_matching(article), words)]
