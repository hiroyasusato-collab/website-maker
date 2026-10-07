"""X（旧 Twitter）から AI 関連の注目投稿を取る（公式 API v2 / 有料）。

    GET https://api.x.com/2/tweets/search/recent
          ?query=(AI OR LLM OR ...) lang:ja -is:reply -is:retweet
          &sort_order=relevancy
          &max_results=100
          &tweet.fields=created_at,public_metrics,entities,lang

**この取得元だけはお金がかかる（投稿1件の読み取りで 0.005 ドル）。**
そのため、ほかの取得元と違う決まりを3つ入れている。

  1. 既定では止まっている（.env の X_ENABLED=true で初めて動く）
  2. 1回の実行で読む件数に上限がある（.env の X_MAX_POSTS。既定 400件 = 最大 2.00 ドル）
  3. 止まっているときは「接続そのものを行わない」（空の結果を返す）

2026-10-07 に公式ドキュメントで確認したこと:
  ・検索条件（query）の文字数上限は、従量課金などの自前契約では **512文字**
    （Enterprise 契約だと 4096文字。API の仕様上は 4096 まで受け付けるが、
      自前契約で 512 を超えると拒否される）
  ・**sort_order=relevancy を付けるとページ送り用の next_token が返らない**
    → 関連度順では1回の検索で最大100件しか取れない。これが費用の自然な上限にもなる
  ・並び順は recency（新着順）か relevancy（関連度順）の2つだけ。
    「いいね数順」は API では指定できないので、取得後に自分で並べ替える
  ・min_likes: という絞り込みがいったん追加されたが、その後
    search/recent では非推奨になったと公式の変更履歴にあるため使わない
  ・1リクエストで最大100件。アクセス上限は15分あたり450回（今回は2回なので余裕）
  ・投稿の項目は既定では id と text だけ。created_at・public_metrics・entities は
    tweet.fields で明示しないと返ってこない
  ・投稿 ID は非常に大きい数値なので、文字列として扱う（桁が壊れるのを防ぐ）
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from src.fetcher import JsonFetch
from src.models import SITE_X, Article
from src.timeutil import parse_iso
from src.wordmatch import contains_word

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"

# 検索条件の文字数上限（自前契約）。
QUERY_LIMIT = 512

# 投稿1件の読み取り単価（ドル）。画面に出す費用の目安に使う。
COST_PER_POST = 0.005

# 1リクエストで取れる件数の範囲（API の決まり）。
MIN_RESULTS_PER_REQUEST = 10
MAX_RESULTS_PER_REQUEST = 100

# 作る表は「X（日本語）」と「X（英語）」の2つ。
LANGUAGES = ("ja", "en")

# 投稿には記事のようなタイトルが無いので、本文の先頭をタイトル代わりに使う。
TITLE_MAX_CHARS = 120

# 返信とリポストを除く（要件のとおり）。
QUERY_SUFFIX_TEMPLATE = "lang:{lang} -is:reply -is:retweet"

# 投稿ページの住所。ユーザー名が分からなくても開ける形。
POST_URL_TEMPLATE = "https://x.com/i/web/status/{post_id}"

# 外部リンクかどうかの判定で「X 自身へのリンク」とみなすホスト。
# 引用投稿や画像は entities.urls に x.com へのリンクとして入るため、外部リンクに数えない。
_INTERNAL_HOSTS = ("x.com", "twitter.com", "t.co", "pic.twitter.com")


class XConfigError(Exception):
    """X の設定に問題があり、接続する前に止めるべき状態。

    合言葉が無い／合言葉の形がおかしい／検索条件が長すぎる、のいずれか。
    どれも「お金をかけて呼んでも無駄になる」ので、接続せずに止める。
    """


class PostBudget:
    """読んでよい投稿の残り件数。

    **日本語・英語・分割された検索条件のすべてで1つを共有する。**
    言語ごとに別々に数えると、合計が X_MAX_POSTS を超えてしまう。
    """

    def __init__(self, total: int) -> None:
        self.total = max(0, total)
        self.remaining = self.total

    def take(self, wanted: int) -> int:
        """次のリクエストで要求してよい件数を返す。0 なら、もう呼んではいけない。

        要求した件数をそのまま残りから引く（返ってきた件数ではなく）。
        少なめに見積もって使い切らないほうが安全なため。
        """
        allowed = min(max(0, wanted), self.remaining)
        # API は1回10件未満を受け付けないので、10件も残っていなければ打ち切る。
        if allowed < MIN_RESULTS_PER_REQUEST:
            return 0
        self.remaining -= allowed
        return allowed


def _validate_token(token: str | None) -> str:
    """合言葉を確かめる。**値そのものはエラーメッセージに入れない**（ログに漏れるため）。"""
    if not token:
        raise XConfigError(
            "X_ENABLED=true ですが X_BEARER_TOKEN が設定されていません。"
            ".env に合言葉を書くか、X_ENABLED=false にしてください。"
        )
    # 改行や空白が混ざると requests が例外メッセージに値を載せることがある。
    if any(char.isspace() for char in token):
        raise XConfigError(
            "X_BEARER_TOKEN に空白または改行が含まれています。"
            ".env の値を1行で書き直してください。"
        )
    return token


def build_query(words: list[str], lang: str, limit: int = QUERY_LIMIT) -> list[str]:
    """ai_trend_words.txt の単語から検索条件を組み立てる。

    512文字に収まらない場合は複数本に分ける。
    **分けるとリクエスト数＝読む件数＝費用が増える**ので、分けた場合は警告を出す。

    2026-10-07 時点の ai_trend_words.txt（42語）では 473文字で、1本に収まる。
    """
    suffix = QUERY_SUFFIX_TEMPLATE.format(lang=lang)

    def assemble(terms: list[str]) -> str:
        return f"({' OR '.join(terms)}) {suffix}"

    queries: list[str] = []
    current: list[str] = []
    for word in words:
        # 空白を含む単語は引用符で囲む（Hugging Face → "Hugging Face"）
        term = f'"{word}"' if " " in word else word
        if current and len(assemble(current + [term])) > limit:
            queries.append(assemble(current))
            current = [term]
        else:
            current.append(term)
    if current:
        queries.append(assemble(current))

    # 1語だけで上限を超える場合は上の分割では収まらない。
    # お金をかけて呼んでも API に拒否されるだけなので、接続する前に止める。
    longest = max((len(q) for q in queries), default=0)
    if longest > limit:
        raise XConfigError(
            f"X の検索条件が {limit} 文字の上限に収まりません（最長 {longest} 文字）。"
            "ai_trend_words.txt に極端に長い単語が無いか確認してください。"
        )

    if len(queries) > 1:
        logger.warning(
            "X（%s）: 単語が多く検索条件が %d 文字の上限に収まらないため %d 本に分けました。"
            "リクエスト数が増えるため費用も増えます。"
            "ai_trend_words.txt の単語を減らすと1本に収まります。",
            lang,
            limit,
            len(queries),
        )
    return queries


def results_per_request(max_posts: int, query_count: int) -> int:
    """1リクエストで読む件数を、費用の上限から決める。

    max_posts は「日本語＋英語の合計」の上限なので、言語数 × 検索条件の本数で割る。
    API の決まりにより 10〜100 の範囲に収める。
    """
    requests_total = max(1, len(LANGUAGES) * max(1, query_count))
    per_request = max_posts // requests_total
    return max(MIN_RESULTS_PER_REQUEST, min(MAX_RESULTS_PER_REQUEST, per_request))


def has_external_link(raw: dict) -> bool:
    """投稿に外部（X の外）へのリンクが付いているか。

    引用投稿や画像は entities.urls に x.com へのリンクとして入るので、外部に数えない。
    """
    urls = ((raw.get("entities") or {}).get("urls")) or []
    for entry in urls:
        expanded = entry.get("expanded_url") or entry.get("unwound_url") or ""
        if not expanded:
            continue
        try:
            host = (urlsplit(expanded).hostname or "").lower()
        except ValueError:
            continue
        if not host:
            continue
        host = host.removeprefix("www.")
        if not any(
            host == internal or host.endswith(f".{internal}") for internal in _INTERNAL_HOSTS
        ):
            return True
    return False


def make_title(text: str) -> str:
    """投稿の本文をタイトル代わりに整える。

    投稿には記事のようなタイトルが無いため、改行を詰めて先頭を切り出す。
    """
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= TITLE_MAX_CHARS:
        return collapsed
    return collapsed[:TITLE_MAX_CHARS].rstrip() + "…"


def parse_posts(payload: dict, words: list[str], require_link: bool) -> list[Article]:
    """応答から投稿を取り出す。

    検索条件に単語を入れていても関連度順では当たりがゆるくなることがあるため、
    本文に単語が含まれているかをここでも確かめる（はてブ・HN と同じ考え方）。
    """
    posts = (payload or {}).get("data") or []
    articles: list[Article] = []

    for raw in posts:
        # 投稿 ID は桁が大きいので必ず文字列として扱う。
        post_id = str(raw.get("id") or "")
        text = raw.get("text") or ""
        published_at = parse_iso(raw.get("created_at") or "")
        if not post_id or not text or published_at is None:
            continue
        if require_link and not has_external_link(raw):
            continue
        if not any(contains_word(text, word) for word in words):
            continue

        metrics = raw.get("public_metrics") or {}
        articles.append(
            Article(
                title=make_title(text),
                url=POST_URL_TEMPLATE.format(post_id=post_id),
                score=int(metrics.get("like_count") or 0),
                published_at=published_at,
                site=SITE_X,
            )
        )
    return articles


def collect(
    lang: str,
    words: list[str],
    fetch_json: JsonFetch,
    bearer_token: str | None,
    budget: PostBudget,
    require_link: bool = False,
) -> list[Article]:
    """1つの言語について、AI 関連の注目投稿を返す。

    呼び出し側（pipeline）は X_ENABLED が false のときこの関数を呼ばないこと。
    ここに来た時点で「お金をかけてよい」と決まっている前提。

    budget は日本語・英語で**同じものを共有する**。言語ごとに別の上限にすると、
    合計が X_MAX_POSTS を超えてしまう。
    """
    token = _validate_token(bearer_token)
    queries = build_query(words, lang)
    wanted = results_per_request(budget.total, len(queries))
    headers = {"Authorization": f"Bearer {token}"}

    articles: list[Article] = []
    seen_ids: set[str] = set()
    requested_total = 0

    for query in queries:
        allowed = budget.take(wanted)
        if allowed == 0:
            logger.warning(
                "X（%s）: 読み取り件数の上限（%d件）に達したため、ここで打ち切りました。",
                lang,
                budget.total,
            )
            break
        requested_total += allowed

        payload = fetch_json(
            SEARCH_URL,
            params={
                "query": query,
                # 人気の投稿を取りこぼしにくくするため関連度順にする（要件のとおり）。
                # なお関連度順では next_token が返らないので、ページ送りはしない。
                "sort_order": "relevancy",
                "max_results": allowed,
                "tweet.fields": "created_at,public_metrics,entities,lang",
            },
            headers=headers,
            # **やり直しをしない。** 通信がやり直されると、サーバー側では読み取りが
            # 済んでいて課金されるのに、こちらは件数を数えられず上限を超えてしまう。
            retries=0,
        )
        for article in parse_posts(payload, words, require_link):
            if article.url in seen_ids:
                continue
            seen_ids.add(article.url)
            articles.append(article)

    logger.info(
        "X（%s）: 最大 %d 件を読み取り（最大 $%.2f）→ %d 件採用。残りの読み取り枠 %d 件",
        lang,
        requested_total,
        requested_total * COST_PER_POST,
        len(articles),
        budget.remaining,
    )
    return articles
