"""技術資料・リポジトリのセクション（GitHub・技術評論社）のテスト。

ページ全体を組み立てたうえで確かめる。実際のサイトにはつながない。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import Settings
from src.models import LABEL_STARS, SITE_GIHYO, SITE_GITHUB
from src.pipeline import build_page
from src.sources import gihyo, github_repos
from tests.conftest import keyword_groups
from tests.test_pipeline import TREND_WORDS, FakeJson, FakeText, _resources


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "keywords": keyword_groups("Claude Code"),
        "trend_words": TREND_WORDS,
        "output_dir": tmp_path / "docs",
        "qiita_token": None,
        "hatena_min_users": 10,
        "max_per_site": 0,
    }
    values.update(overrides)
    return Settings(**values)


# ---------- 表の作り ----------


def test_2つの表に分かれる(tmp_path: Path, reference: datetime) -> None:
    """GitHub（スター数）と技術評論社（数字なし）は数え方が違うので混ぜない。"""
    page = build_page(_settings(tmp_path), FakeJson(), FakeText(), reference)
    resources = _resources(page)

    assert [r.caption for r in resources.rankings] == [
        f"{SITE_GITHUB}（スター数順）",
        f"{SITE_GIHYO}（新着順）",
    ]
    assert resources.rankings[0].score_label == LABEL_STARS
    # 技術評論社には人気の数字が無いので、数の列を出さない。
    assert resources.rankings[1].score_label is None


def test_GitHubはスター数順でAI以外を落とす(tmp_path: Path, reference: datetime) -> None:
    page = build_page(_settings(tmp_path), FakeJson(), FakeText(), reference)
    articles = _resources(page).rankings[0].articles
    titles = [a.title for a in articles]

    assert articles
    assert all(a.site == SITE_GITHUB for a in articles)
    assert [a.score for a in articles] == sorted((a.score for a in articles), reverse=True)
    # AI 関連は入る。
    assert any("openai/math" in t for t in titles)
    assert any("replica-skill" in t for t in titles)
    # AI と無関係なリポジトリは入らない。
    assert not any("sales-crm" in t for t in titles)
    assert not any("bloodborne" in t for t in titles)
    # JetBrains の "ai" で誤爆しないこと（wordmatch の歯止め）。
    assert not any("JetBrains" in t for t in titles)


def test_GitHubは期間外と壊れたURLを落とす(tmp_path: Path, reference: datetime) -> None:
    page = build_page(_settings(tmp_path), FakeJson(), FakeText(), reference)
    articles = _resources(page).rankings[0].articles

    assert not any("future-repo" in a.title for a in articles), "作成日が未来のものは入らない"
    assert all("[broken" not in a.url for a in articles)


def test_技術評論社は新着順でAI以外を落とす(tmp_path: Path, reference: datetime) -> None:
    page = build_page(_settings(tmp_path), FakeJson(), FakeText(), reference)
    articles = _resources(page).rankings[1].articles
    titles = [a.title for a in articles]

    assert articles
    assert all(a.site == SITE_GIHYO for a in articles)
    # 新着順（日付の降順）に並ぶ。
    dates = [a.published_at for a in articles]
    assert dates == sorted(dates, reverse=True)
    # AI 関連は入る。
    assert "Anthropic、Claude Sonnet 5.5を発表" in titles
    # AI と無関係な記事は入らない。
    assert not any("Imagecraft" in t for t in titles)
    # 期間より前の記事は入らない。
    assert "生成AIで業務を変える" not in titles


# ---------- 取得の失敗（要件5） ----------


def test_GitHubが失敗しても技術評論社の表は出る(tmp_path: Path, reference: datetime) -> None:
    page = build_page(
        _settings(tmp_path), FakeJson(fail={github_repos.SEARCH_URL}), FakeText(), reference
    )
    resources = _resources(page)

    assert resources.rankings[0].articles == []
    assert any(SITE_GITHUB in note for note in resources.rankings[0].notes)
    assert resources.rankings[1].articles, "技術評論社の表は出るはず"


def test_技術評論社が失敗してもGitHubの表は出る(tmp_path: Path, reference: datetime) -> None:
    page = build_page(
        _settings(tmp_path), FakeJson(), FakeText(fail_urls={gihyo.FEED_URL}), reference
    )
    resources = _resources(page)

    assert resources.rankings[0].articles, "GitHub の表は出るはず"
    assert resources.rankings[1].articles == []
    assert any(SITE_GIHYO in note for note in resources.rankings[1].notes)


def test_技術評論社がRSSでない応答を返したら取得失敗として出す(
    tmp_path: Path, reference: datetime
) -> None:
    """HTTP 200 で HTML が返っても「記事0件」にせず、取得失敗として残す。"""

    class HtmlText(FakeText):
        def __call__(self, url: str, **kwargs: Any) -> str:
            if url == gihyo.FEED_URL:
                return "<html><body>メンテナンス中</body></html>"
            return super().__call__(url, **kwargs)

    page = build_page(_settings(tmp_path), FakeJson(), HtmlText(), reference)
    ranking = _resources(page).rankings[1]

    assert ranking.articles == []
    assert any(SITE_GIHYO in note for note in ranking.notes)


# ---------- ほかのセクションとの関係 ----------


def test_キーワード別セクションと重複を見ない(tmp_path: Path, reference: datetime) -> None:
    """別グループなので、キーワード側の結果に左右されない。"""
    page = build_page(_settings(tmp_path), FakeJson(), FakeText(), reference)
    assert [a for r in _resources(page).rankings for a in r.articles]


def test_1サイトの上限は効かない(tmp_path: Path, reference: datetime) -> None:
    """GitHub の表・技術評論社の表はそれぞれ1サイトなので、上限で削ってはいけない。

    上限を効かせてしまうと、表が4件に削られてしまう。
    """

    class ManyRepos(FakeJson):
        """AI 関連のリポジトリを6件返す（上限の4件より多い）。"""

        def __call__(self, url: str, **kwargs: Any) -> Any:
            if url == github_repos.SEARCH_URL:
                if kwargs["params"]["page"] != 1:
                    return {"items": []}
                return {
                    "items": [
                        {
                            "full_name": f"owner/ai-tool-{i}",
                            "html_url": f"https://github.com/owner/ai-tool-{i}",
                            "description": "AI agent toolkit",
                            "stargazers_count": 100 - i,
                            "created_at": "2026-10-05T00:00:00Z",
                        }
                        for i in range(6)
                    ]
                }
            return super().__call__(url, **kwargs)

    page = build_page(_settings(tmp_path, max_per_site=4), ManyRepos(), FakeText(), reference)
    assert len(_resources(page).rankings[0].articles) == 6


def test_上限の設定を変えても技術資料の中身は変わらない(
    tmp_path: Path, reference: datetime
) -> None:
    """MAX_PER_SITE は技術資料・リポジトリには関係しないことを、結果の一致で確かめる。"""

    def titles(max_per_site: int) -> list[list[str]]:
        settings = _settings(tmp_path, max_per_site=max_per_site)
        page = build_page(settings, FakeJson(), FakeText(), reference)
        return [[a.title for a in r.articles] for r in _resources(page).rankings]

    assert titles(0) == titles(4)


def test_GitHubとgihyoの記事はキーワード別セクションに入らない(
    tmp_path: Path, reference: datetime
) -> None:
    from tests.test_pipeline import _keyword_sections

    page = build_page(_settings(tmp_path), FakeJson(), FakeText(), reference)
    for section in _keyword_sections(page):
        for ranking in section.rankings:
            assert all(a.site not in (SITE_GITHUB, SITE_GIHYO) for a in ranking.articles)
