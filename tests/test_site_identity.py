"""サイト名とアイコンのテスト。

利用者に見せる名前は「週刊AIトレンドニュース」。ブラウザのタブとページの見出しに出す。
プログラム・フォルダ・URL の名前（website-maker）は変えない。
アイコンは紺の角丸の正方形に白い新聞の紙面、紙面の上部に「AI」、その下に横線2本。
"""

from __future__ import annotations

import re
import struct
import tomllib
import xml.etree.ElementTree as ET
import zlib
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pytest

from src.favicon import ICO_SIZES, NAVY, WHITE, favicon_ico, favicon_svg, render_pixels
from src.models import Page
from src.render import SITE_NAME, render_html, write_site

REPO_ROOT = Path(__file__).resolve().parent.parent

SVG_NS = "{http://www.w3.org/2000/svg}"


def _page() -> Page:
    return Page(target_date=date(2026, 10, 26), period_start=date(2026, 10, 20), sections=[])


def _title(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html)
    assert match is not None
    return match.group(1)


def _icon_hrefs(html: str) -> list[str]:
    return re.findall(r'<link rel="icon" href="([^"]+)"', html)


def _ico_images(data: bytes) -> list[tuple[int, int, bytes]]:
    """ICO を (幅, 高さ, PNG のデータ) の並びに分ける。"""
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1)
    images = []
    for index in range(count):
        width, height, _, _, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        assert (planes, bits) == (1, 32)
        images.append((width or 256, height or 256, data[offset : offset + length]))
    return images


def _decode_png(data: bytes) -> list[list[tuple[int, int, int, int]]]:
    """このプログラムが作る形の PNG（RGBA・各行の前処理なし）だけを読む。"""
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    position = 8
    width = height = 0
    compressed = b""
    while position < len(data):
        (length,) = struct.unpack_from(">I", data, position)
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        (crc,) = struct.unpack_from(">I", data, position + 8 + length)
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF
        if kind == b"IHDR":
            width, height, depth, color_type = struct.unpack_from(">IIBB", body)
            assert (depth, color_type) == (8, 6)
        elif kind == b"IDAT":
            compressed += body
        position += 12 + length
    raw = zlib.decompress(compressed)
    stride = 1 + 4 * width
    rows = []
    for y in range(height):
        line = raw[y * stride : (y + 1) * stride]
        assert line[0] == 0
        rows.append(
            [
                (line[1 + 4 * x], line[2 + 4 * x], line[3 + 4 * x], line[4 + 4 * x])
                for x in range(width)
            ]
        )
    return rows


# ---------- サイト名 ----------


def test_サイト名() -> None:
    assert SITE_NAME == "週刊AIトレンドニュース"


