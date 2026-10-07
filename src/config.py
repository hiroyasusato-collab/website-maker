"""設定ファイル（keywords.txt / ai_trend_words.txt / display_order.txt /
reference_links.txt）と .env の読み込み。"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.models import ReferenceLink

logger = logging.getLogger(__name__)

# プロジェクトの一番上の階層。設定ファイルはここに置く。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

KEYWORDS_FILE = PROJECT_ROOT / "keywords.txt"
TREND_WORDS_FILE = PROJECT_ROOT / "ai_trend_words.txt"
DISPLAY_ORDER_FILE = PROJECT_ROOT / "display_order.txt"
REFERENCE_LINKS_FILE = PROJECT_ROOT / "reference_links.txt"
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


def read_lines(path: Path, required: bool = True) -> list[str]:
    """設定ファイルを1行ずつ読む（すべての設定ファイルの土台）。

    ・先頭の BOM、各行の前後の空白を取り除く
    ・空行と # で始まる行は無視する
    ・**重複は取り除かない**（display_order.txt の「（空き）」のように、
      同じ行を何度も書く設定があるため）

    required=False にすると、ファイルが無くてもエラーにせず空の一覧を返す。
    display_order.txt のように「無くても動く」設定ファイルに使う。
    """
    if not path.exists():
        if not required:
            return []
        raise ConfigError(f"設定ファイルが見つかりません: {path}")

    # utf-8-sig は、Windows のメモ帳が付ける BOM を自動で取り除く。
    text = path.read_text(encoding="utf-8-sig")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def read_word_list(path: Path) -> list[str]:
    """1行1単語の設定ファイルを読む（ai_trend_words.txt 用）。

    同じ単語が複数回書かれていたら、最初の1つだけ残す（順番は保つ）。
    中身が1つも無ければエラーにする。
    """
    words: list[str] = []
    seen: set[str] = set()
    for word in read_lines(path):
        if word in seen:
            continue
        seen.add(word)
        words.append(word)

    if not words:
        raise ConfigError(f"設定ファイルに項目が1つもありません: {path}")
    return words


# --- キーワードのまとまり（keywords.txt の1行）---

# keywords.txt の1行に複数の単語を書くときの区切り。
# 半角カンマのほか、日本語入力のまま打てる全角カンマ・読点も受け付ける。
KEYWORD_SEPARATOR = re.compile(r"[,，、]")

# 複数の単語を1つの表にまとめたときの、表の名前のつなぎ文字。
# 例: 「RAG, ナレッジグラフ」 → 表の名前は「RAG・ナレッジグラフ」
KEYWORD_JOIN = "・"

# display_order.txt で「ここには表を置かない」ことを表す書き方。
GAP_MARKERS = frozenset({"（空き）", "(空き)", "空き", "-"})


@dataclass(frozen=True)
class KeywordGroup:
    """キーワード別セクション1つ分（keywords.txt の1行）。

    name  … 表の名前。ページの見出しと display_order.txt で使う
    words … 実際に検索する単語。1行に複数書いた場合は、どれかに当たる記事を
            1つの表にまとめる（例：RAG とナレッジグラフ）
    """

    name: str
    words: tuple[str, ...]


def parse_keyword_line(line: str) -> KeywordGroup | None:
    """keywords.txt の1行を1つのまとまりにする。単語が無い行は None。"""
    words = tuple(word.strip() for word in KEYWORD_SEPARATOR.split(line) if word.strip())
    if not words:
        return None
    return KeywordGroup(name=KEYWORD_JOIN.join(words), words=words)


def read_keywords(path: Path) -> list[KeywordGroup]:
    """keywords.txt を読む。並び順が「重複を省く優先順」になる（要件4）。

    1行に複数の単語をカンマで並べると、どれかに当たる記事を1つの表にまとめる。
    同じ名前の行が2回あれば最初の1つだけ残す。
    """
    groups: list[KeywordGroup] = []
    seen: set[str] = set()
    for line in read_lines(path):
        group = parse_keyword_line(line)
        if group is None or group.name in seen:
            continue
        seen.add(group.name)
        groups.append(group)

    if not groups:
        raise ConfigError(f"設定ファイルに項目が1つもありません: {path}")
    return groups


def read_display_order(path: Path) -> list[str | None]:
    """display_order.txt を読む。**None は「表を置かない位置」**を表す。

    ・「（空き）」と書いた行は None になる（2列の片側を空けるため）
    ・keywords.txt と同じようにカンマ区切りで書いてもよい。
      その場合は「・」でつないだ名前に直してから照らし合わせる
    ・ファイルが無い・中身が空でもエラーにしない（その場合は keywords.txt の順になる）
    """
    order: list[str | None] = []
    seen: set[str] = set()
    for line in read_lines(path, required=False):
        if line in GAP_MARKERS:
            order.append(None)
            continue
        group = parse_keyword_line(line)
        if group is None or group.name in seen:
            continue
        seen.add(group.name)
        order.append(group.name)
    return order


# --- 参考リンク（reference_links.txt の1行）---

# リンクとして認める URL の形。**http:// と https:// だけ**。
# ページは GitHub Pages で公開するので、javascript: のような危ない書き方を
# そのまま <a href> に入れないための歯止め。
# 末尾の \S は「:// のすぐ後ろに何か文字があること」。`https://` だけの行を弾く。
REFERENCE_URL_PATTERN = re.compile(r"https?://\S", re.IGNORECASE)

# 「表示名 | URL」の区切り。全角の縦棒（｜）でも書けるようにする。
REFERENCE_LINK_SEPARATORS = "|｜"


def parse_reference_link(line: str) -> ReferenceLink | None:
    """reference_links.txt の1行を参考リンク1件にする。読めない行は None。

    書き方は `表示名 | URL`。URL だけ書いた場合は URL をそのまま表示名にする。

    **行の中から「http:// または https:// で始まるところ」を探し、そこから後ろを URL**、
    手前を表示名として扱う。区切りの文字で切り分けないのは、URL 自体に縦棒が入ることが
    あるため（例：検索結果の `?q=AI|LLM`）。URL に空白は入らないので、
    最初の空白までを URL とする。
    """
    match = REFERENCE_URL_PATTERN.search(line)
    if match is None:
        return None

    url = line[match.start() :].split()[0]
    # 表示名側の末尾に残る区切り（| や ｜）を取り除く。
    label = line[: match.start()].strip().rstrip(REFERENCE_LINK_SEPARATORS).strip()
    return ReferenceLink(label=label or url, url=url)


def read_reference_links(path: Path) -> list[ReferenceLink]:
    """reference_links.txt を読む。無い・空のときは空の一覧を返す。

    空の一覧を返すと、ページから「参考リンク」の欄ごと出なくなる。
    同じ URL が複数回書かれていたら、最初の1つだけ残す（順番は保つ）。
    """
    links: list[ReferenceLink] = []
    seen: set[str] = set()
    for line in read_lines(path, required=False):
        link = parse_reference_link(line)
        if link is None:
            logger.warning(
                "%s の次の行は http:// または https:// で始まっていないため読み飛ばしました: %s",
                path.name,
                line,
            )
            continue
        if link.url in seen:
            continue
        seen.add(link.url)
        links.append(link)
    return links


@dataclass(frozen=True)
class Settings:
    """1回の実行で使う設定をまとめたもの。"""

    keywords: list[KeywordGroup]
    trend_words: list[str]
    output_dir: Path
    qiita_token: str | None
    hatena_min_users: int
    max_per_site: int
    # ページに出す順番。keywords.txt（重複を省く優先順）とは別物。
    # 空のときは keywords.txt の順にそのまま並べる。None は「表を置かない位置」。
    display_order: list[str | None] = field(default_factory=list)
    # 取得はせず、ページにリンクを置くだけのもの。空のときは欄ごと出さない。
    reference_links: list[ReferenceLink] = field(default_factory=list)
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
    reference_links_file: Path = REFERENCE_LINKS_FILE,
) -> Settings:
    """設定ファイルと環境変数から設定を組み立てる。"""
    token = (os.environ.get("QIITA_TOKEN") or "").strip() or None
    x_token = (os.environ.get("X_BEARER_TOKEN") or "").strip() or None
    return Settings(
        keywords=read_keywords(keywords_file),
        trend_words=read_word_list(trend_words_file),
        output_dir=output_dir,
        # 無くても動く（その場合は keywords.txt の順に並べる）。
        display_order=read_display_order(display_order_file),
        # 無くても動く（その場合は「参考リンク」の欄が出ない）。
        reference_links=read_reference_links(reference_links_file),
        qiita_token=token,
        hatena_min_users=_read_int_env("HATENA_MIN_USERS", DEFAULT_HATENA_MIN_USERS),
        max_per_site=_read_int_env("MAX_PER_SITE", DEFAULT_MAX_PER_SITE),
        x_enabled=_read_bool_env("X_ENABLED", DEFAULT_X_ENABLED),
        x_bearer_token=x_token,
        # お金に関わる設定なので、読めない値は黙って既定値に戻さずエラーにする。
        x_max_posts=_read_int_env_strict("X_MAX_POSTS", DEFAULT_X_MAX_POSTS),
        x_require_link=_read_bool_env("X_REQUIRE_LINK", DEFAULT_X_REQUIRE_LINK),
    )
