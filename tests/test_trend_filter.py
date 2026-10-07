"""AI 判定のテスト。

このファイルが一番大事。2026-10-07 に実際の Hacker News タイトル100件で検証したとき、
単純な部分一致では半分が誤爆だった。その誤爆を二度と出さないための歯止めにする。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.models import SITE_HACKER_NEWS, Article
from src.timeutil import JST
from src.trend_filter import filter_ai_related, is_ai_related, matched_words

WORDS = [
    "AI",
    "LLM",
    "GPT",
    "Claude",
    "Gemini",
    "生成AI",
    "エージェント",
    "Agent",
    "OpenAI",
    "ChatGPT",
    "xAI",
    "Anthropic",
    "Mistral",
    "機械学習",
    "大規模言語モデル",
    "Transformer",
]


# 実際に誤爆したタイトル。単語の中の "ai" に反応してはいけない。
@pytest.mark.parametrize(
    "title",
    [
        "JetBrains reports revenue growth, net financial loss for 2025",
        "Powerless F1 drivers frustrated by Bahrain F1 software glitch",
        "Show HN: Giving a simulated paint canvas",
        "You said no to the proposal",
        "Retraining staff on the new email system",
        "Thailand raises the minimum wage",
        "A chair, a table and a detail",
    ],
)
def test_単語の中のaiに反応しない(title: str) -> None:
    assert not is_ai_related(title, WORDS), f"誤爆: {title}"


# 語の区切りを見る方式で取りこぼしがちなもの。拾えなければいけない。
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # 複数形
        ("Agents don't need memory, they need documentation", "Agent"),
        ("LLMs are getting cheaper", "LLM"),
        # 他の語に埋め込まれた形 → 単語リストに明示してあるので拾える
        ("I quit OpenAI because its culture is broken", "OpenAI"),
        ("Sites in ChatGPT", "ChatGPT"),
        ("xAI announces a new datacenter", "xAI"),
        # ふつうの一致
        ("AI is changing software", "AI"),
        ("Mistral Large 4", "Mistral"),
        ("Dust: Pretraining Transformers Without Backpropagation", "Transformer"),
        # 記号で区切られていても語の区切りとみなす
        ("AI-powered search is here", "AI"),
        ("What about (AI)?", "AI"),
        ("AI: the next decade", "AI"),
    ],
)
def test_拾うべきタイトルを拾う(title: str, expected: str) -> None:
    assert expected in matched_words(title, WORDS), f"取りこぼし: {title}"


@pytest.mark.parametrize(
    "title",
    [
        "生成AIの使いどころを整理する",
        "機械学習の基礎をおさらいする",
        "大規模言語モデルの評価方法",
        "AIエージェントに任せる仕事",
        "Claudeを業務に入れてみた",
    ],
)
def test_日本語のタイトルを拾う(title: str) -> None:
    assert is_ai_related(title, WORDS), f"取りこぼし: {title}"


def test_日本語の単語は部分一致で判定する() -> None:
    # 日本語は単語の区切りが無いので、前後に文字があっても拾う。
    assert is_ai_related("いま話題の生成AIというもの", ["生成AI"])


def test_大文字小文字を区別しない() -> None:
    assert is_ai_related("the ai boom", WORDS)
    assert is_ai_related("Claude and claude", ["Claude"])


def test_一致した単語は設定ファイルの順で返る() -> None:
    # WORDS では AI が GPT より先に書かれている。
    assert matched_words("AI and GPT", WORDS) == ["AI", "GPT"]


def test_空のタイトルや空の単語で落ちない() -> None:
    assert matched_words("", WORDS) == []
    assert matched_words("AI", []) == []
    assert matched_words("AI", ["", "AI"]) == ["AI"]


def _article(title: str) -> Article:
    return Article(
        title=title,
        url=f"https://example.com/{abs(hash(title))}",
        score=1,
        published_at=datetime(2026, 10, 5, tzinfo=JST),
        site=SITE_HACKER_NEWS,
    )


def test_記事の絞り込みは並び順を変えない() -> None:
    articles = [
        _article("Mistral Large 4"),
        _article("Powerless F1 drivers frustrated by Bahrain glitch"),
        _article("Agents don't need memory"),
        _article("A chair and a table"),
    ]
    result = filter_ai_related(articles, WORDS)
    assert [a.title for a in result] == ["Mistral Large 4", "Agents don't need memory"]
