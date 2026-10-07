"""ページに載せるデータの形。

ページの構造は Page > Section > Ranking > Article の入れ子になっている。

    Page      … 1回分のページ全体（例：2026-10-07 の回）
    Section   … 見出し1つ分（例：「AI駆動開発」「AI業界トレンド」）
    Ranking   … 表1つ分。AI業界トレンドと技術資料・リポジトリは、
                 1セクションに複数の表を持つ（数え方が違う表は混ぜない）
    Article   … 表の1行
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# 取得元の表示名。ページの「サイト名」列に出る。
SITE_ZENN = "Zenn"
SITE_QIITA = "Qiita"
SITE_NOTE = "note"
SITE_HATENA = "はてなブックマーク"
SITE_HACKER_NEWS = "Hacker News"
SITE_X = "X"
SITE_GITHUB = "GitHub"
SITE_GIHYO = "技術評論社"

# 「いいね数」列の見出し。取得元によって数え方が違うので呼び分ける。
LABEL_LIKES = "いいね"
LABEL_BOOKMARKS = "ブックマーク"
LABEL_POINTS = "ポイント"
LABEL_STARS = "スター"

# セクションの種類。ページ上の置き場所と作りが種類ごとに違う。
#   trend     … AI業界トレンド（はてブ・HN・X）。ページの先頭
#   resources … 技術資料・リポジトリ（GitHub・技術評論社）。トレンドの次
#   keyword   … キーワード別。最後にまとめて並ぶ
#   gap       … 表を置かない位置（display_order.txt の「（空き）」）。中身は無い
KIND_TREND = "trend"
KIND_RESOURCES = "resources"
KIND_KEYWORD = "keyword"
KIND_GAP = "gap"


@dataclass(frozen=True)
class Article:
    """記事1件。published_at は必ず日本時間（タイムゾーン付き）にそろえる。

    match_text は AI 判定に使う文字列。ふつうは None で、そのときは title を見る。
    GitHub のように**表示用のタイトルを短く切っている**取得元では、切る前の全文を
    ここに入れる。そうしないと、切り落とした部分にだけ AI の単語があった記事を
    「AI 関連ではない」と判定してしまう。
    """

    title: str
    url: str
    score: int
    published_at: datetime
    site: str
    match_text: str | None = None


@dataclass
class Ranking:
    """表1つ分。

    score_label: 数の列の見出し。**None にすると数の列そのものを出さない**。
                 技術評論社のように人気の数字が無い取得元で使う。
    caption: 表の小見出し。キーワード別セクションでは None（見出しが1つで足りる）。
    notes:   取得できなかった取得元の説明。要件5のとおり、黙って消さずにページに残す。
    """

    score_label: str | None
    articles: list[Article] = field(default_factory=list)
    caption: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Section:
    """見出し1つ分。

    kind は上の KIND_* のどれか。ページ上の置き場所と作りが種類ごとに違うため、
    表示のときに見分ける。
    """

    heading: str
    rankings: list[Ranking] = field(default_factory=list)
    kind: str = KIND_KEYWORD


def gap_section() -> Section:
    """表を置かない位置（display_order.txt の「（空き）」）を表すセクション。

    2列に並べるとき、ここを飛ばして次の表を左列に送るために使う。
    """
    return Section(heading="", kind=KIND_GAP)


@dataclass(frozen=True)
class ReferenceLink:
    """参考リンク1件（reference_links.txt の1行）。

    取得はせず、ページにリンクを置くだけのもの。利用規約でプログラムからの収集が
    禁止されているサイト（Speaker Deck）などを、手で開けるようにするために使う。
    """

    label: str
    url: str


@dataclass
class Page:
    """1回分のページ全体。"""

    target_date: date
    period_start: date
    sections: list[Section] = field(default_factory=list)
    # 参考リンク。空のときはページに欄ごと出さない。
    reference_links: list[ReferenceLink] = field(default_factory=list)
