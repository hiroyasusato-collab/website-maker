"""サイトのアイコン（ブラウザのタブやお気に入りに出る小さな絵）。

形：角を丸めた濃い紺（#003399）の正方形の中に、白い新聞の紙面。紙面の上部に紺の太字で
「AI」、その下に紺の横線を2本（下の線は短い）。

絵はここに図形として1か所だけ書き、そこから2種類のファイルを作る。
    favicon.svg  … 図形のまま。どの大きさでもくっきり出る（今の Edge・Chrome・Firefox が使う）
    favicon.ico  … 16・32・48 ピクセルの絵を1つにまとめたもの（SVG を使えないブラウザ用）
追加の部品を入れずに済むよう、ICO の絵（PNG）は標準の zlib だけで描く。

「AI」は文字（フォント）ではなく図形で描く。フォントは PC によって違い、タブの
16 ピクセルでは字の形が崩れやすいため。座標は 32×32 のマス目で、紙面・文字・線の
端をなるべく偶数にそろえ、16 ピクセルに縮めたときにもにじみにくくしている。
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from functools import lru_cache

NAVY = (0x00, 0x33, 0x99)
WHITE = (0xFF, 0xFF, 0xFF)

# 図形のマス目の大きさ（SVG の viewBox と同じ）。
GRID = 32

# ICO に入れる絵の大きさ。16 はタブ、32 は高解像度の画面のタブ、48 はお気に入りなどで使われる。
ICO_SIZES = (16, 32, 48)

# 1ピクセルを何×何の点で調べて色を決めるか（縁をなめらかにするため）。
SAMPLES_PER_SIDE = 8

Point = tuple[float, float]
Color = tuple[int, int, int]


@dataclass(frozen=True)
class RoundRect:
    """角を丸めた長方形（radius=0 ならただの長方形）。"""

    left: float
    top: float
    right: float
    bottom: float
    color: Color
    radius: float = 0.0

    def contains(self, x: float, y: float) -> bool:
        if not (self.left <= x < self.right and self.top <= y < self.bottom):
            return False
        # 角の丸みの外側（四隅の小さな三角）にある点だけを外す。
        cx = min(max(x, self.left + self.radius), self.right - self.radius)
        cy = min(max(y, self.top + self.radius), self.bottom - self.radius)
        return (x - cx) ** 2 + (y - cy) ** 2 <= self.radius**2

    def svg(self) -> str:
        width = _num(self.right - self.left)
        height = _num(self.bottom - self.top)
        rounded = f' rx="{_num(self.radius)}"' if self.radius else ""
        return (
            f'<rect x="{_num(self.left)}" y="{_num(self.top)}" width="{width}" '
            f'height="{height}"{rounded} fill="{_hex(self.color)}"/>'
        )


@dataclass(frozen=True)
class Shape:
    """折れ線で囲んだ形。輪郭を2つ以上書くと、内側の輪郭は穴になる（even-odd の決まり）。"""

    outlines: tuple[tuple[Point, ...], ...]
    color: Color

    def contains(self, x: float, y: float) -> bool:
        # 点から右へ線を伸ばし、輪郭を何回またぐかを数える。奇数なら内側。
        inside = False
        for outline in self.outlines:
            for (x1, y1), (x2, y2) in zip(outline, outline[1:] + outline[:1]):
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
        return inside

    def svg(self) -> str:
        path = " ".join(
            "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in outline) + " Z"
            for outline in self.outlines
        )
        return f'<path d="{path}" fill="{_hex(self.color)}" fill-rule="evenodd"/>'


# 下から順に重ねて描く。
SHAPES: tuple[RoundRect | Shape, ...] = (
    # 地：角を丸めた紺の正方形
    RoundRect(0, 0, 32, 32, NAVY, radius=6),
    # 新聞の紙面
    RoundRect(6, 4, 26, 28, WHITE, radius=1),
    # 「A」：上の角を落とした太い形に、四角い穴と脚の間の切れ込みを入れる。
    # 16 ピクセルでは横5×縦6 ピクセルの太字の A になる。
    Shape(
        (
            (
                (10, 6),
                (16, 6),
                (18, 10),
                (18, 18),
                (14, 18),
                (14, 14),
                (12, 14),
                (12, 18),
                (8, 18),
                (8, 10),
            ),
            ((12, 9), (14, 9), (14, 12), (12, 12)),
        ),
        NAVY,
    ),
    # 「I」
    RoundRect(20, 6, 24, 18, NAVY),
    # 横線2本（下の線は短い）
    RoundRect(8, 20, 24, 22, NAVY),
    RoundRect(8, 24, 18, 26, NAVY),
)


def _num(value: float) -> str:
    return f"{value:g}"


def _hex(color: Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def favicon_svg() -> str:
    """SVG 形式のアイコン（文字列）。"""
    body = "\n".join(f"  {shape.svg()}" for shape in SHAPES)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}">\n{body}\n</svg>\n'


def render_pixels(size: int) -> list[list[tuple[int, int, int, int]]]:
    """size×size ピクセルの絵を、行ごとの (R, G, B, 不透明度) の並びで返す。

    1ピクセルの中を SAMPLES_PER_SIDE×SAMPLES_PER_SIDE の点で調べ、各点で一番上に
    重なっている図形の色を平均する。どの図形にも入らない点（丸めた角の外）は透明。
    """
    scale = GRID / size
    step = 1 / SAMPLES_PER_SIDE
    offsets = [(i + 0.5) * step for i in range(SAMPLES_PER_SIDE)]
    total = SAMPLES_PER_SIDE**2

    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            red = green = blue = covered = 0
            for oy in offsets:
                for ox in offsets:
                    x, y = (px + ox) * scale, (py + oy) * scale
                    color = None
                    for shape in SHAPES:
                        if shape.contains(x, y):
                            color = shape.color
                    if color is not None:
                        red += color[0]
                        green += color[1]
                        blue += color[2]
                        covered += 1
            if covered:
                row.append(
                    (
                        round(red / covered),
                        round(green / covered),
                        round(blue / covered),
                        round(255 * covered / total),
                    )
                )
            else:
                row.append((0, 0, 0, 0))
        rows.append(row)
    return rows


def png_bytes(size: int) -> bytes:
    """size×size の PNG（色＋透明度）を作る。"""
    raw = b"".join(b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in render_pixels(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    # 8ビット・色の種類6（RGBA）
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


@lru_cache(maxsize=1)
def favicon_ico() -> bytes:
    """ICO 形式のアイコン。ICO_SIZES の大きさの PNG を1つのファイルにまとめる。

    描くのに少し時間がかかるので、1回の実行の中では最初に作ったものを使い回す。
    """
    images = [png_bytes(size) for size in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, image in zip(ICO_SIZES, images):
        # 幅・高さ・色数・予約・面の数・1ピクセルのビット数・データの長さ・データの位置
        entries += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    return header + entries + b"".join(images)
