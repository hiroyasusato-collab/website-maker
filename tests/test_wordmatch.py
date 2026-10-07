"""単語の一致判定のテスト。

AI判定（trend_filter）と note の絞り込み（sources/note_com）の土台なので、
ここが壊れると両方の結果が崩れる。
"""

from __future__ import annotations

import pytest

from src.wordmatch import contains_word


# 実際に誤爆したもの。単語の中の一部に反応してはいけない。
@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("JetBrains reports revenue growth", "AI"),
        ("frustrated by Bahrain F1 glitch", "AI"),
        ("a simulated paint canvas", "AI"),
        ("You said no", "AI"),
        ("Pretraining without backpropagation", "AI"),
        ("Thailand raises the wage", "AI"),
        # note が「RAG」の検索結果として返してきたもの
        ("Day⑦｜金木犀Fragrant Olive", "RAG"),
        ("storage and fragments", "RAG"),
        # 数字とくっついている場合
        ("AI2027 についての考察", "AI2027x"),
        ("M3650 の話", "M365"),
    ],
)
def test_単語の一部には反応しない(text: str, word: str) -> None:
    assert not contains_word(text, word), f"誤爆: {word} <- {text}"


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("AI is changing software", "AI"),
        ("the ai boom", "AI"),  # 大文字小文字を区別しない
        ("AI-powered search", "AI"),  # ハイフン区切り
        ("What about (AI)?", "AI"),  # 括弧区切り
        ("AI: the next decade", "AI"),  # 記号区切り
        ("RAG の構成を見直す", "RAG"),  # 日本語に挟まれた英単語
        ("M365の保持期間", "M365"),
        ("Claude Codeの使い方", "Claude Code"),
        ("I quit OpenAI", "OpenAI"),
        # 複数形
        ("Agents don't need memory", "Agent"),
        ("LLMs are getting cheaper", "LLM"),
        ("the boxes are here", "box"),
    ],
)
def test_一致すべきものに一致する(text: str, word: str) -> None:
    assert contains_word(text, word), f"取りこぼし: {word} <- {text}"


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("いま話題の生成AIというもの", "生成AI"),
        ("機械学習の基礎", "機械学習"),
        ("AI駆動開発をやってみた", "AI駆動開発"),
    ],
)
def test_日本語の単語は部分一致で判定する(text: str, word: str) -> None:
    """日本語は単語の区切りが無いので、前後に文字があっても一致とみなす。"""
    assert contains_word(text, word)


def test_日本語の単語が無ければ一致しない() -> None:
    assert not contains_word("機械の学習について", "機械学習")


@pytest.mark.parametrize(
    ("text", "word"),
    [("", "AI"), ("AI", ""), ("", "")],
)
def test_空の入力で落ちない(text: str, word: str) -> None:
    assert not contains_word(text, word)


def test_正規表現の記号を含む単語でも落ちない() -> None:
    """C++ や .NET のような単語を設定ファイルに書かれても壊れないこと。"""
    assert contains_word("C++ の話", "C++")
    assert contains_word("ASP.NET Core", "ASP.NET")
    assert not contains_word("まったく別の話", "C++")