def test_タブと見出しにサイト名が出る(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    dated = (tmp_path / "2026-10-26.html").read_text(encoding="utf-8")

    assert _title(index) == "週刊AIトレンドニュース"
    # 日付ページは、どの回か分かるように日付を後ろに付ける（これまでと同じ形）。
    assert _title(dated) == "週刊AIトレンドニュース 2026-10-26"
    for html in [index, dated]:
        assert "<h1>週刊AIトレンドニュース</h1>" in html
        assert "AI 関連の注目記事" not in html


def test_プログラムやURLの名前は変えない(tmp_path: Path) -> None:
    written = write_site(_page(), tmp_path)
    names = {path.relative_to(tmp_path).as_posix() for path in written}
    assert {"index.html", "2026-10-26.html", "assets/style.css"} <= names

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "website-maker で自動生成" in html
    assert "websitemaker.hiddenTables" in html
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        assert tomllib.load(file)["project"]["name"] == "website-maker"


# ---------- アイコンの読み込み ----------


def test_アイコンを書き出す(tmp_path: Path) -> None:
    written = write_site(_page(), tmp_path)
    svg = tmp_path / "assets" / "favicon.svg"
    ico = tmp_path / "assets" / "favicon.ico"
    assert svg in written and ico in written
    assert svg.read_text(encoding="utf-8") == favicon_svg()
    assert ico.read_bytes() == favicon_ico()


def test_日付ページとトップページの両方でアイコンを読む(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)
    for name in ["index.html", "2026-10-26.html"]:
        html = (tmp_path / name).read_text(encoding="utf-8")
        assert '<link rel="icon" href="assets/favicon.ico" sizes="any">' in html
        assert '<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">' in html


@pytest.mark.parametrize(
    "page_url",
    [
        "https://example.com/index.html",  # サイトの直下
        "https://example.com/2026-10-26.html",
        "https://example.com/websitemaker/index.html",  # サブフォルダ
        "https://example.com/websitemaker/2026-10-26.html",
        "https://example.com/websitemaker/",  # index.html を省いた住所
    ],
)
def test_公開先の深さによらずアイコンが見つかる(tmp_path: Path, page_url: str) -> None:
    """ページの住所から見たアイコンの住所が、ページと同じフォルダの assets\\ を指す。"""
    write_site(_page(), tmp_path)
    page_dir = urlparse(urljoin(page_url, ".")).path
    html = render_html(_page(), page_title="テスト")
    hrefs = _icon_hrefs(html)
    assert len(hrefs) == 2
    for href in hrefs:
        # / で始めるとサイトの直下を指してしまい、サブフォルダに置いたときに見つからない。
        assert not href.startswith("/") and "://" not in href
        icon_path = urlparse(urljoin(page_url, href)).path
        assert icon_path.startswith(page_dir)
        assert (tmp_path / icon_path.removeprefix(page_dir)).is_file()


def test_作り直してもアイコンが残る(tmp_path: Path) -> None:
    write_site(_page(), tmp_path)
    (tmp_path / "assets" / "favicon.svg").unlink()
    (tmp_path / "assets" / "favicon.ico").write_bytes(b"")

    later = Page(target_date=date(2026, 11, 2), period_start=date(2026, 10, 27), sections=[])
    write_site(later, tmp_path)

    assert (tmp_path / "assets" / "favicon.svg").read_text(encoding="utf-8") == favicon_svg()
    assert (tmp_path / "assets" / "favicon.ico").read_bytes() == favicon_ico()
    for name in ["index.html", "2026-11-02.html"]:
        html = (tmp_path / name).read_text(encoding="utf-8")
        assert len(_icon_hrefs(html)) == 2
        assert "<h1>週刊AIトレンドニュース</h1>" in html


# ---------- アイコンの絵（SVG） ----------


def test_SVGは地が紺の角丸の正方形() -> None:
    root = ET.fromstring(favicon_svg())
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("viewBox") == "0 0 32 32"
    background = list(root)[0]
    assert background.tag == f"{SVG_NS}rect"
    assert (background.get("x"), background.get("y")) == ("0", "0")
    assert (background.get("width"), background.get("height")) == ("32", "32")
    assert float(background.get("rx", "0")) > 0
    assert background.get("fill") == "#003399"


def test_SVGの2枚目は白い紙面() -> None:
    paper = list(ET.fromstring(favicon_svg()))[1]
    assert paper.get("fill") == "#ffffff"
    # 新聞らしく縦長
    assert float(paper.get("height", "0")) > float(paper.get("width", "0"))


def test_SVGは文字やほかのファイルを使わない() -> None:
    """フォントは PC によって違うので、「AI」も図形で描く。外部の読み込みもしない。"""
    svg = favicon_svg()
    assert "<text" not in svg
    assert "href" not in svg
    assert "http://www.w3.org/2000/svg" in svg
    assert svg.count("http") == 1


# ---------- アイコンの絵（ICO） ----------


def test_ICOに3つの大きさが入る() -> None:
    images = _ico_images(favicon_ico())
    assert [(w, h) for w, h, _ in images] == [(size, size) for size in ICO_SIZES]
    assert ICO_SIZES == (16, 32, 48)
    for size, _, png in images:
        assert _decode_png(png) == render_pixels(size)


def _color(pixel: tuple[int, int, int, int]) -> str:
    """ピクセルを「紺」「白」「透明」「混ざった色」に分ける。"""
    *rgb, alpha = pixel
    if alpha == 0:
        return "透明"
    if alpha == 255 and tuple(rgb) == NAVY:
        return "紺"
    if alpha == 255 and tuple(rgb) == WHITE:
        return "白"
    return "混ざった色"


def _tab_icon() -> list[list[str]]:
    """タブに出る 16×16 の絵を、ICO から取り出して色の名前で返す。"""
    width, _, png = _ico_images(favicon_ico())[0]
    assert width == 16
    return [[_color(pixel) for pixel in row] for row in _decode_png(png)]


def test_16ピクセルで角が丸く地が紺() -> None:
    icon = _tab_icon()
    _, _, png = _ico_images(favicon_ico())[0]
    pixels = _decode_png(png)
    # 四隅は丸めた角の外なので、ほとんど透明（縁はなめらかにするため少しだけ色が残る）
    for x, y in [(0, 0), (15, 0), (0, 15), (15, 15)]:
        assert pixels[y][x][3] < 64
    assert icon[0][8] == "紺"  # 上の縁
    assert icon[15][8] == "紺"  # 下の縁
    assert icon[8][0] == "紺" and icon[8][1] == "紺" and icon[8][2] == "紺"  # 左の縁
    assert icon[8][13] == "紺" and icon[8][15] == "紺"  # 右の縁


def test_16ピクセルで白い紙面が見える() -> None:
    icon = _tab_icon()
    # 紙面の左右の余白（文字や線の外側）は白
    for y in range(3, 13):
        assert icon[y][3] == "白", y
        assert icon[y][12] == "白", y


def test_16ピクセルで紙面の上部にAIが見える() -> None:
    icon = _tab_icon()
    # 「A」：左右の脚と横棒は紺、内側の穴と脚の間は白
    assert icon[6][4] == icon[6][8] == "紺"
    assert icon[6][6] == "紺"  # 横棒
    assert icon[5][6] == "白"  # 穴
    assert icon[8][6] == "白"  # 脚の間
    # 「I」：縦に紺が続く
    assert all(icon[y][10] == icon[y][11] == "紺" for y in range(3, 9))
    # 「A」と「I」の間は白
    assert all(icon[y][9] == "白" for y in range(4, 9))


def test_16ピクセルでAIの下に横線が2本あり下の線が短い() -> None:
    icon = _tab_icon()

    def navy_run(y: int) -> list[int]:
        return [x for x in range(3, 13) if icon[y][x] == "紺"]

    upper, lower = navy_run(10), navy_run(12)
    assert upper == list(range(4, 12))
    assert lower == list(range(4, 9))
    assert len(lower) < len(upper)
    # 「AI」と線の間、線と線の間、線の下は白くあいている（タブで線がつぶれない）
    for y in [9, 11, 13]:
        assert navy_run(y) == [], y
