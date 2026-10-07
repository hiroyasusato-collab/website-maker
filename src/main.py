"""入口。`python src\\main.py` で実行する。

やること:
  1. 設定ファイル（keywords.txt / ai_trend_words.txt）と .env を読む
  2. 各サイトから直近7日間の記事を集める
  3. docs\\ に index.html と日付ごとのページを書き出す

このあと本人が git で commit して push すると GitHub Pages に反映される。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# `python src\main.py` と直接実行されたとき、`from src...` を解決できるようにする。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import ConfigError, load_settings  # noqa: E402
from src.fetcher import HttpFetcher  # noqa: E402
from src.models import Page  # noqa: E402
from src.pipeline import build_page  # noqa: E402
from src.render import write_site  # noqa: E402


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )


def _load_dotenv() -> None:
    """.env があれば読み込む。無くても動く（合言葉はどちらも省略可）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_PROJECT_ROOT / ".env")


def _report(page: Page) -> None:
    """集計結果を画面に出す。失敗した取得元があればそれも出す。"""
    print()
    print("=" * 56)
    print(f"  ページを作りました（{page.target_date.isoformat()} 時点）")
    print("=" * 56)

    problems: list[str] = []
    for section in page.sections:
        for ranking in section.rankings:
            label = ranking.caption or section.heading
            print(f"  {label}: {len(ranking.articles)} 件")
            problems.extend(ranking.notes)

    if problems:
        print()
        print("  取得できなかったものがありました:")
        for problem in problems:
            print(f"    - {problem}")
        print("  （他のセクションはそのまま表示されます）")


def main() -> int:
    _setup_logging()
    _load_dotenv()

    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"設定ファイルの読み込みに失敗しました: {error}", file=sys.stderr)
        return 1

    print(f"キーワード {len(settings.keywords)} 個: {' / '.join(settings.keywords)}")
    print(f"AI判定の単語 {len(settings.trend_words)} 個")
    print(f"Qiita トークン: {'あり' if settings.qiita_token else 'なし（1時間60回まで）'}")
    print()

    fetcher = HttpFetcher()
    page = build_page(settings, fetcher.json, fetcher.text)

    written = write_site(page, settings.output_dir)
    _report(page)

    print()
    print("  書き出したファイル:")
    for path in written:
        print(f"    {path}")
    print()
    print("  次にすること: git で commit して push すると GitHub Pages に反映されます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
