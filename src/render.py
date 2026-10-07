"""HTML の書き出し。

出力先は docs\\（GitHub Pages の公開フォルダ）:
    docs\\index.html        最新回の中身 ＋ 下に過去回へのリンク一覧
    docs\\YYYY-MM-DD.html   バックナンバー（実行ごとに増える）
    docs\\assets\\style.css  見た目
    docs\\.nojekyll          GitHub に余計な変換をさせないための空ファイル
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models import Page
from src.timeutil import now_jst

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_NAME = "page.html.j2"
STYLE_SOURCE = TEMPLATE_DIR / "style.css"

# バックナンバーのファイル名の形。この形のファイルだけを過去回として一覧に出す。
BACKNUMBER_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.html$")


@dataclass(frozen=True)
class Backnumber:
    filename: str
    label: str


def find_backnumbers(output_dir: Path, exclude: str | None = None) -> list[Backnumber]:
    """docs\\ の中から YYYY-MM-DD.html を探し、新しい順に並べて返す（要件6）。

    exclude には、一覧に載せたくないファイル名（通常は最新回）を渡す。
    """
    if not output_dir.exists():
        return []

    names = sorted(
        (
            path.name
            for path in output_dir.iterdir()
            if path.is_file() and BACKNUMBER_PATTERN.match(path.name)
        ),
        reverse=True,
    )
    return [
        Backnumber(filename=name, label=name.removesuffix(".html"))
        for name in names
        if name != exclude
    ]


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        # 記事タイトルに < > & が入ってもページが壊れないよう自動エスケープする。
        autoescape=select_autoescape(enabled_extensions=("j2", "html"), default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_html(
    page: Page,
    *,
    page_title: str,
    backnumbers: list[Backnumber] | None = None,
    generated_at: datetime | None = None,
) -> str:
    """ページ1枚分の HTML を文字列で返す。"""
    template = _environment().get_template(TEMPLATE_NAME)
    return template.render(
        page=page,
        page_title=page_title,
        backnumbers=backnumbers or [],
        generated_at=generated_at or now_jst(),
    )


def write_site(page: Page, output_dir: Path) -> list[Path]:
    """docs\\ に一式を書き出し、書いたファイルの一覧を返す。

    バックナンバーを先に書いてから index.html を作る。そうすることで、
    最新回も含めたファイル一覧から過去回のリンクを作れる。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    # GitHub に余計な変換をさせない（中身は空）。
    nojekyll = output_dir / ".nojekyll"
    if not nojekyll.exists():
        nojekyll.write_text("", encoding="utf-8")
    written.append(nojekyll)

    assets_dir = output_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    style_target = assets_dir / "style.css"
    style_target.write_text(STYLE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    written.append(style_target)

    date_label = page.target_date.isoformat()

    # バックナンバー（この回の固定ページ）
    dated_name = f"{date_label}.html"
    dated_path = output_dir / dated_name
    dated_path.write_text(
        render_html(page, page_title=f"AI 関連の注目記事 {date_label}"),
        encoding="utf-8",
    )
    written.append(dated_path)

    # トップページ（最新回の中身 ＋ 過去回へのリンク一覧）
    index_path = output_dir / "index.html"
    index_path.write_text(
        render_html(
            page,
            page_title="AI 関連の注目記事",
            backnumbers=find_backnumbers(output_dir, exclude=dated_name),
        ),
        encoding="utf-8",
    )
    written.append(index_path)

    return written
