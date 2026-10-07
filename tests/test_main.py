"""入口（src/main.py）のテスト。

main() 自体はネットにつなぐので呼ばない。画面に出す内容だけを確かめる。
`python src\\main.py` で動くことは実際の実行で確認済み。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

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


def test_envが環境変数より優先される(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """X の停止スイッチが確実に効くようにするため。

    既定では .env より OS 側の環境変数が優先されるので、どこかに X_ENABLED=true が
    残っていると、.env を false にしても止まらなくなる。
    """
    import src.main as main_module

    env_file = tmp_path / ".env"
    env_file.write_text("X_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setattr(main_module, "_PROJECT_ROOT", tmp_path)
    # OS 側に true が残っている状況を作る。
    monkeypatch.setenv("X_ENABLED", "true")

    main_module._load_dotenv()

    assert os.environ["X_ENABLED"] == "false", ".env の指定が勝つこと"


def test_メモ帳で保存したenvでも停止スイッチが効く(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows のメモ帳で保存すると先頭に BOM が付く。

    既定の読み方だと1行目の項目名が「(BOM)X_ENABLED」として読まれ、
    1行目に書いた X_ENABLED=false が効かなくなる（＝止めたつもりで課金される）。
    """
    import src.main as main_module

    env_file = tmp_path / ".env"
    # utf-8-sig = メモ帳が付ける BOM 付きの保存形式。X_ENABLED を1行目に置く。
    env_file.write_text("X_ENABLED=false\nX_MAX_POSTS=100\n", encoding="utf-8-sig")
    monkeypatch.setattr(main_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("X_ENABLED", "true")

    main_module._load_dotenv()

    assert os.environ["X_ENABLED"] == "false", "BOM 付きでも止まること"
    assert os.environ["X_MAX_POSTS"] == "100"


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
