"""X（旧 Twitter）の取得のテスト。

**実際の X には一切接続しない。** X の API は従量課金なので、接続すると料金がかかる。
偽の取得関数に、本物と同じ形の応答を返させて確かめる。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pytest

from src.models import SITE_X
from src.sources import x_posts
from tests.conftest import RecordingFetch, load_fixture_json

WORDS = ["AI", "LLM", "GPT", "Claude", "生成AI", "Hugging Face", "機械学習"]
EMPTY: dict[str, Any] = {"meta": {"result_count": 0}}


# ---------- 検索条件の組み立て ----------


def test_検索条件に単語と絞り込みが入る() -> None:
    queries = x_posts.build_query(["AI", "LLM"], "ja")

    assert len(queries) == 1
    query = queries[0]
    assert "(AI OR LLM)" in query
    assert "lang:ja" in query
    # 返信とリポストを除く（要件のとおり）。
    assert "-is:reply" in query
    assert "-is:retweet" in query


def test_空白を含む単語は引用符で囲む() -> None:
    """Hugging Face を囲まないと Hugging と Face の2語として扱われてしまう。"""
    query = x_posts.build_query(["Hugging Face"], "en")[0]
    assert '"Hugging Face"' in query


def test_実際の単語リストが1本に収まる() -> None:
    """同梱の ai_trend_words.txt が512文字の上限に収まることを確かめる。

    収まらなくなるとリクエスト数が増えて費用が上がるので、増やしたときに気づけるようにする。
    """
    from src.config import TREND_WORDS_FILE, read_word_list

    words = read_word_list(TREND_WORDS_FILE)
    for lang in x_posts.LANGUAGES:
        queries = x_posts.build_query(words, lang)
        assert len(queries) == 1, f"lang:{lang} が1本に収まらない（単語を減らしてください）"
        assert len(queries[0]) <= x_posts.QUERY_LIMIT


def test_上限を超えたら複数本に分ける() -> None:
    many = [f"word{i:03d}" for i in range(200)]
    queries = x_posts.build_query(many, "ja")

    assert len(queries) > 1
    for query in queries:
        assert len(query) <= x_posts.QUERY_LIMIT


def test_分けたときは警告を出す(caplog: pytest.LogCaptureFixture) -> None:
    """分けるとリクエスト数＝費用が増えるので、黙って分けない。"""
    many = [f"word{i:03d}" for i in range(200)]
    with caplog.at_level(logging.WARNING):
        x_posts.build_query(many, "ja")
    assert "費用も増えます" in caplog.text


def test_1本に収まるときは警告を出さない(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        x_posts.build_query(["AI"], "ja")
    assert caplog.text == ""


# ---------- 費用の上限 ----------


def test_読む件数を費用の上限から決める() -> None:
    # 400件（日本語＋英語の合計）／検索条件1本 → 2リクエスト → 1回200件だが上限100件
    assert x_posts.results_per_request(400, 1) == 100
    # 100件／1本 → 2リクエスト → 1回50件
    assert x_posts.results_per_request(100, 1) == 50
    # 400件／2本 → 4リクエスト → 1回100件
    assert x_posts.results_per_request(400, 2) == 100
    # 200件／2本 → 4リクエスト → 1回50件
    assert x_posts.results_per_request(200, 2) == 50


def test_読む件数はAPIの範囲に収める() -> None:
    # 少なすぎる指定でも 10 未満にはならない（API の下限）。
    assert x_posts.results_per_request(2, 1) == x_posts.MIN_RESULTS_PER_REQUEST
    assert x_posts.results_per_request(0, 1) == x_posts.MIN_RESULTS_PER_REQUEST
    # 多すぎる指定でも 100 を超えない（API の上限）。
    assert x_posts.results_per_request(100000, 1) == x_posts.MAX_RESULTS_PER_REQUEST


def test_費用の上限が実際のリクエストに反映される(since: datetime) -> None:
    fetch = RecordingFetch([], last=EMPTY)
    x_posts.collect("ja", ["AI"], fetch, "dummy-token", x_posts.PostBudget(100))

    _, params, _ = fetch.calls[0]
    # 100件 ÷ 2言語 = 1回50件
    assert params["max_results"] == 50


def test_上限400件のときの読み取り件数と費用() -> None:
    """既定の400件で、日本語＋英語を合わせて最大400件・最大2ドルに収まること。"""
    per_request = x_posts.results_per_request(400, 1)
    requests_total = len(x_posts.LANGUAGES) * 1
    total_posts = per_request * requests_total

    assert total_posts <= 400
    assert total_posts * x_posts.COST_PER_POST <= 2.0


# ---------- 読み取り枠（PostBudget）----------
#
# ここが壊れると X_MAX_POSTS を超えて読み取り、想定より高い料金になる。


def test_枠の範囲で要求件数を返す() -> None:
    budget = x_posts.PostBudget(250)
    assert budget.take(100) == 100
    assert budget.remaining == 150
    assert budget.take(100) == 100
    assert budget.remaining == 50
    # 残り50件なので、100件要求しても50件まで。
    assert budget.take(100) == 50
    assert budget.remaining == 0


def test_枠を使い切ったら0を返す() -> None:
    budget = x_posts.PostBudget(100)
    assert budget.take(100) == 100
    assert budget.take(100) == 0, "0 は「もう呼んではいけない」の意味"
    assert budget.remaining == 0


def test_10件も残っていなければ呼ばせない() -> None:
    """API は1回10件未満を受け付けないので、中途半端に残っても呼ばない。"""
    budget = x_posts.PostBudget(5)
    assert budget.take(100) == 0
    assert budget.remaining == 5


def test_枠が0なら一度も呼ばせない() -> None:
    budget = x_posts.PostBudget(0)
    assert budget.take(100) == 0


def test_枠に負の数を渡しても0として扱う() -> None:
    assert x_posts.PostBudget(-100).take(100) == 0


def test_枠は日本語と英語で共有する(since: datetime) -> None:
    """言語ごとに別の枠にすると、合計が X_MAX_POSTS を超えてしまう。"""
    budget = x_posts.PostBudget(120)
    fetch = RecordingFetch([], last=EMPTY)

    x_posts.collect("ja", ["AI"], fetch, "dummy-token", budget)
    x_posts.collect("en", ["AI"], fetch, "dummy-token", budget)

    requested = [params["max_results"] for _, params, _ in fetch.calls]
    assert sum(requested) <= 120, "合計が枠を超えてはいけない"


def test_枠が小さくても上限を超えて読まない(since: datetime) -> None:
    """以前は1回10件の下限に切り上げてしまい、枠が2件でも20件読んでいた。"""
    budget = x_posts.PostBudget(2)
    fetch = RecordingFetch([], last=EMPTY)

    x_posts.collect("ja", ["AI"], fetch, "dummy-token", budget)
    x_posts.collect("en", ["AI"], fetch, "dummy-token", budget)

    assert fetch.calls == [], "枠が10件未満なら一度も接続しない"


def test_検索条件が多くても上限を超えて読まない(since: datetime) -> None:
    """検索条件が多数に分かれても、合計が枠を超えないこと。"""
    many = [f"word{i:03d}" for i in range(400)]
    budget = x_posts.PostBudget(400)
    fetch = RecordingFetch([], last=EMPTY)

    x_posts.collect("ja", many, fetch, "dummy-token", budget)
    x_posts.collect("en", many, fetch, "dummy-token", budget)

    requested = [params["max_results"] for _, params, _ in fetch.calls]
    assert sum(requested) <= 400


def test_枠を使い切ったら警告を出して打ち切る(
    since: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    """検索条件の本数より枠が少ない場合、途中で止めて知らせる。"""
    many = [f"word{i:03d}" for i in range(400)]  # 10本に分かれる
    budget = x_posts.PostBudget(50)  # 1回10件 × 5回で尽きる
    fetch = RecordingFetch([], last=EMPTY)

    with caplog.at_level(logging.WARNING):
        x_posts.collect("ja", many, fetch, "dummy-token", budget)

    assert "打ち切り" in caplog.text
    requested = [params["max_results"] for _, params, _ in fetch.calls]
    assert sum(requested) == 50, "枠をちょうど使い切って止まる"
    assert len(fetch.calls) == 5, "10本あっても5回で止まる"


# ---------- やり直しをしない ----------


def test_やり直しをしない指定で呼ぶ(since: datetime) -> None:
    """通信がやり直されると、サーバー側では読み取りが済んでいて二重に課金される恐れがある。"""
    fetch = RecordingFetch([], last=EMPTY)
    x_posts.collect("ja", ["AI"], fetch, "dummy-token", x_posts.PostBudget(400))
    assert fetch.retries == [0]


# ---------- 合言葉の確かめ方 ----------


@pytest.mark.parametrize(
    "bad",
    ["abc\ndef", "abc def", "abc\tdef", "abc\r\ndef", " abc\ndef "],
)
def test_合言葉に空白や改行があれば接続しない(since: datetime, bad: str) -> None:
    """改行入りの値を送ると、requests の例外に値が載ってログに漏れることがある。"""
    fetch = RecordingFetch([], last=EMPTY)
    with pytest.raises(x_posts.XConfigError) as info:
        x_posts.collect("ja", ["AI"], fetch, bad, x_posts.PostBudget(400))

    assert fetch.calls == [], "接続していないこと"
    # エラーメッセージに合言葉そのものを載せない。
    assert "abc" not in str(info.value)


def test_検索条件が長すぎれば接続しない(since: datetime) -> None:
    """1語だけで512文字を超える場合、分けても収まらない。呼ぶ前に止める。"""
    fetch = RecordingFetch([], last=EMPTY)
    with pytest.raises(x_posts.XConfigError, match="上限に収まりません"):
        x_posts.collect("ja", ["x" * 600], fetch, "dummy-token", x_posts.PostBudget(400))
    assert fetch.calls == [], "接続していないこと"


# ---------- 検索条件の指定 ----------


def test_関連度順で検索する(since: datetime) -> None:
    """人気の投稿を取りこぼしにくくするため（要件のとおり）。"""
    fetch = RecordingFetch([], last=EMPTY)
    x_posts.collect("ja", ["AI"], fetch, "dummy-token", x_posts.PostBudget(400))

    url, params, headers = fetch.calls[0]
    assert url == x_posts.SEARCH_URL
    assert params["sort_order"] == "relevancy"
    assert "lang:ja" in params["query"]
    # 必要な項目を明示しないと created_at も like 数も返ってこない。
    assert "created_at" in params["tweet.fields"]
    assert "public_metrics" in params["tweet.fields"]
    assert "entities" in params["tweet.fields"]
    # 合言葉を Authorization に付ける。
    assert headers["Authorization"] == "Bearer dummy-token"


def test_合言葉が無ければ接続せずエラーにする(since: datetime) -> None:
    """お金のかかる接続を、設定不足のまま行わないこと。"""
    fetch = RecordingFetch([], last=EMPTY)
    with pytest.raises(x_posts.XConfigError, match="X_BEARER_TOKEN"):
        x_posts.collect("ja", ["AI"], fetch, None, x_posts.PostBudget(400))
    assert fetch.calls == [], "接続していないこと"


# ---------- 応答の読み取り ----------


def test_必要な4項目を取り出す() -> None:
    payload = load_fixture_json("x_search.json")
    articles = x_posts.parse_posts(payload, WORDS, require_link=False)

    first = next(a for a in articles if "Claude Opus 5.5" in a.title)
    assert first.url == "https://x.com/i/web/status/1975000000000000001"
    assert first.score == 980
    assert first.site == SITE_X
    # 2026-10-05T03:12:45Z は日本時間 12:12:45
    assert first.published_at.isoformat() == "2026-10-05T12:12:45+09:00"


def test_本文をタイトル代わりに整える() -> None:
    """投稿には記事のようなタイトルが無いので、本文の先頭を使う。"""
    assert x_posts.make_title("1行目\n2行目\n\n3行目") == "1行目 2行目 3行目"
    assert x_posts.make_title("  前後の空白  ") == "前後の空白"


def test_長い本文は切り詰める() -> None:
    title = x_posts.make_title("あ" * 300)
    assert len(title) == x_posts.TITLE_MAX_CHARS + 1  # 末尾の「…」の分
    assert title.endswith("…")


def test_AI以外の投稿は落とす() -> None:
    """検索条件に単語を入れていても、関連度順では関係の薄い投稿が混ざることがある。"""
    payload = load_fixture_json("x_search.json")
    articles = x_posts.parse_posts(payload, WORDS, require_link=False)
    assert all("ラーメン" not in a.title for a in articles)


def test_日付が無い投稿は落とす() -> None:
    payload = load_fixture_json("x_search.json")
    articles = x_posts.parse_posts(payload, WORDS, require_link=False)
    assert all("日付が無い" not in a.title for a in articles)


def test_投稿IDは文字列として扱う() -> None:
    """ID は非常に大きい数値なので、数値にすると下の桁が壊れることがある。"""
    payload = {
        "data": [
            {
                "id": 1975000000000000001,
                "text": "AI の投稿",
                "created_at": "2026-10-05T03:00:00.000Z",
                "public_metrics": {"like_count": 1},
            }
        ]
    }
    articles = x_posts.parse_posts(payload, WORDS, require_link=False)
    assert articles[0].url == "https://x.com/i/web/status/1975000000000000001"


def test_応答が空でも落ちない() -> None:
    empty_payloads: tuple[dict[str, Any], ...] = (
        {},
        {"meta": {"result_count": 0}},
        {"data": []},
    )
    for payload in empty_payloads:
        assert x_posts.parse_posts(payload, WORDS, require_link=False) == []


# ---------- 外部リンクの判定 ----------


def test_外部リンクを見分ける() -> None:
    assert x_posts.has_external_link(
        {"entities": {"urls": [{"expanded_url": "https://docs.example.com/a"}]}}
    )


def test_X内へのリンクは外部リンクに数えない() -> None:
    """引用投稿や画像は entities.urls に x.com へのリンクとして入る。"""
    for internal in (
        "https://x.com/u/status/123",
        "https://twitter.com/u/status/123",
        "https://www.x.com/u/status/123",
        "https://pic.twitter.com/abc",
    ):
        assert not x_posts.has_external_link({"entities": {"urls": [{"expanded_url": internal}]}})


def test_リンクが無ければ外部リンクなし() -> None:
    assert not x_posts.has_external_link({})
    assert not x_posts.has_external_link({"entities": {}})
    assert not x_posts.has_external_link({"entities": {"urls": []}})


def test_壊れたリンクでも落ちない() -> None:
    """読めない URL が混ざっても例外を投げず、外部リンク無しとして扱う。"""
    assert not x_posts.has_external_link(
        {
            "entities": {
                "urls": [
                    {"expanded_url": "https://["},  # urlsplit が例外を投げる形
                    {"expanded_url": ""},  # 空
                    {"expanded_url": "/relative/path"},  # ホスト名が無い
                    {"expanded_url": "mailto:someone@example.com"},  # ホスト名が無い
                    {},  # expanded_url 自体が無い
                ]
            }
        }
    )


def test_unwound_urlも見る() -> None:
    """X は短縮前の URL を unwound_url で返すことがある。"""
    assert x_posts.has_external_link(
        {"entities": {"urls": [{"unwound_url": "https://news.example.com/a"}]}}
    )


def test_外部リンク必須にするとリンク無しが落ちる() -> None:
    payload = load_fixture_json("x_search.json")
    articles = x_posts.parse_posts(payload, WORDS, require_link=True)

    titles = [a.title for a in articles]
    # 外部リンク付きの投稿だけ残る。
    assert any("Claude Opus 5.5" in t for t in titles)
    # リンク無しの投稿は落ちる。
    assert not any("生成AIで社内の問い合わせ" in t for t in titles)
    # 引用（X 内へのリンク）だけの投稿も落ちる。
    assert not any("引用だけの投稿" in t for t in titles)


def test_既定では外部リンクの有無で区別しない() -> None:
    payload = load_fixture_json("x_search.json")
    articles = x_posts.parse_posts(payload, WORDS, require_link=False)

    titles = [a.title for a in articles]
    assert any("Claude Opus 5.5" in t for t in titles)
    assert any("生成AIで社内の問い合わせ" in t for t in titles)


# ---------- 複数本に分かれたときの取得 ----------


def test_分けた本数だけ検索する(since: datetime) -> None:
    many = [f"word{i:03d}" for i in range(200)]
    queries = x_posts.build_query(many, "ja")

    fetch = RecordingFetch([], last=EMPTY)
    x_posts.collect("ja", many, fetch, "dummy-token", x_posts.PostBudget(400))
    assert len(fetch.calls) == len(queries)


def test_同じ投稿が重なっても1件にする(since: datetime) -> None:
    many = [f"word{i:03d}" for i in range(200)]
    payload: dict[str, Any] = {
        "data": [
            {
                "id": "111",
                "text": "word001 の投稿",
                "created_at": "2026-10-05T03:00:00.000Z",
                "public_metrics": {"like_count": 5},
            }
        ]
    }
    fetch = RecordingFetch([], last=payload)
    articles = x_posts.collect("ja", many, fetch, "dummy-token", x_posts.PostBudget(400))
    assert len(articles) == 1
