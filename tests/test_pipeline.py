"""ページ組み立て全体のテスト。実際の Web サイトにはつながない。

とくに要件5「どれか1つの取得元が失敗しても、他の取得元のセクションは表示される」を
重点的に確かめる。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.models import (
    LABEL_BOOKMARKS,
    LABEL_LIKES,
    LABEL_POINTS,
    SITE_NOTE,
    SITE_QIITA,
    SITE_X,
    SITE_ZENN,
)
from src.pipeline import TREND_HEADING, build_page
from src.sources import hackernews, note_com, qiita, x_posts, zenn
from tests.conftest import load_fixture_json, load_fixture_text

EMPTY_RSS = '<?xml version="1.0" encoding="UTF-8"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"></rdf:RDF>'  # noqa: E501

TREND_WORDS = ["AI", "LLM", "GPT", "Claude", "OpenAI", "ChatGPT", "Mistral", "Agent", "生成AI"]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        keywords=["Claude Code", "RAG"],
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        # 0 = 上限なし。ここまでのテストの期待値を変えないため。
        max_per_site=0,
    )


class FakeJson:
    """URL を見て、その取得元向けの応答を返す偽の取得関数。

    fail に入れた URL は例外を投げる（取得元が落ちた状況を作る）。
    """

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[str] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)
        if url in self.fail:
            raise RuntimeError(f"{url} に接続できません")
        # 2ページ目以降は空にして、ページ送りを1回で終わらせる。
        page = kwargs.get("params", {}).get("page")
        start = kwargs.get("params", {}).get("start")
        if url == zenn.SEARCH_URL:
            return load_fixture_json("zenn_search.json") if page == 1 else {"articles": []}
        if url == qiita.ITEMS_URL:
            return load_fixture_json("qiita_items.json") if page == 1 else []
        if url == note_com.SEARCH_URL:
            if start == 0:
                return load_fixture_json("note_searches.json")
            return {"data": {"notes": {"contents": []}}}
        if url == hackernews.SEARCH_URL:
            return load_fixture_json("hn_search.json") if page == 0 else {"hits": []}
        raise AssertionError(f"知らない URL: {url}")


class FakeText:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, url: str, **kwargs: Any) -> str:
        self.calls.append(url)
        if self.fail:
            raise RuntimeError("はてブに接続できません")
        page = kwargs.get("params", {}).get("page")
        return load_fixture_text("hatena_search.rss") if page == 1 else EMPTY_RSS


def _trend(page: Any) -> Any:
    """AI業界トレンドのセクションを取り出す（ページ上の位置に依存しない）。"""
    return next(s for s in page.sections if s.is_trend)


def _keyword_sections(page: Any) -> list[Any]:
    """キーワード別セクションを、ページに出る順で取り出す。"""
    return [s for s in page.sections if not s.is_trend]


# ---------- ページの形 ----------


def test_AI業界トレンドが先に出る(settings: Settings, reference: datetime) -> None:
    """ページの並びは AI業界トレンド → キーワード別。"""
    page = build_page(settings, FakeJson(), FakeText(), reference)
    assert page.sections[0].heading == TREND_HEADING
    assert page.sections[0].is_trend is True


def test_キーワード別セクションが並ぶ(settings: Settings, reference: datetime) -> None:
    """display_order.txt を指定していなければ keywords.txt の順に並ぶ。"""
    page = build_page(settings, FakeJson(), FakeText(), reference)
    assert [s.heading for s in _keyword_sections(page)] == ["Claude Code", "RAG"]
    assert all(s.is_trend is False for s in _keyword_sections(page))


def test_集めた期間が実行日を含む7日間になる(settings: Settings, reference: datetime) -> None:
    page = build_page(settings, FakeJson(), FakeText(), reference)
    # 実行日 2026-10-07 を含めた7日間 → 2026-10-01 から
    assert page.period_start.isoformat() == "2026-10-01"
    assert page.target_date.isoformat() == "2026-10-07"


def test_キーワードセクションは3つの取得元から集める(
    settings: Settings, reference: datetime
) -> None:
    page = build_page(settings, FakeJson(), FakeText(), reference)
    ranking = _keyword_sections(page)[0].rankings[0]
    assert ranking.score_label == LABEL_LIKES
    sites = {a.site for a in ranking.articles}
    assert sites == {SITE_ZENN, SITE_QIITA, "note"}


def test_キーワードセクションはいいね数順になる(settings: Settings, reference: datetime) -> None:
    page = build_page(settings, FakeJson(), FakeText(), reference)
    scores = [a.score for a in _keyword_sections(page)[0].rankings[0].articles]
    assert scores == sorted(scores, reverse=True)


def test_トレンドセクションは2つの表に分かれる(settings: Settings, reference: datetime) -> None:
    """はてブとHNは数え方が違うので混ぜない（要件3.2）。"""
    page = build_page(settings, FakeJson(), FakeText(), reference)
    trend = _trend(page)
    assert len(trend.rankings) == 2
    assert trend.rankings[0].score_label == LABEL_BOOKMARKS
    assert trend.rankings[1].score_label == LABEL_POINTS
    # どちらの表にも相手のサイトの記事が混ざっていないこと。
    assert {a.site for a in trend.rankings[0].articles} <= {"はてなブックマーク"}
    assert {a.site for a in trend.rankings[1].articles} <= {"Hacker News"}


def test_トレンドセクションはAI以外のタイトルを落とす(
    settings: Settings, reference: datetime
) -> None:
    page = build_page(settings, FakeJson(), FakeText(), reference)
    titles = [a.title for r in _trend(page).rankings for a in r.articles]

    # 実際に誤爆したタイトルが入っていないこと。
    assert not any("JetBrains" in t for t in titles)
    assert not any("Bahrain" in t for t in titles)
    assert not any("Ghostty" in t for t in titles)
    # AI 関連は入っていること。
    assert any("Mistral" in t for t in titles)
    assert any("OpenAI" in t for t in titles)


def test_トレンドセクションもスコア順になる(settings: Settings, reference: datetime) -> None:
    page = build_page(settings, FakeJson(), FakeText(), reference)
    for ranking in _trend(page).rankings:
        scores = [a.score for a in ranking.articles]
        assert scores == sorted(scores, reverse=True)


# ---------- 1サイトあたりの上限 ----------


class ManyArticlesJson:
    """Zenn・Qiita・note がそれぞれ10件返す偽の取得関数。

    note のいいね数を一番大きくして、note が独占しようとする状況を作る。
    """

    def __call__(self, url: str, **kwargs: Any) -> Any:
        params = kwargs.get("params", {})
        page = params.get("page")
        start = params.get("start")

        if url == zenn.SEARCH_URL:
            if page != 1:
                return {"articles": []}
            return {
                "articles": [
                    {
                        "title": f"Claude Code zenn{i}",
                        "path": f"/u/articles/zenn{i}",
                        "published_at": "2026-10-05T12:00:00.000+09:00",
                        "liked_count": 100 - i,
                    }
                    for i in range(10)
                ]
            }
        if url == qiita.ITEMS_URL:
            if page != 1:
                return []
            return [
                {
                    "title": f"Claude Code qiita{i}",
                    "url": f"https://qiita.com/u/items/{i:032d}",
                    "likes_count": 50 - i,
                    "created_at": "2026-10-05T12:00:00+09:00",
                }
                for i in range(10)
            ]
        if url == note_com.SEARCH_URL:
            if start != 0:
                return {"data": {"notes": {"contents": []}}}
            return {
                "data": {
                    "notes": {
                        "contents": [
                            {
                                "name": f"Claude Code note{i}",
                                "key": f"n{i:012d}",
                                "publish_at": "2026-10-05T12:00:00.000+09:00",
                                # note のいいね数を一番大きくする。
                                "like_count": 1000 - i,
                                "user": {"urlname": "someone"},
                            }
                            for i in range(10)
                        ]
                    }
                }
            }
        if url == hackernews.SEARCH_URL:
            return load_fixture_json("hn_search.json") if page == 0 else {"hits": []}
        raise AssertionError(f"知らない URL: {url}")


def _site_counts(articles: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for article in articles:
        counts[article.site] = counts.get(article.site, 0) + 1
    return counts


def test_1サイトの上限が効く(tmp_path: Path, reference: datetime) -> None:
    """note がいいね数で上位を占めても、4件までに抑えて他のサイトを拾う。"""
    settings = Settings(
        keywords=["Claude Code"],
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=4,
    )
    page = build_page(settings, ManyArticlesJson(), FakeText(), reference)
    articles = _keyword_sections(page)[0].rankings[0].articles

    assert len(articles) == 10
    counts = _site_counts(articles)
    assert counts[SITE_NOTE] == 4, "note は上限の4件まで"
    assert counts[SITE_ZENN] == 4
    assert counts[SITE_QIITA] == 2
    # いいね数順は保たれている。
    scores = [a.score for a in articles]
    assert scores == sorted(scores, reverse=True)


def test_上限なしならnoteが独占する(tmp_path: Path, reference: datetime) -> None:
    """上限を入れる前の動き。この偏りを直すための変更であることを示す。"""
    settings = Settings(
        keywords=["Claude Code"],
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=0,
    )
    page = build_page(settings, ManyArticlesJson(), FakeText(), reference)
    articles = _keyword_sections(page)[0].rankings[0].articles
    assert _site_counts(articles) == {SITE_NOTE: 10}


def test_上限はAI業界トレンドセクションには効かない(tmp_path: Path, reference: datetime) -> None:
    """はてブ TOP10 と HN TOP10 はそれぞれ別の表なので対象外（要件のとおり）。

    1つの表の記事は全部同じサイトなので、上限が効いてしまうと4件に削られる。
    """
    settings = Settings(
        keywords=["Claude Code"],
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=4,
    )

    class ManyHnJson(ManyArticlesJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            if url == hackernews.SEARCH_URL:
                if kwargs.get("params", {}).get("page") != 0:
                    return {"hits": []}
                # AI 関連の投稿を6件返す（上限4件より多い）。
                return {
                    "hits": [
                        {
                            "objectID": str(i),
                            "title": f"AI breakthrough {i}",
                            "url": f"https://example.com/hn{i}",
                            "points": 100 - i,
                            "created_at_i": 1791292549,
                        }
                        for i in range(6)
                    ]
                }
            return super().__call__(url, **kwargs)

    page = build_page(settings, ManyHnJson(), FakeText(), reference)
    hn_articles = _trend(page).rankings[1].articles

    assert len(hn_articles) == 6, "HN の表が上限で削られていないこと"


def test_取得元が失敗したら上限を超えて埋める(tmp_path: Path, reference: datetime) -> None:
    """Qiita と Zenn が失敗して note しか残らない場合、4件ではなく10件出す。"""
    settings = Settings(
        keywords=["Claude Code"],
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=4,
    )

    class OnlyNote(ManyArticlesJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            if url in (zenn.SEARCH_URL, qiita.ITEMS_URL):
                raise RuntimeError("接続できません")
            return super().__call__(url, **kwargs)

    page = build_page(settings, OnlyNote(), FakeText(), reference)
    articles = _keyword_sections(page)[0].rankings[0].articles

    # 上限（4件）を超えて10件埋める。
    assert len(articles) == 10
    assert _site_counts(articles) == {SITE_NOTE: 10}


def test_記事が上限より少なければそのまま出す(tmp_path: Path, reference: datetime) -> None:
    settings = Settings(
        keywords=["Claude Code"],
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=4,
    )
    page = build_page(settings, FakeJson(), FakeText(), reference)
    articles = _keyword_sections(page)[0].rankings[0].articles

    # fixture は各サイト数件なので、上限に当たらずそのまま出る。
    assert articles
    assert all(count <= 4 for count in _site_counts(articles).values())


# ---------- X（旧 Twitter）----------
#
# X の API は従量課金なので、接続しないこと自体がテストの目的になる。


class XJson(FakeJson):
    """X の応答も返す偽の取得関数。X に接続したかどうかを記録する。"""

    def __init__(self, fail: set[str] | None = None) -> None:
        super().__init__(fail)
        self.x_calls = 0

    def __call__(self, url: str, **kwargs: Any) -> Any:
        if url == x_posts.SEARCH_URL:
            self.x_calls += 1
            self.calls.append(url)
            if url in self.fail:
                raise RuntimeError("X に接続できません")
            lang = "ja" if "lang:ja" in kwargs.get("params", {}).get("query", "") else "en"
            return {
                "data": [
                    {
                        "id": f"19750000000000000{i:02d}",
                        "text": f"AI の注目投稿 {lang}{i}",
                        "created_at": "2026-10-05T03:00:00.000Z",
                        "public_metrics": {"like_count": 1000 - i},
                    }
                    for i in range(12)
                ]
            }
        return super().__call__(url, **kwargs)


def _x_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "keywords": ["Claude Code"],
        "trend_words": TREND_WORDS,
        "output_dir": tmp_path / "docs",
        "qiita_token": None,
        "hatena_min_users": 10,
        "max_per_site": 0,
        "x_enabled": True,
        "x_bearer_token": "dummy-token",
        "x_max_posts": 400,
        "x_require_link": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_Xが止まっていれば接続しない(tmp_path: Path, reference: datetime) -> None:
    """一番大事なテスト。止めてあるのに接続すると料金が発生してしまう。"""
    settings = _x_settings(tmp_path, x_enabled=False)
    fake = XJson()

    build_page(settings, fake, FakeText(), reference)

    assert fake.x_calls == 0, "X に接続してはいけない"


def test_Xが止まっていれば表を出さない(tmp_path: Path, reference: datetime) -> None:
    settings = _x_settings(tmp_path, x_enabled=False)
    page = build_page(settings, XJson(), FakeText(), reference)

    captions = [r.caption or "" for r in _trend(page).rankings]
    assert not any(SITE_X in c for c in captions)
    # はてブと HN の表はそのまま出る。
    assert len(_trend(page).rankings) == 2


def test_Xが止まっていても他のセクションは動く(tmp_path: Path, reference: datetime) -> None:
    settings = _x_settings(tmp_path, x_enabled=False)
    page = build_page(settings, XJson(), FakeText(), reference)

    assert _keyword_sections(page)[0].rankings[0].articles, "キーワード別セクションは出る"
    assert _trend(page).rankings[0].articles, "はてブの表は出る"


def test_Xを有効にすると日本語と英語の2つの表が出る(tmp_path: Path, reference: datetime) -> None:
    settings = _x_settings(tmp_path)
    page = build_page(settings, XJson(), FakeText(), reference)

    captions = [r.caption or "" for r in _trend(page).rankings]
    # はてブ・HN・X(日本語)・X(英語) の4つ。
    assert len(captions) == 4
    assert any("X（日本語" in c for c in captions)
    assert any("X（英語" in c for c in captions)


def test_Xの表はいいね数順で10件まで(tmp_path: Path, reference: datetime) -> None:
    settings = _x_settings(tmp_path)
    page = build_page(settings, XJson(), FakeText(), reference)

    x_rankings = [r for r in _trend(page).rankings if SITE_X in (r.caption or "")]
    for ranking in x_rankings:
        assert len(ranking.articles) == 10, "12件返しても TOP10 で切る"
        scores = [a.score for a in ranking.articles]
        assert scores == sorted(scores, reverse=True)
        assert all(a.site == SITE_X for a in ranking.articles)


def test_Xは言語ごとに1回ずつ検索する(tmp_path: Path, reference: datetime) -> None:
    """単語リストが1本に収まるので、日本語・英語で各1回＝合計2回。"""
    settings = _x_settings(tmp_path)
    fake = XJson()
    build_page(settings, fake, FakeText(), reference)
    assert fake.x_calls == 2


def test_Xが失敗しても他の表は出る(tmp_path: Path, reference: datetime) -> None:
    """クレジット切れ・合言葉の誤り・通信エラーなどを想定。"""
    settings = _x_settings(tmp_path)
    page = build_page(settings, XJson(fail={x_posts.SEARCH_URL}), FakeText(), reference)

    trend = _trend(page)
    x_rankings = [r for r in trend.rankings if SITE_X in (r.caption or "")]

    assert len(x_rankings) == 2
    for ranking in x_rankings:
        assert ranking.articles == []
        assert any("X" in note for note in ranking.notes)
    # はてブと HN はそのまま出る。
    assert trend.rankings[0].articles
    assert trend.rankings[1].articles


def test_合言葉が無ければ接続せず取得失敗にする(tmp_path: Path, reference: datetime) -> None:
    settings = _x_settings(tmp_path, x_bearer_token=None)
    fake = XJson()
    page = build_page(settings, fake, FakeText(), reference)

    assert fake.x_calls == 0, "合言葉が無いのに接続してはいけない"
    x_rankings = [r for r in _trend(page).rankings if SITE_X in (r.caption or "")]
    assert all(r.notes for r in x_rankings)


def test_Xはキーワード別セクションには入らない(tmp_path: Path, reference: datetime) -> None:
    settings = _x_settings(tmp_path)
    page = build_page(settings, XJson(), FakeText(), reference)

    for section in _keyword_sections(page):
        for ranking in section.rankings:
            assert all(a.site != SITE_X for a in ranking.articles)


def test_Xの費用の上限が設定どおり渡る(tmp_path: Path, reference: datetime) -> None:
    settings = _x_settings(tmp_path, x_max_posts=100)

    seen: list[int] = []

    class Capturing(XJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            if url == x_posts.SEARCH_URL:
                seen.append(kwargs["params"]["max_results"])
            return super().__call__(url, **kwargs)

    build_page(settings, Capturing(), FakeText(), reference)
    # 100件 ÷ 2言語 = 1回50件
    assert seen == [50, 50]


def test_Xの期間外の投稿は落とす(tmp_path: Path, reference: datetime) -> None:
    settings = _x_settings(tmp_path)

    class OldPosts(XJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            if url == x_posts.SEARCH_URL:
                self.x_calls += 1
                return {
                    "data": [
                        {
                            "id": "1",
                            "text": "AI の古い投稿",
                            "created_at": "2026-09-01T03:00:00.000Z",
                            "public_metrics": {"like_count": 9999},
                        },
                        {
                            "id": "2",
                            "text": "AI の期間内の投稿",
                            "created_at": "2026-10-05T03:00:00.000Z",
                            "public_metrics": {"like_count": 10},
                        },
                    ]
                }
            return super().__call__(url, **kwargs)

    page = build_page(settings, OldPosts(), FakeText(), reference)
    x_ranking = next(r for r in _trend(page).rankings if SITE_X in (r.caption or ""))
    assert [a.title for a in x_ranking.articles] == ["AI の期間内の投稿"]


# ---------- 重複の除去（要件4） ----------


def test_同じ記事は先のキーワードセクションにだけ載る(
    settings: Settings, reference: datetime
) -> None:
    """2つのキーワードで同じ応答が返るので、2つ目のセクションは空になる。"""
    page = build_page(settings, FakeJson(), FakeText(), reference)
    first = _keyword_sections(page)[0].rankings[0].articles
    second = _keyword_sections(page)[1].rankings[0].articles

    assert first, "1つ目のセクションには載るはず"
    assert second == [], "2つ目のセクションでは省かれるはず"


def test_トレンドセクションはキーワードセクションと重複を見ない(
    settings: Settings, reference: datetime
) -> None:
    """別グループなので、キーワード側に載った記事があってもトレンド側は空にならない。"""
    page = build_page(settings, FakeJson(), FakeText(), reference)
    trend_articles = [a for r in _trend(page).rankings for a in r.articles]
    assert trend_articles


# ---------- 取得元の失敗（要件5） ----------


def test_noteが失敗しても他の取得元の記事が出る(settings: Settings, reference: datetime) -> None:
    page = build_page(settings, FakeJson(fail={note_com.SEARCH_URL}), FakeText(), reference)
    ranking = _keyword_sections(page)[0].rankings[0]

    assert ranking.articles, "Zenn と Qiita の記事は出るはず"
    assert {a.site for a in ranking.articles} == {SITE_ZENN, SITE_QIITA}
    assert any("note" in note for note in ranking.notes)


def test_はてブが失敗してもHNの表は出る(settings: Settings, reference: datetime) -> None:
    page = build_page(settings, FakeJson(), FakeText(fail=True), reference)
    trend = _trend(page)

    assert trend.rankings[0].articles == []
    assert any("はてなブックマーク" in note for note in trend.rankings[0].notes)
    assert trend.rankings[1].articles, "Hacker News の表は出るはず"


def test_HNが失敗してもはてブの表は出る(settings: Settings, reference: datetime) -> None:
    page = build_page(settings, FakeJson(fail={hackernews.SEARCH_URL}), FakeText(), reference)
    trend = _trend(page)

    assert trend.rankings[0].articles, "はてブの表は出るはず"
    assert trend.rankings[1].articles == []
    assert any("Hacker News" in note for note in trend.rankings[1].notes)


def test_全部失敗してもページの形は崩れない(settings: Settings, reference: datetime) -> None:
    all_urls = {
        zenn.SEARCH_URL,
        qiita.ITEMS_URL,
        note_com.SEARCH_URL,
        hackernews.SEARCH_URL,
    }
    page = build_page(settings, FakeJson(fail=all_urls), FakeText(fail=True), reference)

    assert [s.heading for s in page.sections] == [TREND_HEADING, "Claude Code", "RAG"]
    for section in page.sections:
        for ranking in section.rankings:
            assert ranking.articles == []
            assert ranking.notes, "失敗の説明が残るはず"


def test_取得元の失敗は他のキーワードに波及しない(settings: Settings, reference: datetime) -> None:
    fake = FakeJson(fail={note_com.SEARCH_URL})
    build_page(settings, fake, FakeText(), reference)
    # 2つのキーワードの両方で note を試している（1つ目の失敗で諦めていない）。
    assert fake.calls.count(note_com.SEARCH_URL) >= 2


def test_はてブがRSSでない応答を返したら取得失敗として出す(
    settings: Settings, reference: datetime
) -> None:
    """HTTP 200 で HTML が返っても「記事0件」にせず、取得失敗として残す。"""

    class HtmlText:
        def __call__(self, url: str, **kwargs: Any) -> str:
            return "<html><body>メンテナンス中</body></html>"

    page = build_page(settings, FakeJson(), HtmlText(), reference)
    hatena_ranking = _trend(page).rankings[0]

    assert hatena_ranking.articles == []
    assert any("はてなブックマーク" in note for note in hatena_ranking.notes)


def test_壊れたURLが混ざってもページができる(settings: Settings, reference: datetime) -> None:
    """URL の正規化は取得元ごとの保護の外なので、ここで止まるとページ全体を失う。"""

    class BrokenUrlJson(FakeJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            payload = super().__call__(url, **kwargs)
            # Qiita・はてブ・HN は応答の URL をそのまま使うので、壊れた値が入りうる。
            if url == qiita.ITEMS_URL and isinstance(payload, list) and payload:
                payload = json.loads(json.dumps(payload))
                payload[0]["url"] = "https://[broken"
            return payload

    page = build_page(settings, BrokenUrlJson(), FakeText(), reference)

    assert page.sections
    # 壊れた1件は落ち、他の記事は残る。
    articles = _keyword_sections(page)[0].rankings[0].articles
    assert articles
    assert all("[broken" not in a.url for a in articles)


def test_未来の投稿日の記事は載せない(settings: Settings, reference: datetime) -> None:
    """note の予約投稿などで投稿日が未来の記事は、期間の表示と合わないので落とす。"""

    class FutureJson(FakeJson):
        def __call__(self, url: str, **kwargs: Any) -> Any:
            payload = super().__call__(url, **kwargs)
            if url == zenn.SEARCH_URL and isinstance(payload, dict) and payload.get("articles"):
                payload = json.loads(json.dumps(payload))
                payload["articles"][0]["title"] = "未来の予約投稿"
                payload["articles"][0]["published_at"] = "2026-12-25T00:00:00.000+09:00"
                payload["articles"][0]["liked_count"] = 99999
            return payload

    page = build_page(settings, FutureJson(), FakeText(), reference)
    titles = [a.title for s in page.sections for r in s.rankings for a in r.articles]
    assert "未来の予約投稿" not in titles


def test_失敗しても例外が外に出ない(settings: Settings, reference: datetime) -> None:
    """main.py まで例外が飛ぶと、できていたページも保存されなくなる。"""

    class Boom:
        def __call__(self, url: str, **kwargs: Any) -> Any:
            raise ValueError("想定外の応答")

    page = build_page(settings, Boom(), Boom(), reference)
    assert page.sections


# ---------- 書き出しまで通す ----------


def test_ページを書き出せる(settings: Settings, reference: datetime) -> None:
    from src.render import write_site

    page = build_page(settings, FakeJson(), FakeText(), reference)
    write_site(page, settings.output_dir)

    index = (settings.output_dir / "index.html").read_text(encoding="utf-8")
    assert "Claude Code" in index
    assert TREND_HEADING in index
    assert (settings.output_dir / "2026-10-07.html").exists()
