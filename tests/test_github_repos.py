"""GitHub（公式 API）からリポジトリを取る処理のテスト。実際の GitHub にはつながない。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from src.models import SITE_GITHUB
from src.sources import github_repos
from src.timeutil import JST
from src.trend_filter import filter_ai_related
from tests.conftest import RecordingFetch, load_fixture_json

TREND_WORDS = ["AI", "LLM", "GPT", "Claude", "OpenAI", "ChatGPT", "Agent"]


@pytest.fixture
def until() -> datetime:
    """期間の終わり（実行日の翌日 0:00）。未来の作成日を落とすのに使う。"""
    return datetime(2026, 10, 8, 0, 0, 0, tzinfo=JST)


def _fetch(pages: list[Any] | None = None) -> RecordingFetch:
    """1ページ目に fixture、2ページ目以降は空を返す偽の取得関数。"""
    return RecordingFetch(pages or [load_fixture_json("github_search.json")], {"items": []})


# ---------- 応答の読み取り ----------


def test_4つの項目を取り出せる(since: datetime, until: datetime) -> None:
    articles = github_repos.collect(since, _fetch(), until=until)
    first = articles[0]

    assert first.title == "openai/math"
    assert first.url == "https://github.com/openai/math"
    assert first.score == 5334
    assert first.published_at.isoformat() == "2026-10-07T06:47:02+09:00"
    assert first.site == SITE_GITHUB


def test_説明文をタイトルにつなげる(since: datetime, until: datetime) -> None:
    """リポジトリ名だけでは中身が分からないので、説明文もタイトルに入れる。"""
    articles = github_repos.collect(since, _fetch(), until=until)
    titles = [a.title for a in articles]

    assert "Jakeschincariol/replica-skill — Eleven free Claude skills that clone any app" in titles
    # 説明文が無いリポジトリは名前だけ。
    assert "openai/math" in titles


def test_長い説明文は切る() -> None:
    title = github_repos.build_title("owner/name", "あ" * 300)
    assert len(title) == github_repos.TITLE_MAX_CHARS
    assert title.endswith("…")


def test_説明文の改行は詰める() -> None:
    assert github_repos.build_title("o/n", "1行目\n2行目") == "o/n — 1行目 2行目"


def test_説明文が空白だけなら名前だけにする() -> None:
    assert github_repos.build_title("o/n", "   ") == "o/n"
    assert github_repos.build_title("o/n", None) == "o/n"


def test_スター数の多い順で返る(since: datetime, until: datetime) -> None:
    """サーバー側が並べてくれるので、取得した順がそのままスター数順になる。"""
    scores = [a.score for a in github_repos.collect(since, _fetch(), until=until)]
    assert scores == sorted(scores, reverse=True)


# ---------- 期間と不正なデータ ----------


def test_未来の作成日は落とす(since: datetime, until: datetime) -> None:
    """期間の上限を渡したときは、作成日が未来のリポジトリを入れない。"""
    titles = [a.title for a in github_repos.collect(since, _fetch(), until=until)]
    assert not any("future-repo" in t for t in titles)


def test_期間より前の作成日は落とす(until: datetime) -> None:
    late = datetime(2026, 10, 5, 0, 0, 0, tzinfo=JST)
    articles = github_repos.collect(late, _fetch(), until=until)
    assert [a.title for a in articles] == ["openai/math"]


def test_読めないURLは落とす(since: datetime, until: datetime) -> None:
    """壊れた URL が1件混ざってもページ全体を失わない（要件5）。"""
    urls = [a.url for a in github_repos.collect(since, _fetch(), until=until)]
    assert all("[broken" not in url for url in urls)


def test_項目が足りない応答は飛ばす(since: datetime, until: datetime) -> None:
    fetch = RecordingFetch(
        [
            {
                "items": [
                    {"full_name": "a/b"},  # URL と作成日が無い
                    {"html_url": "https://github.com/c/d"},  # 名前が無い
                    {
                        "full_name": "e/f",
                        "html_url": "https://github.com/e/f",
                        "created_at": "2026-10-05T00:00:00Z",
                        "stargazers_count": 7,
                    },
                ]
            }
        ],
        {"items": []},
    )
    articles = github_repos.collect(since, fetch, until=until)
    assert [a.title for a in articles] == ["e/f"]


def test_スター数が無ければ0にする(since: datetime, until: datetime) -> None:
    fetch = RecordingFetch(
        [
            {
                "items": [
                    {
                        "full_name": "e/f",
                        "html_url": "https://github.com/e/f",
                        "created_at": "2026-10-05T00:00:00Z",
                    }
                ]
            }
        ],
        {"items": []},
    )
    assert github_repos.collect(since, fetch, until=until)[0].score == 0


def test_同じリポジトリは1回だけ入れる(since: datetime, until: datetime) -> None:
    one = {
        "full_name": "e/f",
        "html_url": "https://github.com/e/f",
        "created_at": "2026-10-05T00:00:00Z",
        "stargazers_count": 7,
    }
    fetch = RecordingFetch([{"items": [one, dict(one)]}], {"items": []})
    assert len(github_repos.collect(since, fetch, until=until)) == 1


# ---------- 問い合わせの組み立て ----------


def test_スター数順の指定で呼ぶ(since: datetime) -> None:
    fetch = _fetch()
    github_repos.collect(since, fetch)
    _, params, headers = fetch.calls[0]

    assert params["sort"] == "stars"
    assert params["order"] == "desc"
    assert params["per_page"] == github_repos.PER_PAGE
    assert params["page"] == 1
    # API の版を明示して、仕様変更で急に挙動が変わらないようにしている。
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_作成日は1日前から指定する(since: datetime) -> None:
    """created:>= は UTC の日付で解釈されるため、1日前から広く取って後で絞る。

    こうしないと、日本時間の 0:00〜9:00 に作られたリポジトリを落としてしまう。
    """
    fetch = _fetch()
    github_repos.collect(since, fetch)  # since = 2026-10-01 0:00（日本時間）
    assert fetch.calls[0][1]["q"] == "created:>=2026-09-30"


# ---------- ページ送り ----------


def test_AIが必要数そろったら次のページに進まない(since: datetime, until: datetime) -> None:
    fetch = _fetch()

    def wanted(title: str) -> bool:
        return True  # 全部ほしい扱いにする

    github_repos.collect(since, fetch, is_wanted=wanted, needed=3, until=until)
    assert len(fetch.calls) == 1


def _full_page(prefix: str) -> dict[str, Any]:
    """1ページ分（100件）ちょうど返る応答。ページ送りが続く状況を作る。"""
    return {
        "items": [
            {
                "full_name": f"{prefix}/n{i}",
                "html_url": f"https://github.com/{prefix}/n{i}",
                "created_at": "2026-10-05T00:00:00Z",
                "stargazers_count": 100 - i,
            }
            for i in range(github_repos.PER_PAGE)
        ]
    }


def test_AIがそろわなければページを進める(since: datetime, until: datetime) -> None:
    """AI 以外が続いても表が埋まるように、必要数そろうまで進める。"""
    fetch = RecordingFetch([_full_page("a"), _full_page("b")], {"items": []})

    def wanted(title: str) -> bool:
        return title.startswith("b/")  # 2ページ目にだけ「ほしい」ものがある

    github_repos.collect(since, fetch, is_wanted=wanted, needed=10, until=until)
    assert len(fetch.calls) == 2, "1ページ目で足りなければ2ページ目に進む"


def test_1ページ分に満たなければそこで止まる(since: datetime, until: datetime) -> None:
    """返ってきた件数が1ページ分より少なければ、それが最後のページ。"""
    fetch = _fetch()
    github_repos.collect(since, fetch, is_wanted=lambda t: False, needed=10, until=until)
    assert len(fetch.calls) == 1


def test_空の応答で止まる(since: datetime) -> None:
    fetch = RecordingFetch([{"items": []}], {"items": []})
    assert github_repos.collect(since, fetch) == []
    assert len(fetch.calls) == 1


def test_ページ上限を超えて取らない(since: datetime, until: datetime) -> None:
    """アクセス上限（検索 API は1分に10回）に当たらないよう上限を決めてある。"""
    full = {
        "items": [
            {
                "full_name": f"o/n{i}",
                "html_url": f"https://github.com/o/n{i}",
                "created_at": "2026-10-05T00:00:00Z",
                "stargazers_count": 1,
            }
            for i in range(github_repos.PER_PAGE)
        ]
    }
    fetch = RecordingFetch([], full)
    github_repos.collect(since, fetch, is_wanted=lambda t: False, needed=10, until=until)
    assert len(fetch.calls) == github_repos.MAX_PAGES


# ---------- 切る前の全文で AI 判定する ----------


LONG_DESC = (
    "A fast, batteries-included toolkit for building production web services with queues, "
    "caching, background jobs, scheduled tasks and a tiny footprint, now with an LLM helper"
)


def test_判定用の全文は切らない() -> None:
    """表示用のタイトルは切るが、AI 判定に使う全文は切らない。"""
    full = github_repos.build_full_text("someorg/toolkit", LONG_DESC)
    title = github_repos.build_title("someorg/toolkit", LONG_DESC)

    assert "LLM" in full, "全文には末尾の LLM が残る"
    assert len(title) == github_repos.TITLE_MAX_CHARS
    assert "LLM" not in title, "表示用は切られるので残らない"


def test_説明文の末尾にだけAIの単語があっても拾える(since: datetime, until: datetime) -> None:
    """ここが抜けると、説明文の長いリポジトリを「AI 関連ではない」と誤判定する。"""
    fetch = RecordingFetch(
        [
            {
                "items": [
                    {
                        "full_name": "someorg/toolkit",
                        "html_url": "https://github.com/someorg/toolkit",
                        "description": LONG_DESC,
                        "stargazers_count": 1000,
                        "created_at": "2026-10-05T00:00:00Z",
                    }
                ]
            }
        ],
        {"items": []},
    )
    article = github_repos.collect(since, fetch, until=until)[0]

    # 表に出るタイトルは切られている。
    assert "LLM" not in article.title
    # 判定用の全文は切られていないので、AI 関連として残る。
    assert filter_ai_related([article], TREND_WORDS) == [article]


def test_ページ送りの判定も全文で行う(since: datetime, until: datetime) -> None:
    """is_wanted に渡すのも切る前の全文。切った文字列を渡すと数え落とす。"""
    seen: list[str] = []
    fetch = RecordingFetch(
        [
            {
                "items": [
                    {
                        "full_name": "someorg/toolkit",
                        "html_url": "https://github.com/someorg/toolkit",
                        "description": LONG_DESC,
                        "stargazers_count": 1000,
                        "created_at": "2026-10-05T00:00:00Z",
                    }
                ]
            }
        ],
        {"items": []},
    )

    def wanted(text: str) -> bool:
        seen.append(text)
        return True

    github_repos.collect(since, fetch, is_wanted=wanted, needed=1, until=until)
    assert seen and "LLM" in seen[0]


# ---------- 検索が時間切れで打ち切られたとき（incomplete_results）----------
#
# GitHub は検索が時間切れになると HTTP 200 のまま incomplete_results: true と
# 途中までの結果（ときには空）を返す。これを「0件」として扱わないようにする。


def test_時間切れで0件なら取得失敗にする(since: datetime, until: datetime) -> None:
    """「期間内に該当なし」と区別できないので、黙って0件にしない（要件5）。"""
    fetch = RecordingFetch([{"total_count": 500, "incomplete_results": True, "items": []}])
    with pytest.raises(github_repos.GitHubIncompleteError):
        github_repos.collect(since, fetch, until=until)


def test_時間切れでも取れた分は返す(since: datetime, until: datetime) -> None:
    """途中までの結果が返っているなら、捨てずに出す（警告はログに出る）。"""
    fetch = RecordingFetch(
        [
            {
                "total_count": 500,
                "incomplete_results": True,
                "items": [
                    {
                        "full_name": "o/n",
                        "html_url": "https://github.com/o/n",
                        "created_at": "2026-10-05T00:00:00Z",
                        "stargazers_count": 7,
                    }
                ],
            }
        ],
        {"items": []},
    )
    articles = github_repos.collect(since, fetch, until=until)
    assert [a.title for a in articles] == ["o/n"]


def test_時間切れならページを進めない(since: datetime, until: datetime) -> None:
    """続きは取れないので、むだなアクセスをしない。"""
    fetch = RecordingFetch(
        [], {"total_count": 500, "incomplete_results": True, "items": _full_page("a")["items"]}
    )
    github_repos.collect(since, fetch, is_wanted=lambda t: False, needed=10, until=until)
    assert len(fetch.calls) == 1


def test_時間切れでなければ例外にしない(since: datetime, until: datetime) -> None:
    fetch = RecordingFetch([{"total_count": 0, "incomplete_results": False, "items": []}])
    assert github_repos.collect(since, fetch, until=until) == []
