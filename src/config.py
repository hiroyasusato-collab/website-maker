"""設定ファイル（keywords.txt / ai_trend_words.txt / display_order.txt）と .env の読み込み。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# プロジェクトの一番上の階層。設定ファイルはここに置く。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

KEYWORDS_FILE = PROJECT_ROOT / "keywords.txt"
TREND_WORDS_FILE = PROJECT_ROOT / "ai_trend_words.txt"
DISPLAY_ORDER_FILE = PROJECT_ROOT / "display_order.txt"
OUTPUT_DIR = PROJECT_ROOT / "docs"

# はてブ検索で除外するブックマーク数のしきい値（.env で変えられる）
DEFAULT_HATENA_MIN_USERS = 10

# キーワード別セクションの TOP10 で、同じサイトから載せる最大件数（.env で変えられる）。
# note のスキは Zenn・Qiita のいいねより数が大きくなりやすく、そのまま並べると
# note が上位を占めてしまうため上限を設ける。0 以下にすると上限なしになる。
DEFAULT_MAX_PER_SITE = 4

# --- X（旧 Twitter）---
# X の API は従量課金（投稿1件の読み取りで 0.005 ドル）。
# うっかりお金がかかることを防ぐため、既定では **止めてある**。
# 使うときは .env に X_ENABLED=true と書く。
DEFAULT_X_ENABLED = False

# 1回の実行で読む投稿の最大件数（日本語＋英語の合計）。費用の上限にあたる。
# 400件 = 最大 2.00 ドル（0.005 ドル × 400）。
DEFAULT_X_MAX_POSTS = 400

# 外部リンク付きの投稿だけに絞るかどうか。既定は絞らない。
DEFAULT_X_REQUIRE_LINK = False


class ConfigError(Exception):
    """設定ファイルが読めない・中身が空などの問題。"""


def read_word_list(path: Path, required: bool = True) -> list[str]:
    """1行1項目の設定ファイルを読む。

    ・先頭の BOM、各行の前後の空白を取り除く
    ・空行と # で始まる行は無視する
    ・同じ項目が複数回書かれていたら、最初の1つだけ残す（順番は保つ）

    required=False にすると、ファイルが無い・中身が空でもエラーにせず空の一覧を返す。
    display_order.txt のように「無くても動く」設定ファイルに使う。
    """
    if not path.exists():
        if not required:
            return []
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

    if not words and required:
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
    # ページに出す順番。keywords.txt（重複を省く優先順）とは別物。
    # 空のときは keywords.txt の順にそのまま並べる。
    display_order: list[str] = field(default_factory=list)
    # X は有料なので、指定しなかったときは「止まっている」状態を既定にする。
    x_enabled: bool = DEFAULT_X_ENABLED
    x_bearer_token: str | None = None
    x_max_posts: int = DEFAULT_X_MAX_POSTS
    x_require_link: bool = DEFAULT_X_REQUIRE_LINK


def _read_int_env(name: str, default: int) -> int:
    """環境変数を整数で読む。空・未設定・数字でない場合は既定値を使う。"""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# 「はい」として扱う書き方。true/false をどう書いても通じるようにする。
_TRUE_WORDS = frozenset({"true", "1", "yes", "y", "on"})
_FALSE_WORDS = frozenset({"false", "0", "no", "n", "off"})


def _read_int_env_strict(name: str, default: int) -> int:
    """環境変数を整数で読む。**書いてあるのに読めない場合はエラーにする。**

    お金に関わる設定（X_MAX_POSTS）に使う。`_read_int_env` のように黙って既定値に
    戻すと、「0 のつもりで 0.0 と書いた」ような場合に既定の400件が使われ、
    意図しない料金が発生してしまう。
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(
            f".env の {name} が整数として読めません（書かれている値: {raw!r}）。"
            f"半角の整数で書き直すか、行を消して既定値（{default}）に戻してください。"
        ) from None


def _read_bool_env(name: str, default: bool) -> bool:
    """環境変数を true / false で読む。

    お金がかかる機能のスイッチなので、読み取れない書き方のときは既定値（止めたまま）
    に倒す。勝手に動き出さないようにするため。
    """
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in _TRUE_WORDS:
        return True
    if raw in _FALSE_WORDS:
        return False
    return default


def load_settings(
    keywords_file: Path = KEYWORDS_FILE,
    trend_words_file: Path = TREND_WORDS_FILE,
    output_dir: Path = OUTPUT_DIR,
    display_order_file: Path = DISPLAY_ORDER_FILE,
) -> Settings:
    """設定ファイルと環境変数から設定を組み立てる。"""
    token = (os.environ.get("QIITA_TOKEN") or "").strip() or None
    x_token = (os.environ.get("X_BEARER_TOKEN") or "").strip() or None
    return Settings(
        keywords=read_word_list(keywords_file),
        trend_words=read_word_list(trend_words_file),
        output_dir=output_dir,
        # 無くても動く（その場合は keywords.txt の順に並べる）。
        display_order=read_word_list(display_order_file, required=False),
        qiita_token=token,
        hatena_min_users=_read_int_env("HATENA_MIN_USERS", DEFAULT_HATENA_MIN_USERS),
        max_per_site=_read_int_env("MAX_PER_SITE", DEFAULT_MAX_PER_SITE),
        x_enabled=_read_bool_env("X_ENABLED", DEFAULT_X_ENABLED),
        x_bearer_token=x_token,
        # お金に関わる設定なので、読めない値は黙って既定値に戻さずエラーにする。
        x_max_posts=_read_int_env_strict("X_MAX_POSTS", DEFAULT_X_MAX_POSTS),
        x_require_link=_read_bool_env("X_REQUIRE_LINK", DEFAULT_X_REQUIRE_LINK),
    )
