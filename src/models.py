"""ページに載せるデータの形。

ページの構造は Page > Section > Ranking > Article の入れ子になっている。

    Page      … 1回分のページ全体（例：2026-10-07 の回）
    Section   … 見出し1つ分（例：「AI駆動開発」「AI業界トレンド」）
    Ranking   … 表1つ分。AI業界トレンドだけは1セクションに2つの表を持つ
                 （はてブとHNは数え方が違うので混ぜない）
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

# 「いいね数」列の見出し。取得元によって数え方が違うので呼び分ける。
LABEL_LIKES = "いいね"
LABEL_BOOKMARKS = "ブックマーク"
LABEL_POINTS = "ポイント"


@dataclass(frozen=True)
class Article:
    """記事1件。published_at は必ず日本時間（タイムゾーン付き）にそろえる。"""

    title: str
    url: str
    score: int
    published_at: datetime
    site: str


@dataclass
class Ranking:
    """表1つ分。

    caption: 表の小見出し。キーワード別セクションでは None（見出しが1つで足りる）。
    notes:   取得できなかった取得元の説明。要件5のとおり、黙って消さずにページに残す。
    """

    score_label: str
    articles: list[Article] = field(default_factory=list)
    caption: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Section:
    """見出し1つ分。

    is_trend は AI業界トレンドのセクションだけ True。
    ページの作りが違うため（見出しの下に表が4つ並ぶ）、表示のときに見分ける。
    """

    heading: str
    rankings: list[Ranking] = field(default_factory=list)
    is_trend: bool = False


@dataclass
class Page:
    """1回分のページ全体。"""

    target_date: date
    period_start: date
    sections: list[Section] = field(default_factory=list)
