"""設定ファイル（keywords.txt / ai_trend_words.txt）と .env の読み込み。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# プロジェクトの一番上の階層。設定ファイルはここに置く。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

KEYWORDS_FILE = PROJECT_ROOT / "keywords.txt"
TREND_WORDS_FILE = PROJECT_ROOT / "ai_trend_words.txt"
OUTPUT_DIR = PROJECT_ROOT / "docs"

# はてブ検索で除外するブックマーク数のしきい値（.env で変えられる）
DEFAULT_HATENA_MIN_USERS = 10

# キーワード別セクションの TOP10 で、同じサイトから載せる最大件数（.env で変えられる）。
# note のスキは Zenn・Qiita のいいねより数が大きくなりやすく、そのまま並べると
# note が上位を占めてしまうため上限を設ける。0 以下にすると上限なしになる。
DEFAULT_MAX_PER_SITE = 4


class ConfigError(Exception):
    """設定ファイルが読めない・中身が空などの問題。"""


def read_word_list(path: Path) -> list[str]:
    """1行1項目の設定ファイルを読む。

    ・先頭の BOM、各行の前後の空白を取り除く
    ・空行と # で始まる行は無視する
    ・同じ項目が複数回書かれていたら、最初の1つだけ残す（順番は保つ）
    """
    if not path.exists():
        raise ConfigError(f"設定ファイルが見つかりません: {path}")

    # utf-8-sig は、Windows のメモ帳が付ける BOM を自動で取り除く。
    text = path.read_text(encoding="utf-8-sig")

    words: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        word = raw.strip()
        if not word or word.startswith("#"):
            continue
        if word in seen:
            continue
        seen.add(word)
        words.append(word)

    if not words:
        raise ConfigError(f"設定ファイルに項目が1つもありません: {path}")
    return words


@dataclass(frozen=True)
class Settings:
    """1回の実行で使う設定をまとめたもの。"""

    keywords: list[str]
    trend_words: list[str]
    output_dir: Path
    qiita_token: str | None
    hatena_min_users: int
    max_per_site: int


def _read_int_env(name: str, default: int) -> int:
    """環境変数を整数で読む。空・未設定・数字でない場合は既定値を使う。"""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_settings(
    keywords_file: Path = KEYWORDS_FILE,
    trend_words_file: Path = TREND_WORDS_FILE,
    output_dir: Path = OUTPUT_DIR,
) -> Settings:
    """設定ファイルと環境変数から設定を組み立てる。"""
    token = (os.environ.get("QIITA_TOKEN") or "").strip() or None
    return Settings(
        keywords=read_word_list(keywords_file),
        trend_words=read_word_list(trend_words_file),
        output_dir=output_dir,
        qiita_token=token,
        hatena_min_users=_read_int_env("HATENA_MIN_USERS", DEFAULT_HATENA_MIN_USERS),
        max_per_site=_read_int_env("MAX_PER_SITE", DEFAULT_MAX_PER_SITE),
    )
