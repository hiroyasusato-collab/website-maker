"""表示の並び（display_order.txt）のテスト。

大事なのは次の2つ。
  ・ページに出す順番は display_order.txt で変えられる
  ・**それを変えても、重複を省く優先順（keywords.txt の順）は変わらない**
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings, load_settings
from src.models import SITE_X
from src.pipeline import TREND_HEADING, arrange_for_display, build_page
from tests.conftest import keyword_groups
from tests.test_pipeline import (
    FakeText,
    ManyArticlesJson,
    XJson,
    _keyword_sections,
    _trend,
)

KEYWORDS = ["AI駆動開発", "RAG", "Claude Code", "Claude", "ChatGPT", "M365"]

# 依頼どおりの並び（左・右・左・右…）
DISPLAY = ["M365", "ChatGPT", "RAG", "Claude", "Claude Code", "AI駆動開発"]


# ---------- 並べ替えの決まり ----------


def test_設定した順に並べ替える() -> None:
    assert arrange_for_display(KEYWORDS, DISPLAY) == DISPLAY


def test_設定が空なら元の順のまま() -> None:
    assert arrange_for_display(KEYWORDS, []) == KEYWORDS


def test_書かれていないキーワードは末尾に足す() -> None:
    """キーワードを増やして display_order.txt に書き忘れても、ページから消えない。"""
    keywords = [*KEYWORDS, "新しいキーワード", "もう1つ"]
    result = arrange_for_display(keywords, DISPLAY)

    assert result[: len(DISPLAY)] == DISPLAY
    # 末尾は keywords.txt の順。
    assert result[len(DISPLAY) :] == ["新しいキーワード", "もう1つ"]


def test_一部だけ書いても残りは末尾に来る() -> None:
    result = arrange_for_display(KEYWORDS, ["M365", "ChatGPT"])
    assert result == ["M365", "ChatGPT", "AI駆動開発", "RAG", "Claude Code", "Claude"]


def test_キーワードに無いものは無視する() -> None:
    """keywords.txt から消したキーワードが display_order.txt に残っていても落ちない。"""
    result = arrange_for_display(["RAG", "M365"], ["M365", "もう使わない語", "RAG"])
    assert result == ["M365", "RAG"]


def test_同じキーワードを2回書いても1回だけ出る() -> None:
    result = arrange_for_display(KEYWORDS, ["M365", "M365", "RAG"])
    assert result.count("M365") == 1
    assert result[:2] == ["M365", "RAG"]


def test_キーワードが1つでも落ちない() -> None:
    assert arrange_for_display(["RAG"], ["M365"]) == ["RAG"]
    assert arrange_for_display([], DISPLAY) == []


def test_並べ替えても件数は変わらない() -> None:
    """並べ替えで増えたり消えたりしないこと。"""
    result = arrange_for_display(KEYWORDS, DISPLAY)
    assert sorted(name for name in result if name is not None) == sorted(KEYWORDS)


# ---------- 実際のページでの並び ----------


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "keywords": keyword_groups("Claude Code", "RAG", "M365"),
        "trend_words": ["AI", "Claude", "RAG", "M365"],
        "output_dir": tmp_path / "docs",
        "qiita_token": None,
        "hatena_min_users": 10,
        "max_per_site": 0,
        "display_order": ["M365", "RAG", "Claude Code"],
    }
    values.update(overrides)
    return Settings(**values)


def test_ページが設定した順に並ぶ(tmp_path: Path, reference: datetime) -> None:
    page = build_page(_settings(tmp_path), ManyArticlesJson(), FakeText(), reference)
    assert [s.heading for s in _keyword_sections(page)] == ["M365", "RAG", "Claude Code"]


class OneArticleJson(ManyArticlesJson):
    """どのキーワードでも同じ1件だけを返す偽の取得関数。

    1件しか無いので「どのセクションに載るか」で優先順がはっきり分かる。
    """

    def __call__(self, url: str, **kwargs: Any) -> Any:
        from src.sources import note_com, qiita, zenn

        params = kwargs.get("params", {})
        if url == zenn.SEARCH_URL:
            if params.get("page") != 1:
                return {"articles": []}
            return {
                "articles": [
                    {
                        "title": "Claude Code と RAG と M365 の記事",
                        "path": "/u/articles/only-one",
                        "published_at": "2026-10-05T12:00:00.000+09:00",
                        "liked_count": 50,
                    }
                ]
            }
        if url == qiita.ITEMS_URL:
            return []
        if url == note_com.SEARCH_URL:
            return {"data": {"notes": {"contents": []}}}
        return super().__call__(url, **kwargs)


def test_並べ替えても優先順は変わらない(tmp_path: Path, reference: datetime) -> None:
    """一番大事なテスト。

    同じ記事が複数のキーワードに該当したとき、載るのは keywords.txt で先のセクション
    （ここでは Claude Code）。display_order.txt で M365 を先に表示しても変わらない。
    """
    settings = _settings(tmp_path)  # 表示順は M365 → RAG → Claude Code
    page = build_page(settings, OneArticleJson(), FakeText(), reference)
    by_heading = {s.heading: s for s in _keyword_sections(page)}

    # keywords.txt の先頭は Claude Code。1件しか無いのでそこにだけ載る。
    assert len(by_heading["Claude Code"].rankings[0].articles) == 1
    assert by_heading["RAG"].rankings[0].articles == []
    assert by_heading["M365"].rankings[0].articles == []

    # 表示は M365 が先頭（＝並べ替えは効いている）。
    assert _keyword_sections(page)[0].heading == "M365"


def test_表示順を逆にしても優先順は変わらない(tmp_path: Path, reference: datetime) -> None:
    """表示順を入れ替えても、記事が載るセクションは Claude Code のまま。"""
    for display in (
        ["M365", "RAG", "Claude Code"],
        ["Claude Code", "RAG", "M365"],
        [],
    ):
        settings = _settings(tmp_path, display_order=display)
        page = build_page(settings, OneArticleJson(), FakeText(), reference)
        by_heading = {s.heading: s for s in _keyword_sections(page)}

        assert len(by_heading["Claude Code"].rankings[0].articles) == 1, f"display={display}"
        assert by_heading["M365"].rankings[0].articles == [], f"display={display}"


def test_優先順が高いセクションにいいね数の多い記事が載る(
    tmp_path: Path, reference: datetime
) -> None:
    """記事がたくさんある場合も、優先順の高いセクションから順に取っていく。

    ManyArticlesJson は note（いいね数が最大）・Zenn・Qiita で各10件返す。
    keywords.txt の先頭 Claude Code が note の10件を取り、
    表示が先頭の M365 は一番いいね数の少ない Qiita の10件になる。
    """
    settings = _settings(tmp_path)
    page = build_page(settings, ManyArticlesJson(), FakeText(), reference)
    by_heading = {s.heading: s for s in _keyword_sections(page)}

    top = by_heading["Claude Code"].rankings[0].articles
    bottom = by_heading["M365"].rankings[0].articles

    assert min(a.score for a in top) > max(a.score for a in bottom)


def test_表示順を変えても載る記事は同じ(tmp_path: Path, reference: datetime) -> None:
    """表示順だけ違う2つの設定で、各セクションの記事が一致すること。"""

    def articles_by_heading(display_order: list[str]) -> dict[str, list[str]]:
        settings = _settings(tmp_path, display_order=display_order)
        page = build_page(settings, ManyArticlesJson(), FakeText(), reference)
        return {s.heading: [a.url for a in s.rankings[0].articles] for s in _keyword_sections(page)}

    forward = articles_by_heading(["Claude Code", "RAG", "M365"])
    reverse = articles_by_heading(["M365", "RAG", "Claude Code"])
    assert forward == reverse


def test_設定が空ならkeywordsの順で出る(tmp_path: Path, reference: datetime) -> None:
    settings = _settings(tmp_path, display_order=[])
    page = build_page(settings, ManyArticlesJson(), FakeText(), reference)
    assert [s.heading for s in _keyword_sections(page)] == ["Claude Code", "RAG", "M365"]


def test_設定に無いキーワードはページの末尾に出る(tmp_path: Path, reference: datetime) -> None:
    settings = _settings(tmp_path, display_order=["M365"])
    page = build_page(settings, ManyArticlesJson(), FakeText(), reference)
    headings = [s.heading for s in _keyword_sections(page)]

    assert headings[0] == "M365"
    # 残りは keywords.txt の順。
    assert headings[1:] == ["Claude Code", "RAG"]


# ---------- AI業界トレンドの並び ----------


def test_トレンドの表の並びは固定(tmp_path: Path, reference: datetime) -> None:
    """はてブ → HN → X（日本語）→ X（英語）の順。display_order.txt の対象外。"""
    settings = _settings(tmp_path, x_enabled=True, x_bearer_token="dummy-token", x_max_posts=400)
    page = build_page(settings, XJson(), FakeText(), reference)

    captions = [r.caption or "" for r in _trend(page).rankings]
    assert len(captions) == 4
    assert "はてなブックマーク" in captions[0]
    assert "Hacker News" in captions[1]
    assert "日本語" in captions[2]
    assert "英語" in captions[3]


def test_Xを止めるとXの行ごと消える(tmp_path: Path, reference: datetime) -> None:
    settings = _settings(tmp_path, x_enabled=False)
    page = build_page(settings, XJson(), FakeText(), reference)

    captions = [r.caption or "" for r in _trend(page).rankings]
    assert len(captions) == 2, "はてブと HN の2つだけ"
    assert not any(SITE_X in c for c in captions)


# ---------- 設定ファイルの読み込み ----------


def test_設定ファイルが無くても動く(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """display_order.txt は無くても動く（keywords.txt の順になる）。"""
    (tmp_path / "keywords.txt").write_text("RAG\n", encoding="utf-8")
    (tmp_path / "ai_trend_words.txt").write_text("AI\n", encoding="utf-8")
    monkeypatch.delenv("X_MAX_POSTS", raising=False)

    settings = load_settings(
        tmp_path / "keywords.txt",
        tmp_path / "ai_trend_words.txt",
        tmp_path / "docs",
        tmp_path / "ない.txt",
    )
    assert settings.display_order == []


def test_設定ファイルの中身が空でも動く(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "keywords.txt").write_text("RAG\n", encoding="utf-8")
    (tmp_path / "ai_trend_words.txt").write_text("AI\n", encoding="utf-8")
    (tmp_path / "display_order.txt").write_text("# コメントだけ\n\n", encoding="utf-8")
    monkeypatch.delenv("X_MAX_POSTS", raising=False)

    settings = load_settings(
        tmp_path / "keywords.txt",
        tmp_path / "ai_trend_words.txt",
        tmp_path / "docs",
        tmp_path / "display_order.txt",
    )
    assert settings.display_order == []


def test_設定ファイルを読める(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "keywords.txt").write_text("RAG\nM365\n", encoding="utf-8")
    (tmp_path / "ai_trend_words.txt").write_text("AI\n", encoding="utf-8")
    # メモ帳で保存したとき（BOM付き）でも読めること。
    (tmp_path / "display_order.txt").write_text("# 並び\nM365\nRAG\n", encoding="utf-8-sig")
    monkeypatch.delenv("X_MAX_POSTS", raising=False)

    settings = load_settings(
        tmp_path / "keywords.txt",
        tmp_path / "ai_trend_words.txt",
        tmp_path / "docs",
        tmp_path / "display_order.txt",
    )
    assert settings.display_order == ["M365", "RAG"]


def test_同梱の設定ファイルがkeywordsと合っている() -> None:
    """display_order.txt と keywords.txt の中身がそろっていることを確かめる。"""
    from src.config import DISPLAY_ORDER_FILE, KEYWORDS_FILE, read_display_order, read_keywords

    names = [group.name for group in read_keywords(KEYWORDS_FILE)]
    display = read_display_order(DISPLAY_ORDER_FILE)

    # 「（空き）」（None）を除くと、両方のファイルに同じ表の名前が並ぶこと。
    assert sorted(n for n in display if n is not None) == sorted(names)

    # 依頼どおりの表示の並びになっていること（None は表を置かない位置）。
    assert display == [
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

    # 優先順（keywords.txt）は依頼どおり。
    assert names == [
        "AI駆動開発",
        "RAG・ナレッジグラフ",
        "Claude Code",
        "Codex",
        "Claude",
        "ChatGPT",
        "M365",
        "AIエージェント",
    ]


def test_同梱のkeywordsでRAGとナレッジグラフが1つの表になる() -> None:
    """1行にカンマで並べた単語が、1つの表（まとまり）として読めること。"""
    from src.config import KEYWORDS_FILE, read_keywords

    groups = {group.name: group.words for group in read_keywords(KEYWORDS_FILE)}
    assert groups["RAG・ナレッジグラフ"] == ("RAG", "ナレッジグラフ")
    # 1単語だけの行は、その単語だけで検索する。
    assert groups["M365"] == ("M365",)


def test_セクションの見出しは重複しない() -> None:
    """同じキーワードを2回書いても、セクションが二重に出ないこと。"""
    assert arrange_for_display(["RAG"], ["RAG", "RAG"]) == ["RAG"]


def test_トレンドの見出しは変わらない(tmp_path: Path, reference: datetime) -> None:
    page = build_page(_settings(tmp_path), ManyArticlesJson(), FakeText(), reference)
    assert _trend(page).heading == TREND_HEADING
