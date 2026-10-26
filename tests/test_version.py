"""バージョン番号と変更履歴のテスト。

番号は pyproject.toml の1か所にだけ書き、ページの一番下に小さく出す。
番号を上げたのに CHANGELOG.md に1行足し忘れた、という漏れもここで気づけるようにする。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from src.models import Page
from src.render import STYLE_SOURCE, TEMPLATE_DIR, find_backnumbers, render_html, write_site
from src.version import PYPROJECT, VERSION, read_version

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def _page() -> Page:
    return Page(target_date=date(2026, 10, 26), period_start=date(2026, 10, 20), sections=[])


def _changelog() -> list[tuple[str, list[str]]]:
    """CHANGELOG.md を「## 番号」ごとに区切り、(番号, 中身の行) を上から順に返す。"""
    entries: list[tuple[str, list[str]]] = []
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## (.+)$", line)
        if heading:
            entries.append((heading.group(1).strip(), []))
        elif entries and line.strip():
            entries[-1][1].append(line.strip())
    return entries


def _as_numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


# ---------- 番号の置き場所 ----------


def test_番号は3つの数の形() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)


def test_番号はpyprojectから読む() -> None:
    assert VERSION == read_version(PYPROJECT)


@pytest.mark.parametrize("bad", ["1.1", "1.1.0.0", "v1.1.0", "1.1.x", ""])
def test_形の違う番号は止める(tmp_path: Path, bad: str) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(f'[project]\nname = "x"\nversion = "{bad}"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="3つの数"):
        read_version(path)


def test_番号が無ければ止める(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        read_version(path)


def test_番号はプログラムの中に書き写さない() -> None:
    """番号を上げるとき pyproject.toml だけを直せば済むように。

    説明文の例（「1.1.0 → 1.2.0」など）は構わないので、引用符で囲んだ番号だけを探す。
    """
    sources = [*(REPO_ROOT / "src").rglob("*.py"), *TEMPLATE_DIR.iterdir()]
    for path in sources:
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert f'"{VERSION}"' not in text, path.name
            assert f"'{VERSION}'" not in text, path.name


# ---------- 変更履歴 ----------


def test_変更履歴の一番上が今の番号() -> None:
    """番号を上げたら CHANGELOG.md に1行足す（足し忘れるとここで落ちる）。"""
    assert _changelog()[0][0] == VERSION


def test_変更履歴は新しい版が上で同じ番号が無い() -> None:
    versions = [version for version, _ in _changelog()]
    for version in versions:
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    numbers = [_as_numbers(v) for v in versions]
    assert numbers == sorted(set(numbers), reverse=True)


def test_変更点は1つの版につき1から2行() -> None:
    for version, lines in _changelog():
        assert 1 <= len(lines) <= 2, version


def test_これまでの版の変更点() -> None:
    entries = dict(_changelog())
    assert entries["1.0.0"] == ["- 初版"]
    changes = "".join(entries["1.1.0"])
    assert "表示 ON/OFF" in changes
    assert "Speaker Deck（はてなブックマークの新着）" in changes


# ---------- ページに出す ----------


def test_ページの一番下に番号が出る() -> None:
    html = render_html(_page(), page_title="テスト")
    footer = re.search(r"<footer>(.*?)</footer>", html, flags=re.DOTALL)
    assert footer is not None
    assert f'<p class="version">バージョン {VERSION}</p>' in footer.group(1)
    # 自動生成の日時より下、つまりページの文の一番最後に出る
    assert footer.group(1).rstrip().endswith(f"バージョン {VERSION}</p>")


def test_番号はバックナンバーの一覧より下に出る(tmp_path: Path) -> None:
    (tmp_path / "2026-10-15.html").write_text("", encoding="utf-8")
    html = render_html(_page(), page_title="テスト", backnumbers=find_backnumbers(tmp_path))
    assert html.index("過去の回") < html.index(f"バージョン {VERSION}")


def test_日付ページとトップページの両方に番号が出る(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)
    for name in ["index.html", "2026-10-26.html"]:
        assert f"バージョン {VERSION}" in (tmp_path / name).read_text(encoding="utf-8")


def test_番号は小さく薄い字で出す() -> None:
    css = STYLE_SOURCE.read_text(encoding="utf-8")
    rule = re.search(r"footer \.version \{(.*?)\}", css, flags=re.DOTALL)
    assert rule is not None
    assert "font-size: 11px" in rule.group(1)
    assert "color: #999" in rule.group(1)
