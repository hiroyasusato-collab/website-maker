"""並べ替え・上位10件・重複の除去のテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.aggregate import (
    TOP_N,
    count_by_site,
    dedupe_within,
    exclude_used,
    normalize_url,
    pick_top,
    rank,
    select_with_site_cap,
    within_window,
)
from src.models import SITE_NOTE, SITE_QIITA, SITE_ZENN, Article
from src.timeutil import JST

BASE = datetime(2026, 10, 5, 12, 0, tzinfo=JST)


def _article(title: str, score: int, url: str | None = None, days: int = 0) -> Article:
    # url に "" を渡せるよう、既定値の判定は None で行う。
    return Article(
        title=title,
        url=f"https://zenn.dev/u/articles/{title}" if url is None else url,
        score=score,
        published_at=BASE + timedelta(days=days),
        site=SITE_ZENN,
    )


# ---------- URL のそろえ方 ----------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # 末尾のスラッシュ
        ("https://example.com/a", "https://example.com/a/"),
        # http と https
        ("http://example.com/a", "https://example.com/a"),
        # ホスト名の大文字小文字
        ("https://Example.COM/a", "https://example.com/a"),
        # 計測用パラメータ
        ("https://example.com/a?utm_source=x", "https://example.com/a"),
        ("https://example.com/a?utm_source=x&utm_medium=y", "https://example.com/a"),
        ("https://example.com/a?fbclid=z", "https://example.com/a"),
        # 末尾の #...
        ("https://example.com/a#section", "https://example.com/a"),
    ],
)
def test_同じ記事として扱うURL(left: str, right: str) -> None:
    assert normalize_url(left) == normalize_url(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # 別の記事なので区別する
        ("https://example.com/a", "https://example.com/b"),
        ("https://example.com/a", "https://other.com/a"),
        # 記事を指す本来のパラメータは残す
        ("https://news.ycombinator.com/item?id=1", "https://news.ycombinator.com/item?id=2"),
    ],
)
def test_別の記事として扱うURL(left: str, right: str) -> None:
    assert normalize_url(left) != normalize_url(right)


def test_空のURLは空文字になる() -> None:
    assert normalize_url("") == ""
    assert normalize_url("   ") == ""


@pytest.mark.parametrize("bad", ["https://[broken", "http://[::1::2]/x", "https://["])
def test_読めないURLで例外を投げない(bad: str) -> None:
    """壊れた URL が1件混ざっただけでページ全体の作成が止まらないこと（要件5）。"""
    assert normalize_url(bad) == ""


def test_読めないURLの記事は落とすが他は残る() -> None:
    articles = [
        _article("壊れたURLの記事", 999, url="https://[broken"),
        _article("ふつうの記事", 10, url="https://example.com/ok"),
    ]
    used: set[str] = set()
    assert [a.title for a in pick_top(articles, used)] == ["ふつうの記事"]


# ---------- 期間の絞り込み ----------


def test_期間内の記事だけ残す() -> None:
    since = datetime(2026, 10, 1, 0, 0, tzinfo=JST)
    until = datetime(2026, 10, 8, 0, 0, tzinfo=JST)
    articles = [
        _article("古すぎる", 1, days=-20),  # 2026-09-15
        _article("期間内", 1, days=0),  # 2026-10-05
        _article("未来の記事", 999, days=10),  # 2026-10-15
    ]
    assert [a.title for a in within_window(articles, since, until)] == ["期間内"]


def test_期間の境目の扱い() -> None:
    since = datetime(2026, 10, 1, 0, 0, tzinfo=JST)
    until = datetime(2026, 10, 8, 0, 0, tzinfo=JST)

    def at(moment: datetime) -> Article:
        return Article("記事", "https://example.com/a", 1, moment, SITE_ZENN)

    # 開始時刻ちょうどは含む。
    assert within_window([at(since)], since, until)
    # 終了時刻ちょうどは含まない（翌日 0:00 なので期間外）。
    assert not within_window([at(until)], since, until)
    # 終了時刻の1秒前は含む。
    assert within_window([at(until - timedelta(seconds=1))], since, until)


def test_未来の投稿日を落とす() -> None:
    """note は予約投稿ができるため、投稿日が未来の記事が返ることがある。"""
    since = datetime(2026, 10, 1, 0, 0, tzinfo=JST)
    until = datetime(2026, 10, 8, 0, 0, tzinfo=JST)
    future = Article(
        "予約投稿", "https://note.com/u/n/x", 9999, datetime(2026, 11, 1, tzinfo=JST), SITE_ZENN
    )
    assert within_window([future], since, until) == []


# ---------- 並べ替え ----------


def test_いいね数の多い順に並ぶ() -> None:
    articles = [_article("c", 5), _article("a", 100), _article("b", 50)]
    assert [a.title for a in rank(articles)] == ["a", "b", "c"]


def test_いいね数が同じなら新しい記事が先() -> None:
    old = _article("古い", 10, days=-2)
    new = _article("新しい", 10, days=0)
    assert [a.title for a in rank([old, new])] == ["新しい", "古い"]


def test_上位10件で切る() -> None:
    articles = [_article(f"記事{i:02d}", i) for i in range(30)]
    assert len(rank(articles)) == TOP_N


def test_件数を指定して切れる() -> None:
    articles = [_article(f"記事{i}", i) for i in range(10)]
    assert len(rank(articles, limit=3)) == 3


def test_並べ替えは何度やっても同じ結果になる() -> None:
    """いいね数・日付・タイトルがすべて同じでも順番がぶれないこと。"""
    articles = [_article("b", 1), _article("a", 1), _article("c", 1)]
    assert [a.title for a in rank(articles)] == [a.title for a in rank(list(reversed(articles)))]


# ---------- 重複の除去 ----------


def test_同じURLは1件にする() -> None:
    same = "https://example.com/same"
    articles = [_article("1件目", 10, url=same), _article("2件目", 99, url=same + "/")]
    result = dedupe_within(articles)
    assert len(result) == 1
    # 先に来たほうを残す（並び順は変えない）
    assert result[0].title == "1件目"


def test_URLが空の記事は落とす() -> None:
    assert dedupe_within([_article("x", 1, url="")]) == []


def test_すでに使われたURLを除く() -> None:
    used = {normalize_url("https://example.com/a")}
    articles = [
        _article("載せない", 10, url="https://example.com/a?utm_source=x"),
        _article("載せる", 5, url="https://example.com/b"),
    ]
    assert [a.title for a in exclude_used(articles, used)] == ["載せる"]


def test_すでに使われたURLの集合は書き換えない() -> None:
    used = {normalize_url("https://example.com/a")}
    before = set(used)
    exclude_used([_article("x", 1, url="https://example.com/b")], used)
    assert used == before


# ---------- セクションをまたぐ重複（要件4） ----------


def test_同じ記事は先のセクションにだけ載る() -> None:
    shared = "https://zenn.dev/u/articles/shared"
    used: set[str] = set()

    first = pick_top([_article("共通の記事", 10, url=shared)], used)
    second = pick_top([_article("共通の記事", 10, url=shared)], used)

    assert [a.title for a in first] == ["共通の記事"]
    assert second == []


def test_載らなかった記事は後のセクションに残る() -> None:
    """ここが大事。上位10件に入らなかった記事を予約してしまってはいけない。"""
    used: set[str] = set()
    # 11件のうち上位10件だけが1つ目のセクションに載る。
    candidates = [_article(f"記事{i:02d}", i) for i in range(11)]
    first = pick_top(candidates, used)

    assert len(first) == TOP_N
    # 一番いいねが少ない「記事00」は載らなかったので、後のセクションに出せる。
    dropped = _article("記事00", 0)
    second = pick_top([dropped], used)
    assert [a.title for a in second] == ["記事00"]


def test_セクション内の重複もまとめる() -> None:
    same = "https://example.com/same"
    used: set[str] = set()
    result = pick_top(
        [_article("1件目", 10, url=same), _article("2件目", 99, url=same)],
        used,
    )
    assert len(result) == 1


# ---------- 1サイトあたりの上限 ----------


def _from(site: str, title: str, score: int) -> Article:
    return Article(
        title=title,
        url=f"https://example.com/{site}/{title}",
        score=score,
        published_at=BASE,
        site=site,
    )


def test_同じサイトからは上限までしか載せない() -> None:
    """note のスキは数が大きくなりやすいので、1サイトの件数に上限を設ける。

    キーワード別セクションの取得元は Zenn・Qiita・note の3つ。
    上限4件なら 4+4+4=12 ≥ 10 なので、上限を超えずに TOP10 を埋められる。
    """
    # note がいいね数で上位を独占している状況を作る。
    articles = [_from(SITE_NOTE, f"note{i}", 1000 - i) for i in range(10)]
    articles += [_from(SITE_ZENN, f"zenn{i}", 100 - i) for i in range(10)]
    articles += [_from(SITE_QIITA, f"qiita{i}", 50 - i) for i in range(10)]

    result = select_with_site_cap(articles, limit=10, max_per_site=4)

    counts = count_by_site(result)
    assert len(result) == 10
    assert counts[SITE_NOTE] == 4, "note は上限の4件まで"
    assert counts[SITE_ZENN] == 4
    assert counts[SITE_QIITA] == 2
    # どのサイトも上限を超えていない。
    assert all(count <= 4 for count in counts.values())


def test_上限なしならnoteが独占する() -> None:
    """上限を入れる前の動き。これを避けるための変更であることを示す。"""
    articles = [_from(SITE_NOTE, f"note{i}", 1000 - i) for i in range(10)]
    articles += [_from(SITE_ZENN, f"zenn{i}", 100 - i) for i in range(10)]
    articles += [_from(SITE_QIITA, f"qiita{i}", 50 - i) for i in range(10)]

    result = select_with_site_cap(articles, limit=10, max_per_site=0)
    assert count_by_site(result) == {SITE_NOTE: 10}


def test_サイトが2つしかなければ上限を超えて埋める() -> None:
    """取得元が1つ失敗したときの動き。

    サイト2つ × 上限4件 = 8件しか上限内で選べないので、残り2件は上限を超えて埋める。
    8件で止めるより、いいね数の多い記事を10件出すほうがよいと判断した。
    """
    articles = [_from(SITE_NOTE, f"note{i}", 1000 - i) for i in range(10)]
    articles += [_from(SITE_ZENN, f"zenn{i}", 100 - i) for i in range(10)]

    result = select_with_site_cap(articles, limit=10, max_per_site=4)

    counts = count_by_site(result)
    assert len(result) == 10
    assert counts[SITE_ZENN] == 4
    # 足りない2件は、いいね数の多い note から補われる。
    assert counts[SITE_NOTE] == 6


def test_上限で飛ばした分は他のサイトで埋める() -> None:
    articles = [
        _from(SITE_NOTE, "note1", 500),
        _from(SITE_NOTE, "note2", 400),
        _from(SITE_NOTE, "note3", 300),
        _from(SITE_ZENN, "zenn1", 50),
        _from(SITE_QIITA, "qiita1", 40),
    ]
    result = select_with_site_cap(articles, limit=4, max_per_site=2)

    titles = [a.title for a in result]
    # note は上位2件だけ。残りは Zenn と Qiita で埋まる。
    assert titles == ["note1", "note2", "zenn1", "qiita1"]


def test_上限を守ったうえでいいね数順に並ぶ() -> None:
    articles = [
        _from(SITE_NOTE, "note1", 500),
        _from(SITE_NOTE, "note2", 400),
        _from(SITE_NOTE, "note3", 300),
        _from(SITE_ZENN, "zenn1", 450),
        _from(SITE_ZENN, "zenn2", 350),
    ]
    result = select_with_site_cap(articles, limit=4, max_per_site=2)

    # note は上位2件、Zenn は上位2件。表示はいいね数順。
    assert [a.title for a in result] == ["note1", "zenn1", "note2", "zenn2"]
    scores = [a.score for a in result]
    assert scores == sorted(scores, reverse=True)


def test_他のサイトの記事が無ければ上限を超えて埋める() -> None:
    """上限は独占を防ぐためのもの。他に出せる記事が無いなら件数を減らさない。"""
    articles = [_from(SITE_NOTE, f"note{i}", 100 - i) for i in range(7)]

    result = select_with_site_cap(articles, limit=10, max_per_site=4)

    # 7件すべて出す（4件に絞らない）。
    assert len(result) == 7
    assert count_by_site(result)[SITE_NOTE] == 7


def test_足りない分だけ上限を超えて埋める() -> None:
    articles = [_from(SITE_NOTE, f"note{i}", 100 - i) for i in range(10)]
    articles += [_from(SITE_ZENN, "zenn1", 1)]

    result = select_with_site_cap(articles, limit=10, max_per_site=4)

    counts = count_by_site(result)
    assert len(result) == 10
    assert counts[SITE_ZENN] == 1
    assert counts[SITE_NOTE] == 9


def test_上限を超えて埋めるときもいいね数順になる() -> None:
    articles = [_from(SITE_NOTE, f"note{i}", 100 - i) for i in range(6)]
    result = select_with_site_cap(articles, limit=6, max_per_site=2)

    assert [a.title for a in result] == ["note0", "note1", "note2", "note3", "note4", "note5"]


@pytest.mark.parametrize("cap", [0, -1])
def test_上限を0以下にすると上限なしになる(cap: int) -> None:
    articles = [_from(SITE_NOTE, f"note{i}", 100 - i) for i in range(10)]
    articles += [_from(SITE_ZENN, "zenn1", 1)]

    result = select_with_site_cap(articles, limit=10, max_per_site=cap)

    # いいね数順にそのまま上位10件（note だけになる）。
    assert count_by_site(result)[SITE_NOTE] == 10


def test_上限が件数より大きければ何も変わらない() -> None:
    articles = [_from(SITE_NOTE, "note1", 10), _from(SITE_ZENN, "zenn1", 5)]
    assert select_with_site_cap(articles, limit=10, max_per_site=99) == rank(articles, 10)


def test_記事が無くても落ちない() -> None:
    assert select_with_site_cap([], limit=10, max_per_site=4) == []


def test_サイトごとの件数を数える() -> None:
    articles = [
        _from(SITE_NOTE, "a", 1),
        _from(SITE_NOTE, "b", 1),
        _from(SITE_ZENN, "c", 1),
    ]
    assert count_by_site(articles) == {SITE_NOTE: 2, SITE_ZENN: 1}


def test_pick_topに上限を渡せる() -> None:
    articles = [_from(SITE_NOTE, f"note{i}", 1000 - i) for i in range(10)]
    articles += [_from(SITE_ZENN, f"zenn{i}", 100 - i) for i in range(10)]
    articles += [_from(SITE_QIITA, f"qiita{i}", 50 - i) for i in range(10)]

    used: set[str] = set()
    result = pick_top(articles, used, limit=10, max_per_site=4)

    assert count_by_site(result)[SITE_NOTE] == 4
    # 載せた10件だけが予約される（上限で飛ばした note の記事は後のセクションに残る）。
    assert len(used) == 10


def test_pick_topは上限を指定しなければ絞らない() -> None:
    articles = [_from(SITE_NOTE, f"note{i}", 1000 - i) for i in range(10)]
    articles += [_from(SITE_ZENN, "zenn1", 1)]

    used: set[str] = set()
    result = pick_top(articles, used, limit=10)

    assert count_by_site(result)[SITE_NOTE] == 10


def test_上限で飛ばした記事は後のセクションに残る() -> None:
    """上限で載らなかった記事も「載っていない」ので、後のセクションに出てよい。"""
    articles = [_from(SITE_NOTE, f"note{i}", 100 - i) for i in range(6)]
    articles += [_from(SITE_ZENN, f"zenn{i}", 50 - i) for i in range(6)]

    used: set[str] = set()
    first = pick_top(articles, used, limit=4, max_per_site=2)
    assert [a.title for a in first] == ["note0", "note1", "zenn0", "zenn1"]

    # 同じ候補をもう一度渡すと、まだ載っていない記事が出る。
    second = pick_top(articles, used, limit=4, max_per_site=2)
    assert [a.title for a in second] == ["note2", "note3", "zenn2", "zenn3"]


def test_取得元が混ざっても並べ替えられる() -> None:
    zenn = Article("Zennの記事", "https://zenn.dev/a", 30, BASE, SITE_ZENN)
    qiita = Article("Qiitaの記事", "https://qiita.com/b", 50, BASE, SITE_QIITA)
    used: set[str] = set()
    assert [a.site for a in pick_top([zenn, qiita], used)] == [SITE_QIITA, SITE_ZENN]
