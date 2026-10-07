"""参考リンク（reference_links.txt）のテスト。

参考リンクは「取得はせず、ページにリンクを置くだけ」のもの。
いちばん大事なのは、**ここに書いた先へプログラムからアクセスしないこと**。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from src.config import (
    REFERENCE_LINKS_FILE,
    Settings,
    load_settings,
    parse_reference_link,
    read_reference_links,
)
from src.models import Page, ReferenceLink
from src.pipeline import build_page
from src.render import render_html
from tests.conftest import keyword_groups
from tests.test_pipeline import TREND_WORDS, FakeJson, FakeText

SPEAKER_DECK_URL = "https://speakerdeck.com/search?q=AI"


def _write(tmp_path: Path, text: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / "reference_links.txt"
    path.write_text(text, encoding=encoding)
    return path


def _page(links: list[ReferenceLink]) -> Page:
    return Page(
        target_date=date(2026, 10, 7),
        period_start=date(2026, 10, 1),
        sections=[],
        reference_links=links,
    )


# ---------- 設定ファイルの読み取り ----------


def test_表示名とURLを読む(tmp_path: Path) -> None:
    path = _write(tmp_path, f"Speaker Deck（「AI」の検索結果） | {SPEAKER_DECK_URL}\n")
    links = read_reference_links(path)

    assert links == [ReferenceLink(label="Speaker Deck（「AI」の検索結果）", url=SPEAKER_DECK_URL)]


def test_全角の縦棒でも区切れる(tmp_path: Path) -> None:
    """日本語入力のまま打てるようにする。"""
    path = _write(tmp_path, f"Speaker Deck ｜ {SPEAKER_DECK_URL}\n")
    assert read_reference_links(path)[0].label == "Speaker Deck"


def test_区切りの前後に空白が無くても読める() -> None:
    link = parse_reference_link(f"Speaker Deck|{SPEAKER_DECK_URL}")
    assert link == ReferenceLink(label="Speaker Deck", url=SPEAKER_DECK_URL)


def test_URLだけ書いたらURLが表示名になる(tmp_path: Path) -> None:
    path = _write(tmp_path, f"{SPEAKER_DECK_URL}\n")
    assert read_reference_links(path) == [
        ReferenceLink(label=SPEAKER_DECK_URL, url=SPEAKER_DECK_URL)
    ]


def test_表示名が空ならURLを表示名にする() -> None:
    link = parse_reference_link(f" | {SPEAKER_DECK_URL}")
    assert link is not None
    assert link.label == SPEAKER_DECK_URL


def test_表示名に縦棒が入っていても読める() -> None:
    """URL の直前の区切りで分けるので、表示名の中の縦棒は残る。"""
    link = parse_reference_link(f"A | B | {SPEAKER_DECK_URL}")
    assert link is not None
    assert link.label == "A | B"
    assert link.url == SPEAKER_DECK_URL


def test_空行とコメント行を無視する(tmp_path: Path) -> None:
    path = _write(tmp_path, f"# メモ\n\n  \nSpeaker Deck | {SPEAKER_DECK_URL}\n")
    assert len(read_reference_links(path)) == 1


def test_同じURLは1つだけ残す(tmp_path: Path) -> None:
    path = _write(tmp_path, f"A | {SPEAKER_DECK_URL}\nB | {SPEAKER_DECK_URL}\n")
    links = read_reference_links(path)
    assert [link.label for link in links] == ["A"]


def test_メモ帳のBOMでも読める(tmp_path: Path) -> None:
    path = _write(tmp_path, f"Speaker Deck | {SPEAKER_DECK_URL}\n", encoding="utf-8-sig")
    assert read_reference_links(path)[0].label == "Speaker Deck"


def test_順番を保つ(tmp_path: Path) -> None:
    path = _write(tmp_path, "A | https://example.com/a\nB | https://example.com/b\n")
    assert [link.label for link in read_reference_links(path)] == ["A", "B"]


# ---------- 設定ファイルが無い・空のとき ----------


def test_ファイルが無ければ空で返る(tmp_path: Path) -> None:
    """無くても動く（エラーにしない）。"""
    assert read_reference_links(tmp_path / "ない.txt") == []


def test_中身が空なら空で返る(tmp_path: Path) -> None:
    assert read_reference_links(_write(tmp_path, "")) == []


def test_コメントだけなら空で返る(tmp_path: Path) -> None:
    assert read_reference_links(_write(tmp_path, "# 何も書いていない\n\n")) == []


# ---------- 危ない URL を受け付けない ----------


@pytest.mark.parametrize(
    "raw",
    [
        "危ないリンク | javascript:alert(1)",
        "ファイル | file:///C:/Windows",
        "メール | mailto:someone@example.com",
        "書きかけ | speakerdeck.com/search?q=AI",
        "URLが無い | ",
        "ただの文章",
    ],
)
def test_httpで始まらない行は読み飛ばす(tmp_path: Path, raw: str) -> None:
    """ページは公開されるので、http / https 以外はリンクにしない。"""
    assert read_reference_links(_write(tmp_path, raw + "\n")) == []


def test_読み飛ばした行はお知らせを出す(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """黙って消すと、書き間違いに気づけないため。"""
    with caplog.at_level(logging.WARNING):
        read_reference_links(_write(tmp_path, "危ないリンク | javascript:alert(1)\n"))
    assert "読み飛ばしました" in caplog.text


def test_読み飛ばしても他の行は残る(tmp_path: Path) -> None:
    path = _write(tmp_path, f"だめな行 | javascript:alert(1)\nよい行 | {SPEAKER_DECK_URL}\n")
    assert [link.label for link in read_reference_links(path)] == ["よい行"]


def test_httpも受け付ける(tmp_path: Path) -> None:
    assert read_reference_links(_write(tmp_path, "A | http://example.com\n"))


# ---------- ページへの表示 ----------


def test_参考リンクの欄が出る() -> None:
    html = render_html(
        _page([ReferenceLink(label="Speaker Deck（「AI」の検索結果）", url=SPEAKER_DECK_URL)]),
        page_title="テスト",
    )

    assert "参考リンク" in html
    assert "Speaker Deck（「AI」の検索結果）" in html
    assert SPEAKER_DECK_URL in html
    # 別のタブで開く（ほかのリンクと同じ扱い）。
    assert 'rel="noopener noreferrer"' in html


def test_リンクが無ければ欄ごと出さない() -> None:
    html = render_html(_page([]), page_title="テスト")
    assert "参考リンク" not in html


def test_書いた順に並ぶ() -> None:
    links = [
        ReferenceLink(label="1つ目", url="https://example.com/a"),
        ReferenceLink(label="2つ目", url="https://example.com/b"),
    ]
    html = render_html(_page(links), page_title="テスト")
    assert html.index("1つ目") < html.index("2つ目")


def test_表示名の記号をエスケープする() -> None:
    """表示名に < > & が入ってもページが壊れないこと。"""
    links = [ReferenceLink(label="<script>危険</script>", url="https://example.com/a")]
    html = render_html(_page(links), page_title="テスト")

    assert "<script>危険</script>" not in html
    assert "&lt;script&gt;" in html


def test_技術資料の次キーワード別の前に出る(tmp_path: Path, reference: datetime) -> None:
    settings = Settings(
        keywords=keyword_groups("Claude Code"),
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=0,
        reference_links=[ReferenceLink(label="Speaker Deck", url=SPEAKER_DECK_URL)],
    )
    page = build_page(settings, FakeJson(), FakeText(), reference)
    html = render_html(page, page_title="テスト")

    assert html.index("技術資料・リポジトリ") < html.index("参考リンク")
    assert html.index("参考リンク") < html.index("キーワード別")


# ---------- 取得しないこと（ここが一番大事） ----------


def test_参考リンクには接続しない(tmp_path: Path, reference: datetime) -> None:
    """ページにリンクを置くだけ。プログラムからは一切アクセスしない。"""
    settings = Settings(
        keywords=keyword_groups("Claude Code"),
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=0,
        reference_links=[ReferenceLink(label="Speaker Deck", url=SPEAKER_DECK_URL)],
    )
    fake_json = FakeJson()
    fake_text = FakeText()

    build_page(settings, fake_json, fake_text, reference)

    called = fake_json.calls + fake_text.calls
    assert all("speakerdeck.com" not in url for url in called)


def test_参考リンクはページにそのまま渡る(tmp_path: Path, reference: datetime) -> None:
    links = [ReferenceLink(label="Speaker Deck", url=SPEAKER_DECK_URL)]
    settings = Settings(
        keywords=keyword_groups("Claude Code"),
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=0,
        reference_links=links,
    )
    page = build_page(settings, FakeJson(), FakeText(), reference)
    assert page.reference_links == links


def test_設定しなければページにも出ない(tmp_path: Path, reference: datetime) -> None:
    settings = Settings(
        keywords=keyword_groups("Claude Code"),
        trend_words=TREND_WORDS,
        output_dir=tmp_path / "docs",
        qiita_token=None,
        hatena_min_users=10,
        max_per_site=0,
    )
    page = build_page(settings, FakeJson(), FakeText(), reference)

    assert page.reference_links == []
    assert "参考リンク" not in render_html(page, page_title="テスト")


# ---------- 同梱の設定ファイル ----------


def test_同梱のreference_linksにSpeakerDeckが入っている() -> None:
    links = read_reference_links(REFERENCE_LINKS_FILE)

    assert links == [ReferenceLink(label="Speaker Deck（「AI」の検索結果）", url=SPEAKER_DECK_URL)]


def test_load_settingsが参考リンクを読む(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "keywords.txt").write_text("RAG\n", encoding="utf-8")
    (tmp_path / "ai_trend_words.txt").write_text("AI\n", encoding="utf-8")
    _write(tmp_path, f"Speaker Deck | {SPEAKER_DECK_URL}\n")
    monkeypatch.delenv("X_MAX_POSTS", raising=False)

    settings = load_settings(
        tmp_path / "keywords.txt",
        tmp_path / "ai_trend_words.txt",
        tmp_path / "docs",
        tmp_path / "ない.txt",
        tmp_path / "reference_links.txt",
    )
    assert [link.label for link in settings.reference_links] == ["Speaker Deck"]


def test_load_settingsは参考リンクが無くても動く(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "keywords.txt").write_text("RAG\n", encoding="utf-8")
    (tmp_path / "ai_trend_words.txt").write_text("AI\n", encoding="utf-8")
    monkeypatch.delenv("X_MAX_POSTS", raising=False)

    settings = load_settings(
        tmp_path / "keywords.txt",
        tmp_path / "ai_trend_words.txt",
        tmp_path / "docs",
        tmp_path / "ない.txt",
        tmp_path / "ない2.txt",
    )
    assert settings.reference_links == []


# ---------- URL の中に縦棒が入っている場合 ----------
#
# 区切りの文字で切り分けると、検索結果のような URL（?q=AI|LLM）が壊れる。
# そこで「http:// または https:// で始まるところから後ろ」を URL として扱う。


def test_URLの中の半角縦棒を区切りと間違えない() -> None:
    link = parse_reference_link("検索 | https://example.com/?q=AI|LLM")
    assert link == ReferenceLink(label="検索", url="https://example.com/?q=AI|LLM")


def test_URLの中の全角縦棒を区切りと間違えない() -> None:
    link = parse_reference_link("検索 ｜ https://example.com/?q=AI｜LLM")
    assert link == ReferenceLink(label="検索", url="https://example.com/?q=AI｜LLM")


def test_区切りが無くてもURLの手前が表示名になる() -> None:
    """「|」を書き忘れても読めるようにする。"""
    link = parse_reference_link("Speaker Deck https://speakerdeck.com/search?q=AI")
    assert link == ReferenceLink(label="Speaker Deck", url=SPEAKER_DECK_URL)


def test_URLの後ろに文字があっても落とす() -> None:
    """URL に空白は入らないので、最初の空白までを URL とする。"""
    link = parse_reference_link(f"A | {SPEAKER_DECK_URL} ← ここを見る")
    assert link is not None
    assert link.url == SPEAKER_DECK_URL


def test_大文字で書いたURLも受け付ける() -> None:
    link = parse_reference_link("A | HTTPS://example.com")
    assert link is not None
    assert link.url == "HTTPS://example.com"


@pytest.mark.parametrize("raw", ["A | https://", "A | http://", "A | https:// example.com"])
def test_スキームだけの行は読み飛ばす(raw: str) -> None:
    """`https://` だけではリンク先が無いので、リンクにしない。"""
    assert parse_reference_link(raw) is None


def test_表示名の中にURLらしきものがあってもURLを取り違えない() -> None:
    """文字としての「http://」は、:// の直後が空白なので URL と見なさない。"""
    link = parse_reference_link(f"http:// は使わない | {SPEAKER_DECK_URL}")
    assert link is not None
    assert link.url == SPEAKER_DECK_URL
    assert link.label == "http:// は使わない"
