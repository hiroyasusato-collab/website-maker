"""1行に複数の単語を書いたキーワード（例：RAG・ナレッジグラフ）と、
「表を置かない位置（（空き））」のテスト。実際のサイトにはつながない。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import Settings
from src.models import KIND_GAP, KIND_KEYWORD, KIND_RESOURCES, KIND_TREND
from src.pipeline import build_page
from src.sources import note_com, qiita, zenn
from tests.conftest import keyword_groups
from tests.test_pipeline import TREND_WORDS, FakeJson, FakeText, _keyword_sections


def _settings(tmp_path: Path, *lines: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "keywords": keyword_groups(*(lines or ("Claude Code",))),
        "trend_words": TREND_WORDS,
        "output_dir": tmp_path / "docs",
        "qiita_token": None,
        "hatena_min_users": 10,
        "max_per_site": 0,
    }
    values.update(overrides)
    return Settings(**values)


class OneZennArticlePerWord(FakeJson):
    """Zenn が「検索した単語の名前が入った記事」を1件だけ返す偽の取得関数。

    どちらの単語の記事が表に入ったかが分かるようにしている。
    """

    def __call__(self, url: str, **kwargs: Any) -> Any:
        params = kwargs.get("params", {})
        if url == zenn.SEARCH_URL:
            if params.get("page") != 1:
                return {"articles": []}
            word = params["q"]
            return {
                "articles": [
                    {
                        "title": f"{word} の記事",
                        "path": f"/u/articles/{word}",
                        "published_at": "2026-10-05T12:00:00.000+09:00",
                        # ナレッジグラフ側のいいね数を多くして、並び順を確かめる。
                        "liked_count": 10 if word == "RAG" else 20,
                    }
                ]
            }
        if url == qiita.ITEMS_URL:
            return []
        if url == note_com.SEARCH_URL:
            return {"data": {"notes": {"contents": []}}}
        return super().__call__(url, **kwargs)


# ---------- 単語ごとに検索して1つの表にまとめる ----------


def test_まとまりの単語ごとに検索する(tmp_path: Path, reference: datetime) -> None:
    """1行に2語あるときは、2語とも検索する。"""
    queries: list[str] = []

    class CapturingJson(FakeJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            if url == zenn.SEARCH_URL:
                queries.append(kwargs["params"]["q"])
            return super().__call__(url, **kwargs)

    page = build_page(
        _settings(tmp_path, "RAG, ナレッジグラフ"), CapturingJson(), FakeText(), reference
    )

    assert "RAG" in queries
    assert "ナレッジグラフ" in queries
    # 表は1つにまとまる。
    assert [s.heading for s in _keyword_sections(page)] == ["RAG・ナレッジグラフ"]


def test_どちらの単語の記事も同じ表に並ぶ(tmp_path: Path, reference: datetime) -> None:
    page = build_page(
        _settings(tmp_path, "RAG, ナレッジグラフ"), OneZennArticlePerWord(), FakeText(), reference
    )
    titles = [a.title for a in _keyword_sections(page)[0].rankings[0].articles]

    assert titles == ["ナレッジグラフ の記事", "RAG の記事"], "いいね数の多い順に1つの表へ"


def test_1単語だけの行は従来どおり1回だけ検索する(tmp_path: Path, reference: datetime) -> None:
    queries: list[str] = []

    class CapturingJson(FakeJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            if url == zenn.SEARCH_URL and kwargs["params"]["page"] == 1:
                queries.append(kwargs["params"]["q"])
            return super().__call__(url, **kwargs)

    build_page(_settings(tmp_path, "M365"), CapturingJson(), FakeText(), reference)
    assert queries == ["M365"]


def test_片方の単語で失敗しても他の単語の記事は出る(tmp_path: Path, reference: datetime) -> None:
    """1語の取得が失敗しても、同じ表のもう1語の記事は残る（要件5）。"""

    class FailOneWord(OneZennArticlePerWord):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            if url == zenn.SEARCH_URL and kwargs["params"]["q"] == "RAG":
                raise RuntimeError("RAG の検索に失敗")
            return super().__call__(url, **kwargs)

    page = build_page(
        _settings(tmp_path, "RAG, ナレッジグラフ"), FailOneWord(), FakeText(), reference
    )
    ranking = _keyword_sections(page)[0].rankings[0]

    assert [a.title for a in ranking.articles] == ["ナレッジグラフ の記事"]
    assert any("RAG" in note for note in ranking.notes), "失敗した単語が分かること"


def test_まとまりも重複を省く優先順の対象になる(tmp_path: Path, reference: datetime) -> None:
    """同じ記事が2つの表に当たったら、keywords.txt で先の表にだけ載る。"""

    class SameArticleForAnyWord(FakeJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            params = kwargs.get("params", {})
            if url == zenn.SEARCH_URL:
                if params.get("page") != 1:
                    return {"articles": []}
                return {
                    "articles": [
                        {
                            "title": "RAG とナレッジグラフと Claude の記事",
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

    # keywords.txt の順＝優先順。まとまりが先に書かれている。
    settings = _settings(tmp_path, "RAG, ナレッジグラフ", "Claude")
    page = build_page(settings, SameArticleForAnyWord(), FakeText(), reference)
    by_heading = {s.heading: s for s in _keyword_sections(page)}

    assert len(by_heading["RAG・ナレッジグラフ"].rankings[0].articles) == 1
    assert by_heading["Claude"].rankings[0].articles == []


# ---------- 表を置かない位置（（空き）） ----------


def test_空きがセクションの並びに入る(tmp_path: Path, reference: datetime) -> None:
    settings = _settings(tmp_path, "M365", "ChatGPT", display_order=["M365", None, "ChatGPT"])
    page = build_page(settings, FakeJson(), FakeText(), reference)

    # トレンド → 技術資料 → M365 → 空き → ChatGPT
    assert [s.kind for s in page.sections] == [
        KIND_TREND,
        KIND_RESOURCES,
        KIND_KEYWORD,
        KIND_GAP,
        KIND_KEYWORD,
    ]
    assert [s.heading for s in _keyword_sections(page)] == ["M365", "ChatGPT"]


def test_空きがあっても記事の載り方は変わらない(tmp_path: Path, reference: datetime) -> None:
    """「（空き）」は見た目だけの指定。どの表にどの記事が載るかは変わらない。"""

    def articles_by_heading(display_order: list[str | None]) -> dict[str, list[str]]:
        settings = _settings(tmp_path, "M365", "ChatGPT", display_order=display_order)
        page = build_page(settings, FakeJson(), FakeText(), reference)
        return {s.heading: [a.url for a in s.rankings[0].articles] for s in _keyword_sections(page)}

    assert articles_by_heading(["M365", "ChatGPT"]) == articles_by_heading(
        ["M365", None, "ChatGPT"]
    )


def test_空きしか書いていなければキーワードは末尾に出る(
    tmp_path: Path, reference: datetime
) -> None:
    """display_order.txt に表の名前を書き忘れても、ページから消えない。"""
    settings = _settings(tmp_path, "M365", "ChatGPT", display_order=[None, None])
    page = build_page(settings, FakeJson(), FakeText(), reference)

    assert [s.heading for s in _keyword_sections(page)] == ["M365", "ChatGPT"]
