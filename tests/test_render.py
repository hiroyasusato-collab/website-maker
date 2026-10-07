"""HTML 書き出しのテスト。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from src.models import (
    KIND_RESOURCES,
    KIND_TREND,
    LABEL_BOOKMARKS,
    LABEL_LIKES,
    LABEL_POINTS,
    LABEL_STARS,
    SITE_GIHYO,
    SITE_GITHUB,
    SITE_HATENA,
    SITE_ZENN,
    Article,
    Page,
    Ranking,
    Section,
    gap_section,
)
from src.render import find_backnumbers, render_html, write_site
from src.timeutil import JST


def _page(sections: list[Section] | None = None) -> Page:
    return Page(
        target_date=date(2026, 10, 7),
        period_start=date(2026, 10, 1),
        sections=sections if sections is not None else [_keyword_section()],
    )


def _keyword_section() -> Section:
    return Section(
        heading="Claude Code",
        rankings=[
            Ranking(
                score_label=LABEL_LIKES,
                articles=[
                    Article(
                        title="俺のAIプログラミング手法",
                        url="https://zenn.dev/mizchi/articles/x",
                        score=548,
                        published_at=datetime(2026, 10, 5, 13, 59, tzinfo=JST),
                        site=SITE_ZENN,
                    )
                ],
            )
        ],
    )


# ---------- 中身 ----------


def test_各行の項目が出る() -> None:
    html = render_html(_page(), page_title="テスト")

    assert "Claude Code" in html  # 見出し
    assert "俺のAIプログラミング手法" in html  # タイトル
    assert "https://zenn.dev/mizchi/articles/x" in html  # リンク
    assert SITE_ZENN in html  # サイト名
    assert "548" in html  # いいね数
    assert "2026-10-05" in html  # 投稿日
    assert '<td class="col-rank">1</td>' in html  # 順位


def test_集めた期間が出る() -> None:
    html = render_html(_page(), page_title="テスト")
    assert "2026-10-01" in html
    assert "2026-10-07" in html


def _one(title: str, site: str) -> list[Article]:
    return [
        Article(
            title=title,
            url=f"https://example.com/{title}",
            score=10,
            published_at=datetime(2026, 10, 5, tzinfo=JST),
            site=site,
        )
    ]


def test_取得元ごとに数の見出しを変える() -> None:
    """はてブは「ブックマーク」、HN は「ポイント」。数え方が違うので呼び分ける。"""
    section = Section(
        heading="AI業界トレンド",
        kind=KIND_TREND,
        rankings=[
            Ranking(
                caption="はてブ",
                score_label=LABEL_BOOKMARKS,
                articles=_one("はてブの記事", SITE_HATENA),
            ),
            Ranking(
                caption="HN",
                score_label=LABEL_POINTS,
                articles=_one("HNの記事", "Hacker News"),
            ),
        ],
    )
    html = render_html(_page([section]), page_title="テスト")
    assert f'<th class="col-score">{LABEL_BOOKMARKS}</th>' in html
    assert f'<th class="col-score">{LABEL_POINTS}</th>' in html


def test_表の小見出しが出る() -> None:
    """表ごとの小見出しは AI業界トレンドのセクションで使う。"""
    section = Section(
        heading="AI業界トレンド",
        kind=KIND_TREND,
        rankings=[
            Ranking(
                caption="はてなブックマーク（ブックマーク数順）",
                score_label=LABEL_BOOKMARKS,
                articles=[
                    Article(
                        title="AIの記事",
                        url="https://example.com/a",
                        score=99,
                        published_at=datetime(2026, 10, 5, tzinfo=JST),
                        site=SITE_HATENA,
                    )
                ],
            )
        ],
    )
    html = render_html(_page([section]), page_title="テスト")
    assert "はてなブックマーク（ブックマーク数順）" in html


# ---------- 2列に並べる ----------


def test_トレンドの表を2列の枠に入れる() -> None:
    """CSS の grid で2列にするので、表が grid の中に入っていること。"""
    section = Section(
        heading="AI業界トレンド",
        kind=KIND_TREND,
        rankings=[
            Ranking(caption="はてブ", score_label=LABEL_BOOKMARKS, articles=_one("a", SITE_HATENA)),
            Ranking(caption="HN", score_label=LABEL_POINTS, articles=_one("b", "Hacker News")),
        ],
    )
    html = render_html(_page([section]), page_title="テスト")

    assert '<div class="grid">' in html
    assert html.count('<div class="card">') == 2


def test_キーワード別も2列の枠に入れる() -> None:
    sections = [
        Section(
            heading=name,
            rankings=[Ranking(score_label=LABEL_LIKES, articles=_one(name, SITE_ZENN))],
        )
        for name in ("M365", "ChatGPT", "RAG")
    ]
    html = render_html(_page(sections), page_title="テスト")

    assert "キーワード別" in html
    assert html.count('<div class="card">') == 3


def test_キーワード別の見出しが設定した順に並ぶ() -> None:
    sections = [
        Section(
            heading=name,
            rankings=[Ranking(score_label=LABEL_LIKES, articles=_one(name, SITE_ZENN))],
        )
        for name in ("M365", "ChatGPT", "RAG", "Claude")
    ]
    html = render_html(_page(sections), page_title="テスト")

    positions = [html.index(f"<h3>{name}</h3>") for name in ("M365", "ChatGPT", "RAG", "Claude")]
    assert positions == sorted(positions), "セクションが渡した順に出ること"


def test_トレンドがキーワード別より先に出る() -> None:
    trend = Section(
        heading="AI業界トレンド",
        kind=KIND_TREND,
        rankings=[
            Ranking(caption="はてブ", score_label=LABEL_BOOKMARKS, articles=_one("a", SITE_HATENA))
        ],
    )
    keyword = Section(
        heading="M365", rankings=[Ranking(score_label=LABEL_LIKES, articles=_one("b", SITE_ZENN))]
    )
    # わざと順番を逆に渡しても、ページ上はトレンドが先に出る。
    html = render_html(_page([keyword, trend]), page_title="テスト")

    assert html.index("AI業界トレンド") < html.index("キーワード別")


def test_トレンドが無ければ見出しを出さない() -> None:
    keyword = Section(
        heading="M365", rankings=[Ranking(score_label=LABEL_LIKES, articles=_one("b", SITE_ZENN))]
    )
    html = render_html(_page([keyword]), page_title="テスト")

    assert "AI業界トレンド" not in html
    assert "キーワード別" in html


def test_キーワード別が無ければ見出しを出さない() -> None:
    trend = Section(
        heading="AI業界トレンド",
        kind=KIND_TREND,
        rankings=[
            Ranking(caption="はてブ", score_label=LABEL_BOOKMARKS, articles=_one("a", SITE_HATENA))
        ],
    )
    html = render_html(_page([trend]), page_title="テスト")

    assert "AI業界トレンド" in html
    assert "キーワード別" not in html


def test_サイト名と投稿日はタイトルの下に出す() -> None:
    """表の幅が半分になるので、列にせずタイトルの下に小さく置く。"""
    html = render_html(_page(), page_title="テスト")

    assert '<span class="meta">Zenn・2026-10-05</span>' in html
    # 列としては出さない。
    assert '<th class="col-site">' not in html
    assert '<th class="col-date">' not in html


def test_表の列は3つ() -> None:
    html = render_html(_page(), page_title="テスト")

    assert '<th class="col-rank">順位</th>' in html
    assert '<th class="col-title">記事タイトル</th>' in html
    assert f'<th class="col-score">{LABEL_LIKES}</th>' in html


def test_1列に戻す指定がスタイルに入っている() -> None:
    """画面が狭いときに1列に戻ること（CSS 側の指定）。"""
    from src.render import STYLE_SOURCE

    css = STYLE_SOURCE.read_text(encoding="utf-8")
    assert "@media (max-width:" in css
    assert "grid-template-columns: repeat(2" in css


# ---------- エスケープ（ここが壊れるとページが読めなくなる） ----------


def test_タイトルの記号をエスケープする() -> None:
    section = Section(
        heading="テスト",
        rankings=[
            Ranking(
                score_label=LABEL_LIKES,
                articles=[
                    Article(
                        title='<script>alert("x")</script> & "引用" <b>太字</b>',
                        url="https://example.com/a",
                        score=1,
                        published_at=datetime(2026, 10, 5, tzinfo=JST),
                        site=SITE_ZENN,
                    )
                ],
            )
        ],
    )
    html = render_html(_page([section]), page_title="テスト")

    # 生のタグがそのまま入っていないこと。
    assert "<script>" not in html
    assert "<b>太字</b>" not in html
    # エスケープされた形で入っていること。
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_URLの記号もエスケープする() -> None:
    section = Section(
        heading="テスト",
        rankings=[
            Ranking(
                score_label=LABEL_LIKES,
                articles=[
                    Article(
                        title="記事",
                        url='https://example.com/a?x=1&y=2"onmouseover="evil()',
                        score=1,
                        published_at=datetime(2026, 10, 5, tzinfo=JST),
                        site=SITE_ZENN,
                    )
                ],
            )
        ],
    )
    html = render_html(_page([section]), page_title="テスト")
    assert 'onmouseover="evil()"' not in html
    assert "&amp;y=2" in html


# ---------- 取得失敗・空のとき ----------


def test_取得失敗の説明がページに残る() -> None:
    """要件5：黙って消さずに残す。"""
    section = Section(
        heading="RAG",
        rankings=[
            Ranking(
                score_label=LABEL_LIKES,
                articles=[],
                notes=["note は取得できませんでした（FetchError）。"],
            )
        ],
    )
    html = render_html(_page([section]), page_title="テスト")
    assert "note は取得できませんでした" in html


def test_記事が無ければそう書く() -> None:
    section = Section(heading="M365", rankings=[Ranking(score_label=LABEL_LIKES, articles=[])])
    html = render_html(_page([section]), page_title="テスト")
    assert "該当する記事はありませんでした" in html


def test_取得失敗のときは記事なしの文を出さない() -> None:
    """「取得できませんでした」と「記事がありません」が二重に出ないこと。"""
    section = Section(
        heading="M365",
        rankings=[Ranking(score_label=LABEL_LIKES, articles=[], notes=["取得できませんでした。"])],
    )
    html = render_html(_page([section]), page_title="テスト")
    assert "該当する記事はありませんでした" not in html


# ---------- バックナンバー ----------


def test_日付ページを新しい順に並べる(tmp_path: Path) -> None:
    for name in ["2026-09-23.html", "2026-10-07.html", "2026-09-30.html"]:
        (tmp_path / name).write_text("", encoding="utf-8")

    found = find_backnumbers(tmp_path)
    assert [b.filename for b in found] == [
        "2026-10-07.html",
        "2026-09-30.html",
        "2026-09-23.html",
    ]
    assert found[0].label == "2026-10-07"


def test_日付の形でないファイルは一覧に入れない(tmp_path: Path) -> None:
    for name in ["index.html", "style.css", "2026-10-07.html", "メモ.html", "2026-10.html"]:
        (tmp_path / name).write_text("", encoding="utf-8")
    assert [b.filename for b in find_backnumbers(tmp_path)] == ["2026-10-07.html"]


def test_最新回を一覧から外せる(tmp_path: Path) -> None:
    for name in ["2026-10-07.html", "2026-09-30.html"]:
        (tmp_path / name).write_text("", encoding="utf-8")
    found = find_backnumbers(tmp_path, exclude="2026-10-07.html")
    assert [b.filename for b in found] == ["2026-09-30.html"]


def test_フォルダが無くても落ちない(tmp_path: Path) -> None:
    assert find_backnumbers(tmp_path / "ない") == []


# ---------- 書き出し ----------


def test_一式を書き出す(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)

    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "2026-10-07.html").exists()
    assert (tmp_path / "assets" / "style.css").exists()
    # GitHub に余計な変換をさせないための空ファイル。
    assert (tmp_path / ".nojekyll").exists()


def test_日付ページとトップページの中身が同じ記事を含む(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    dated = (tmp_path / "2026-10-07.html").read_text(encoding="utf-8")
    assert "俺のAIプログラミング手法" in index
    assert "俺のAIプログラミング手法" in dated


def test_トップページに過去回のリンクが出る(tmp_path: Path) -> None:
    (tmp_path / "2026-09-30.html").write_text("", encoding="utf-8")
    write_site(_page(), tmp_path)

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="2026-09-30.html"' in index
    # 最新回は「過去の回」に出さない。
    assert 'href="2026-10-07.html"' not in index


def test_日付ページには過去回のリンクを出さない(tmp_path: Path) -> None:
    (tmp_path / "2026-09-30.html").write_text("", encoding="utf-8")
    write_site(_page(), tmp_path)
    dated = (tmp_path / "2026-10-07.html").read_text(encoding="utf-8")
    assert "過去の回" not in dated


def test_2回実行しても過去回が消えない(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)

    later = Page(
        target_date=date(2026, 10, 14),
        period_start=date(2026, 10, 8),
        sections=[_keyword_section()],
    )
    write_site(later, tmp_path)

    assert (tmp_path / "2026-10-07.html").exists()
    assert (tmp_path / "2026-10-14.html").exists()
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="2026-10-07.html"' in index


def test_文字化けしない書き出し(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'charset="utf-8"' in html or "charset=utf-8" in html
    assert "俺のAIプログラミング手法" in html


def test_スタイルシートを相対パスで読む(tmp_path: Path) -> None:
    """GitHub Pages ではサブフォルダ配下に公開されるので、相対パスでないと崩れる。"""
    write_site(_page(), tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="assets/style.css"' in html


# ---------- 技術資料・リポジトリのセクション ----------


def _resource_section() -> Section:
    return Section(
        heading="技術資料・リポジトリ",
        kind=KIND_RESOURCES,
        rankings=[
            Ranking(
                caption="GitHub（スター数順）",
                score_label=LABEL_STARS,
                articles=_one("owner/repo — AI の道具", SITE_GITHUB),
            ),
            Ranking(
                caption="技術評論社（新着順）",
                score_label=None,
                articles=_one("AI の記事", SITE_GIHYO),
            ),
        ],
    )


def test_技術資料のセクションが2列の枠に入る() -> None:
    html = render_html(_page([_resource_section()]), page_title="テスト")

    assert "技術資料・リポジトリ" in html
    assert "GitHub（スター数順）" in html
    assert "技術評論社（新着順）" in html
    assert html.count('<div class="card">') == 2


def test_技術資料はトレンドの後キーワード別の前に出る() -> None:
    trend = Section(
        heading="AI業界トレンド",
        kind=KIND_TREND,
        rankings=[
            Ranking(caption="はてブ", score_label=LABEL_BOOKMARKS, articles=_one("a", SITE_HATENA))
        ],
    )
    keyword = Section(
        heading="M365", rankings=[Ranking(score_label=LABEL_LIKES, articles=_one("b", SITE_ZENN))]
    )
    # わざと順番をばらばらに渡しても、ページ上の並びは決まっている。
    html = render_html(_page([keyword, _resource_section(), trend]), page_title="テスト")

    assert html.index("AI業界トレンド") < html.index("技術資料・リポジトリ")
    assert html.index("技術資料・リポジトリ") < html.index("キーワード別")


def test_技術資料が無ければ見出しを出さない() -> None:
    keyword = Section(
        heading="M365", rankings=[Ranking(score_label=LABEL_LIKES, articles=_one("b", SITE_ZENN))]
    )
    html = render_html(_page([keyword]), page_title="テスト")
    assert "技術資料・リポジトリ" not in html


# ---------- 人気の数字が無い取得元（数の列を出さない）----------


def test_数の見出しが無ければ列を出さない() -> None:
    """技術評論社には人気の数字が無いので、数の列そのものを出さない。"""
    section = Section(
        heading="技術資料・リポジトリ",
        kind=KIND_RESOURCES,
        rankings=[
            Ranking(
                caption="技術評論社（新着順）",
                score_label=None,
                articles=_one("AI の記事", SITE_GIHYO),
            )
        ],
    )
    html = render_html(_page([section]), page_title="テスト")

    assert '<th class="col-score">' not in html
    assert '<td class="col-score">' not in html
    # タイトルとサイト名・日付は出る。
    assert "AI の記事" in html
    assert f'<span class="meta">{SITE_GIHYO}・2026-10-05</span>' in html


def test_スター数の見出しを出す() -> None:
    html = render_html(_page([_resource_section()]), page_title="テスト")
    assert f'<th class="col-score">{LABEL_STARS}</th>' in html


# ---------- 表を置かない位置（（空き））----------


def test_空きは中身の無い枠として出る() -> None:
    """2列のとき、次の表を左列に送るための空の枠を置く。"""
    sections = [
        Section(
            heading="M365",
            rankings=[Ranking(score_label=LABEL_LIKES, articles=_one("a", SITE_ZENN))],
        ),
        gap_section(),
        Section(
            heading="ChatGPT",
            rankings=[Ranking(score_label=LABEL_LIKES, articles=_one("b", SITE_ZENN))],
        ),
    ]
    html = render_html(_page(sections), page_title="テスト")

    assert '<div class="spacer" aria-hidden="true"></div>' in html
    # 空きは表ではないので card は2つだけ。
    assert html.count('<div class="card">') == 2
    # 並びは M365 → 空き → ChatGPT。
    assert html.index("<h3>M365</h3>") < html.index('<div class="spacer"')
    assert html.index('<div class="spacer"') < html.index("<h3>ChatGPT</h3>")


def test_空きだけでも見出しは出る() -> None:
    """万一「（空き）」しか残らなくても、ページの形が崩れないこと。"""
    html = render_html(_page([gap_section()]), page_title="テスト")
    assert "キーワード別" in html
