"""入口（src/main.py）のテスト。

main() 自体はネットにつなぐので呼ばない。画面に出す内容だけを確かめる。
`python src\\main.py` で動くことは実際の実行で確認済み。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.main import _report
from src.models import LABEL_LIKES, LABEL_POINTS, SITE_ZENN, Article, Page, Ranking, Section
from src.timeutil import JST


def _page(sections: list[Section]) -> Page:
    return Page(
        target_date=date(2026, 10, 7),
        period_start=date(2026, 10, 1),
        sections=sections,
    )


def _article(title: str) -> Article:
    return Article(
        title=title,
        url=f"https://example.com/{title}",
        score=1,
        published_at=datetime(2026, 10, 5, tzinfo=JST),
        site=SITE_ZENN,
    )


def test_各セクションの件数を出す(capsys: pytest.CaptureFixture[str]) -> None:
    page = _page(
        [
            Section(
                heading="Claude Code",
                rankings=[Ranking(score_label=LABEL_LIKES, articles=[_article("a")])],
            )
        ]
    )
    _report(page)

    out = capsys.readouterr().out
    assert "2026-10-07" in out
    assert "Claude Code: 1 件" in out


def test_取得できなかったものを画面に出す(capsys: pytest.CaptureFixture[str]) -> None:
    """要件5：失敗を黙って消さず、実行した人に伝える。"""
    page = _page(
        [
            Section(
                heading="RAG",
                rankings=[
                    Ranking(
                        score_label=LABEL_LIKES,
                        articles=[],
                        notes=["note は取得できませんでした（FetchError）。"],
                    )
                ],
            )
        ]
    )
    _report(page)

    out = capsys.readouterr().out
    assert "取得できなかったもの" in out
    assert "note は取得できませんでした" in out
    assert "他のセクションはそのまま表示されます" in out


def test_失敗が無ければ失敗の見出しを出さない(capsys: pytest.CaptureFixture[str]) -> None:
    page = _page(
        [
            Section(
                heading="RAG",
                rankings=[Ranking(score_label=LABEL_LIKES, articles=[_article("a")])],
            )
        ]
    )
    _report(page)
    assert "取得できなかったもの" not in capsys.readouterr().out


def test_表の小見出しがあればそれを使う(capsys: pytest.CaptureFixture[str]) -> None:
    page = _page(
        [
            Section(
                heading="AI業界トレンド",
                rankings=[
                    Ranking(
                        caption="Hacker News（ポイント順）",
                        score_label=LABEL_POINTS,
                        articles=[_article("a")],
                    )
                ],
            )
        ]
    )
    _report(page)
    assert "Hacker News（ポイント順）: 1 件" in capsys.readouterr().out
