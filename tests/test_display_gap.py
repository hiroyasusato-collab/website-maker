"""並べ替えの決まりのうち、「表を置かない位置（（空き））」の扱いのテスト。"""

from __future__ import annotations

from src.pipeline import arrange_for_display

KEYWORDS = [
    "AI駆動開発",
    "RAG・ナレッジグラフ",
    "Claude Code",
    "Codex",
    "Claude",
    "ChatGPT",
    "M365",
    "AIエージェント",
]

# 依頼どおりの並び（左・右・左・右…／None は表を置かない位置）
DISPLAY: list[str | None] = [
    "M365",
    "RAG・ナレッジグラフ",
    "AIエージェント",
    None,
    "ChatGPT",
    "Codex",
    "Claude",
    "Claude Code",
    "AI駆動開発",
    None,
]


def test_依頼どおりの並びになる() -> None:
    """末尾の「（空き）」は見た目に影響しないので落ちる。"""
    assert arrange_for_display(KEYWORDS, DISPLAY) == DISPLAY[:-1]


def test_空きはそのままの位置に残る() -> None:
    result = arrange_for_display(["M365", "ChatGPT"], ["M365", None, "ChatGPT"])
    assert result == ["M365", None, "ChatGPT"]


def test_空きを何個でも置ける() -> None:
    result = arrange_for_display(["M365", "ChatGPT"], ["M365", None, None, "ChatGPT"])
    assert result == ["M365", None, None, "ChatGPT"]


def test_末尾の空きは落とす() -> None:
    """ページの一番下に空の枠が残らないようにする。"""
    assert arrange_for_display(["M365"], ["M365", None, None]) == ["M365"]


def test_空きだけでも落ちない() -> None:
    assert arrange_for_display([], [None, None]) == []
    # 先頭の空きは指定どおり残す（左列を空けて右列から始めたい場合）。
    assert arrange_for_display(["M365"], [None]) == [None, "M365"]


def test_空きがあっても書き忘れたキーワードは末尾に足す() -> None:
    result = arrange_for_display(["M365", "ChatGPT", "Codex"], ["M365", None])
    # 空きのあと、keywords.txt の順で残りが続く。
    assert result == ["M365", None, "ChatGPT", "Codex"]


def test_空きは件数に数えない() -> None:
    """並べ替えでキーワードが増えたり消えたりしないこと。"""
    result = arrange_for_display(KEYWORDS, DISPLAY)
    assert sorted(name for name in result if name is not None) == sorted(KEYWORDS)
