"""「文字列の中にその単語があるか」の判定。

AI判定（trend_filter）と、note の検索結果の絞り込み（sources/note_com）の両方で使う。

英数字だけの単語を単純な部分一致で探すと、まったく関係ない記事を拾ってしまう。
2026-10-07 に実際に確認した例:

    "AI"  → JetBr"ai"ns / B"ah"r"ai"n / p"ai"nt / s"ai"d
    "RAG" → "F"rag"rant"（note が「RAG」の検索結果として返してきた）

そこで英数字だけの単語は「前後が英数字でないときだけ一致」とする。
ただしそれだけでは複数形（Agents / LLMs）を取りこぼすので、末尾の s・es を許す。
日本語を含む単語は区切りが無いので、単純な部分一致で判定する。
"""

from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=512)
def _ascii_pattern(word: str) -> re.Pattern[str]:
    """英数字だけの単語用の、語の区切りを見る正規表現。

    (?<![A-Za-z0-9]) … 直前が英数字でない
    (?:es|s)?        … 末尾の複数形を許す（Agent → Agents、LLM → LLMs）
    (?![A-Za-z0-9])  … 直後が英数字でない
    """
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(word)}(?:es|s)?(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def contains_word(text: str, word: str) -> bool:
    """text の中に word があるか。

    word が英数字だけなら語の区切りを見て、日本語を含むなら部分一致で判定する。
    """
    if not text or not word:
        return False
    if word.isascii():
        return _ascii_pattern(word).search(text) is not None
    return word.lower() in text.lower()
