"""表ごとの表示 ON/OFF のテスト。

ページ側（どの表に名前が付くか・一覧に何が並ぶか・外部を読み込まないか）は HTML で確かめる。
切り替えの決まり（保存した値の読み方・「（空き）」の扱い）は table_toggle.js を node で
動かして確かめる。node が無い PC では、そのテストだけ飛ばす。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from src.models import (
    KIND_RESOURCES,
    KIND_TREND,
    LABEL_LIKES,
    LABEL_STARS,
    SITE_GITHUB,
    SITE_HATENA,
    SITE_ZENN,
    Article,
    Page,
    Ranking,
    ReferenceLink,
    Section,
    gap_section,
)
from src.render import (
    REFERENCE_LINKS_NAME,
    STYLE_SOURCE,
    TOGGLE_SCRIPT_SOURCE,
    ToggleGroup,
    render_html,
    toggle_groups,
    write_site,
)
from src.timeutil import JST


def _one(title: str, site: str) -> list[Article]:
    return [
        Article(
            title=title,
            url="https://example.com/a",
            score=1,
            published_at=datetime(2026, 10, 5, tzinfo=JST),
            site=site,
        )
    ]


def _keyword(name: str) -> Section:
    return Section(
        heading=name,
        rankings=[Ranking(score_label=LABEL_LIKES, articles=_one(name, SITE_ZENN))],
    )


def _trend() -> Section:
    return Section(
        heading="AI業界トレンド",
        kind=KIND_TREND,
        rankings=[
            Ranking(
                caption="はてなブックマーク（ブックマーク数順）",
                score_label=LABEL_LIKES,
                articles=_one("a", SITE_HATENA),
            ),
            Ranking(caption="Hacker News（ポイント順）", score_label=LABEL_LIKES),
        ],
    )


def _resources() -> Section:
    return Section(
        heading="技術資料・リポジトリ",
        kind=KIND_RESOURCES,
        rankings=[
            Ranking(
                caption="GitHub（スター数順）",
                score_label=LABEL_STARS,
                articles=_one("r", SITE_GITHUB),
            )
        ],
    )


def _page(sections: list[Section] | None = None, links: list[ReferenceLink] | None = None) -> Page:
    return Page(
        target_date=date(2026, 10, 26),
        period_start=date(2026, 10, 20),
        sections=(
            sections
            if sections is not None
            else [_trend(), _resources(), _keyword("M365"), gap_section(), _keyword("Codex")]
        ),
        reference_links=(
            links
            if links is not None
            else [ReferenceLink(label="Speaker Deck", url="https://speakerdeck.com/search?q=AI")]
        ),
    )


def _html(page: Page | None = None) -> str:
    return render_html(page or _page(), page_title="テスト")


# ---------- 表の名前（data-table） ----------


def test_表ごとに名前が付く() -> None:
    html = _html()

    for name in [
        "はてなブックマーク（ブックマーク数順）",
        "Hacker News（ポイント順）",
        "GitHub（スター数順）",
        "M365",
        "Codex",
    ]:
        assert f'<div class="card" data-table="{name}">' in html


def test_参考リンクの欄にも名前が付く() -> None:
    assert f'<section class="reference-links" data-table="{REFERENCE_LINKS_NAME}">' in _html()


def test_空き枠には名前を付けない() -> None:
    """空き枠は表ではないので、一覧にも出さず、隠す対象にもしない。"""
    html = _html()
    assert '<div class="spacer" aria-hidden="true"></div>' in html


def test_見出しごと消せる枠に印が付く() -> None:
    """AI業界トレンド・技術資料・リポジトリ・キーワード別の3つ。"""
    assert _html().count('<section class="table-group">') == 3


def test_表の名前の記号をエスケープする() -> None:
    html = _html(_page([_keyword('A<b>&"c')], links=[]))
    assert 'data-table="A&lt;b&gt;&amp;&#34;c"' in html
    assert 'value="A&lt;b&gt;&amp;&#34;c"' in html
    assert 'A<b>&"c' not in html


# ---------- 表示するニュース項目を選ぶ（一覧） ----------


def test_一覧はページに出る順に並ぶ() -> None:
    assert toggle_groups(_page()) == [
        ToggleGroup(
            heading="AI業界トレンド",
            names=["はてなブックマーク（ブックマーク数順）", "Hacker News（ポイント順）"],
        ),
        ToggleGroup(heading="技術資料・リポジトリ", names=["GitHub（スター数順）"]),
        ToggleGroup(heading=None, names=[REFERENCE_LINKS_NAME]),
        ToggleGroup(heading="キーワード別", names=["M365", "Codex"]),
    ]


def test_一覧の表は最初はすべてON() -> None:
    html = _html()
    boxes = re.findall(r"<input [^>]*>", html)
    assert len(boxes) == 6
    assert all('type="checkbox"' in box and "checked" in box for box in boxes)


def test_一覧は日付の下に置き普段は畳んでおく() -> None:
    html = _html()
    header = html[html.index("<header>") : html.index("</header>")]

    assert header.index('class="period"') < header.index("表示するニュース項目を選ぶ")
    # details に open を付けない＝畳んだ状態。
    assert '<details class="table-toggle" id="table-toggle" hidden>' in header
    assert "<summary>表示するニュース項目を選ぶ" in header


def test_JavaScriptが動くまで一覧は出さない() -> None:
    """動かないブラウザでは、押しても何も起きない一覧を出さない（全部表示のまま）。"""
    assert 'id="table-toggle" hidden' in _html()


def test_隠している数の置き場所とすべて表示に戻すがある() -> None:
    html = _html()
    summary = html[html.index("<summary>") : html.index("</summary>")]
    assert "data-toggle-count" in summary
    assert '<button type="button" data-toggle-reset>すべて表示に戻す</button>' in html


def test_参考リンクが無ければ一覧にも出さない() -> None:
    groups = toggle_groups(_page(links=[]))
    assert all(REFERENCE_LINKS_NAME not in group.names for group in groups)


def test_一覧はページにある表から作る() -> None:
    """一覧はページにある表から作るので、増えた表も消えた表もそのまま反映される。"""
    groups = toggle_groups(_page([_keyword("新しい表")], links=[]))
    assert groups == [ToggleGroup(heading="キーワード別", names=["新しい表"])]


def test_同じ名前の表は一覧に1回だけ出る() -> None:
    page = _page([_keyword("M365"), _keyword("M365")], links=[])
    assert toggle_groups(page) == [ToggleGroup(heading="キーワード別", names=["M365"])]


def test_表が1つも無ければ一覧を出さない() -> None:
    html = _html(_page([], links=[]))
    assert "<summary>表示するニュース項目を選ぶ" not in html
    assert 'id="table-toggle"' not in html


def test_空き枠は一覧に出ない() -> None:
    groups = toggle_groups(_page([gap_section(), _keyword("M365")], links=[]))
    assert groups == [ToggleGroup(heading="キーワード別", names=["M365"])]


# ---------- 外部を読み込まない・送らない ----------


def _script_from(html: str) -> str:
    scripts = re.findall(r"<script([^>]*)>(.*?)</script>", html, flags=re.DOTALL)
    assert len(scripts) == 1
    attrs, body = scripts[0]
    assert attrs == ""  # src を付けない＝別のファイルを読み込まない
    return body


def test_切り替えの仕組みはページに埋め込む() -> None:
    body = _script_from(_html())
    assert "websitemaker.hiddenTables" in body
    # エスケープされずにそのまま入っている（&quot; などになっていない）。
    assert '"use strict";' in body


def test_ページは外部のファイルを読み込まない() -> None:
    html = _html()
    assert re.findall(r"<link [^>]*>", html) == ['<link rel="stylesheet" href="assets/style.css">']
    assert "<script src" not in html
    assert "<iframe" not in html
    assert "@import" not in STYLE_SOURCE.read_text(encoding="utf-8")


def test_切り替えの仕組みはどこにも送らない() -> None:
    source = TOGGLE_SCRIPT_SOURCE.read_text(encoding="utf-8")
    for word in ["fetch", "XMLHttpRequest", "sendBeacon", "WebSocket", "http:", "https:"]:
        assert word not in source
    assert "document.cookie" not in source


def test_埋め込んだ仕組みがページを途中で閉じない() -> None:
    """script の中に </script> があると、そこでページが壊れる。"""
    source = TOGGLE_SCRIPT_SOURCE.read_text(encoding="utf-8").lower()
    assert "</script" not in source
    assert "<!--" not in source


def test_保存の名前はwebsitemakerで始まる() -> None:
    source = TOGGLE_SCRIPT_SOURCE.read_text(encoding="utf-8")
    keys = re.findall(r'STORAGE_KEY = "([^"]+)"', source)
    assert keys == ["websitemaker.hiddenTables"]


def test_日付ページとトップページの両方に入る(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)
    for name in ["index.html", "2026-10-26.html"]:
        html = (tmp_path / name).read_text(encoding="utf-8")
        assert "表示するニュース項目を選ぶ" in html
        assert "websitemaker.hiddenTables" in html


def test_隠したものは空き枠でも確実に消える() -> None:
    """.spacer は display: block を指定しているので、hidden だけでは消えない。"""
    css = STYLE_SOURCE.read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;", css)


# ---------- 切り替えの決まり（node で table_toggle.js を動かす） ----------

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node が無いので JavaScript のテストは飛ばす")

_RUNNER = """
const t = require(process.argv[1]);
const args = JSON.parse(process.argv[3]);
const value = process.argv[2] === "STORAGE_KEY" ? t.STORAGE_KEY : t[process.argv[2]](...args);
process.stdout.write(JSON.stringify(value === undefined ? null : value));
"""


def _js(name: str, *args: Any) -> Any:
    assert NODE is not None
    result = subprocess.run(
        [NODE, "-e", _RUNNER, str(TOGGLE_SCRIPT_SOURCE), name, json.dumps(list(args))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


# 枠の中身の書き方：表は名前、隠した表は "-名前"、空き枠は None。
def _layout(cells: list[str | None]) -> list[str | None]:
    """出す枠だけを並べて返す（空き枠は None のまま）。"""
    items = [
        {"spacer": cell is None, "hidden": cell is not None and cell.startswith("-")}
        for cell in cells
    ]
    shown = _js("layoutItems", items)
    return [cell for cell, keep in zip(cells, shown) if keep]


@needs_node
def test_保存の名前_実物() -> None:
    assert _js("STORAGE_KEY").startswith("websitemaker")


@needs_node
@pytest.mark.parametrize("raw", [None, "", "{", "not json", "{}", '"M365"', "123", "null"])
def test_保存した値が読めなければ全部表示(raw: str | None) -> None:
    assert _js("parseHidden", raw) == []


@needs_node
def test_保存した値から隠す表の名前を読む() -> None:
    raw = json.dumps(["M365", 3, None, "Codex", "M365"])
    # 文字列以外は捨て、重複は1つにする。
    assert _js("parseHidden", raw) == ["M365", "Codex"]


@needs_node
def test_隠している数はこのページにある表だけ数える() -> None:
    assert _js("countHidden", ["M365", "ほかの回にしか無い表"], ["M365", "Codex"]) == 1


@needs_node
def test_隠している数の書き方() -> None:
    assert _js("hiddenMessage", 3) == "3個のニュース項目を非表示中"
    assert _js("hiddenMessage", 12) == "12個のニュース項目を非表示中"
    assert _js("hiddenMessage", 0) == ""


# 同梱の display_order.txt の並び（M365｜RAG／AIエージェント｜空き／ChatGPT｜Codex …）
DEFAULT: list[str | None] = [
    "M365",
    "RAG",
    "AIエージェント",
    None,
    "ChatGPT",
    "Codex",
    "Claude",
    "Claude Code",
    "AI駆動開発",
]


@needs_node
def test_何も隠していなければ空き枠は今までどおり() -> None:
    assert _layout(DEFAULT) == DEFAULT
    # 先頭や連続した空きも、設定したとおりに残す。
    assert _layout([None, "M365", None, None, "Codex"]) == [None, "M365", None, None, "Codex"]


@needs_node
def test_隠した表は詰める() -> None:
    assert _layout(["M365", "-RAG", "Codex", "Claude"]) == ["M365", "Codex", "Claude"]


@needs_node
def test_空き枠が左列に来るなら消す() -> None:
    """RAG を隠すと AIエージェント が右列に上がり、空き枠が左列に来てしまう。"""
    cells = list(DEFAULT)
    cells[1] = "-RAG"
    assert _layout(cells) == [
        "M365",
        "AIエージェント",
        "ChatGPT",
        "Codex",
        "Claude",
        "Claude Code",
        "AI駆動開発",
    ]


@needs_node
def test_空き枠が右列のままなら残す() -> None:
    """上の行で2つ隠しても、空き枠が右列に来るなら「次の表を左列から始める」役目を果たす。"""
    cells = list(DEFAULT)
    cells[0] = "-M365"
    cells[1] = "-RAG"
    assert _layout(cells) == [
        "AIエージェント",
        None,
        "ChatGPT",
        "Codex",
        "Claude",
        "Claude Code",
        "AI駆動開発",
    ]


@needs_node
def test_空き枠の前の表を隠すと空き枠も消える() -> None:
    cells = list(DEFAULT)
    cells[2] = "-AIエージェント"
    assert _layout(cells) == [
        "M365",
        "RAG",
        "ChatGPT",
        "Codex",
        "Claude",
        "Claude Code",
        "AI駆動開発",
    ]


@needs_node
def test_後ろの表をすべて隠すと空き枠は残らない() -> None:
    cells: list[str | None] = ["M365", "RAG", "AIエージェント", None, "-ChatGPT", "-Codex"]
    assert _layout(cells) == ["M365", "RAG", "AIエージェント"]


@needs_node
def test_先頭や連続した空き枠は隠しているときは詰める() -> None:
    assert _layout([None, "M365", None, None, "-RAG", "Codex"]) == ["M365", None, "Codex"]


@needs_node
def test_すべて隠すと何も残らない() -> None:
    assert _layout(["-M365", None, "-Codex"]) == []
