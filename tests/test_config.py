"""設定ファイルの読み込みのテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import (
    ConfigError,
    load_settings,
    parse_keyword_line,
    read_display_order,
    read_keywords,
    read_word_list,
)


def _write(tmp_path: Path, name: str, text: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


def test_1行1項目で読む(tmp_path: Path) -> None:
    path = _write(tmp_path, "keywords.txt", "AI駆動開発\nRAG\nClaude Code\n")
    assert read_word_list(path) == ["AI駆動開発", "RAG", "Claude Code"]


def test_空行とコメント行を無視する(tmp_path: Path) -> None:
    text = "# これはコメント\n\nAI駆動開発\n\n# RAG を一時的に外す\n#RAG\nClaude Code\n"
    path = _write(tmp_path, "keywords.txt", text)
    assert read_word_list(path) == ["AI駆動開発", "Claude Code"]


def test_前後の空白を取り除く(tmp_path: Path) -> None:
    path = _write(tmp_path, "keywords.txt", "  AI駆動開発  \n\tRAG\t\n")
    assert read_word_list(path) == ["AI駆動開発", "RAG"]


def test_メモ帳のBOMを取り除く(tmp_path: Path) -> None:
    """Windows のメモ帳で保存すると先頭に BOM が付くことがある。"""
    path = _write(tmp_path, "keywords.txt", "AI駆動開発\nRAG\n", encoding="utf-8-sig")
    assert read_word_list(path) == ["AI駆動開発", "RAG"]


def test_重複は最初の1つだけ残し順番を保つ(tmp_path: Path) -> None:
    path = _write(tmp_path, "keywords.txt", "RAG\nAI\nRAG\nClaude\nAI\n")
    assert read_word_list(path) == ["RAG", "AI", "Claude"]


def test_改行コードがCRLFでも読める(tmp_path: Path) -> None:
    path = tmp_path / "keywords.txt"
    path.write_bytes("AI駆動開発\r\nRAG\r\n".encode())
    assert read_word_list(path) == ["AI駆動開発", "RAG"]


def test_ファイルが無ければ分かるエラーにする(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="見つかりません"):
        read_word_list(tmp_path / "ない.txt")


def test_中身が空なら分かるエラーにする(tmp_path: Path) -> None:
    path = _write(tmp_path, "keywords.txt", "# コメントだけ\n\n")
    with pytest.raises(ConfigError, match="項目が1つもありません"):
        read_word_list(path)


def test_設定をまとめて読む(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\nLLM\n")
    monkeypatch.delenv("QIITA_TOKEN", raising=False)
    monkeypatch.delenv("HATENA_MIN_USERS", raising=False)
    monkeypatch.delenv("MAX_PER_SITE", raising=False)

    settings = load_settings(keywords, words, tmp_path / "docs")

    assert [group.name for group in settings.keywords] == ["RAG"]
    assert settings.trend_words == ["AI", "LLM"]
    assert settings.qiita_token is None
    assert settings.hatena_min_users == 10
    assert settings.max_per_site == 4


def test_環境変数を読む(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    monkeypatch.setenv("QIITA_TOKEN", "  abc123  ")
    monkeypatch.setenv("HATENA_MIN_USERS", "30")
    monkeypatch.setenv("MAX_PER_SITE", "2")

    settings = load_settings(keywords, words, tmp_path / "docs")

    assert settings.qiita_token == "abc123"
    assert settings.hatena_min_users == 30
    assert settings.max_per_site == 2


@pytest.mark.parametrize("raw", ["", "   ", "よっつ", "4.5"])
def test_1サイトの上限が数字でなければ既定値を使う(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    monkeypatch.setenv("MAX_PER_SITE", raw)

    settings = load_settings(keywords, words, tmp_path / "docs")
    assert settings.max_per_site == 4


def test_1サイトの上限に0を指定できる(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """0 は「上限なし」の意味。既定値に戻してはいけない。"""
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    monkeypatch.setenv("MAX_PER_SITE", "0")

    settings = load_settings(keywords, words, tmp_path / "docs")
    assert settings.max_per_site == 0


# ---------- X（旧 Twitter）の設定 ----------
#
# X は従量課金なので、設定の読み間違いがそのまま料金につながる。


def _x_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("X_ENABLED", "X_BEARER_TOKEN", "X_MAX_POSTS", "X_REQUIRE_LINK"):
        monkeypatch.delenv(name, raising=False)


def test_Xは既定で止まっている(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """うっかり料金が発生しないよう、何も書かなければ止まっていること。"""
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)

    settings = load_settings(keywords, words, tmp_path / "docs")

    assert settings.x_enabled is False
    assert settings.x_bearer_token is None
    assert settings.x_max_posts == 400
    assert settings.x_require_link is False


@pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "on"])
def test_Xを有効にする書き方(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_ENABLED", raw)

    assert load_settings(keywords, words, tmp_path / "docs").x_enabled is True


@pytest.mark.parametrize("raw", ["false", "False", "0", "no", "off"])
def test_Xを止める書き方(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_ENABLED", raw)

    assert load_settings(keywords, words, tmp_path / "docs").x_enabled is False


@pytest.mark.parametrize("raw", ["", "   ", "はい", "ture", "maybe"])
def test_読めない書き方なら止まったままにする(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """お金がかかる機能なので、書き間違いのときは動かさない側に倒す。"""
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_ENABLED", raw)

    assert load_settings(keywords, words, tmp_path / "docs").x_enabled is False


def test_Xの合言葉と上限を読む(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_BEARER_TOKEN", "  secret-token  ")
    monkeypatch.setenv("X_MAX_POSTS", "200")
    monkeypatch.setenv("X_REQUIRE_LINK", "true")

    settings = load_settings(keywords, words, tmp_path / "docs")

    assert settings.x_bearer_token == "secret-token"
    assert settings.x_max_posts == 200
    assert settings.x_require_link is True


@pytest.mark.parametrize("raw", ["", "   "])
def test_Xの件数上限が空なら既定値を使う(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_MAX_POSTS", raw)

    assert load_settings(keywords, words, tmp_path / "docs").x_max_posts == 400


def test_Xの件数上限は全角数字でも読める(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """全角で書いても意図どおりの数になる（エラーにしない）。"""
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_MAX_POSTS", "１００")

    assert load_settings(keywords, words, tmp_path / "docs").x_max_posts == 100


@pytest.mark.parametrize("raw", ["よんひゃく", "400.5", "0.0", "1e3", "400件"])
def test_Xの件数上限が読めなければエラーにする(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """お金に関わる設定なので、黙って既定値（400件）に戻してはいけない。

    「0 のつもりで 0.0 と書いた」場合に 400件読んでしまうと、意図しない料金になる。
    """
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_MAX_POSTS", raw)

    with pytest.raises(ConfigError, match="X_MAX_POSTS"):
        load_settings(keywords, words, tmp_path / "docs")


def test_Xの件数上限に0を指定できる(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """0 は「1件も読まない」の意味。既定値に戻してはいけない。"""
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_MAX_POSTS", "0")

    assert load_settings(keywords, words, tmp_path / "docs").x_max_posts == 0


def test_Xの合言葉が空なら無しとして扱う(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    _x_env(monkeypatch)
    monkeypatch.setenv("X_BEARER_TOKEN", "   ")

    assert load_settings(keywords, words, tmp_path / "docs").x_bearer_token is None


@pytest.mark.parametrize("raw", ["", "   ", "たくさん", "10.5"])
def test_しきい値が数字でなければ既定値を使う(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    monkeypatch.setenv("HATENA_MIN_USERS", raw)

    settings = load_settings(keywords, words, tmp_path / "docs")
    assert settings.hatena_min_users == 10


def test_空のトークンは無しとして扱う(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keywords = _write(tmp_path, "keywords.txt", "RAG\n")
    words = _write(tmp_path, "ai_trend_words.txt", "AI\n")
    monkeypatch.setenv("QIITA_TOKEN", "   ")

    settings = load_settings(keywords, words, tmp_path / "docs")
    assert settings.qiita_token is None


def test_実際の設定ファイルが読める() -> None:
    """同梱の keywords.txt / ai_trend_words.txt が壊れていないことを確かめる。"""
    from src.config import KEYWORDS_FILE, TREND_WORDS_FILE, read_keywords

    groups = read_keywords(KEYWORDS_FILE)
    names = [group.name for group in groups]
    # 検索に使う単語（まとまりを展開したもの）。
    search_words = [word for group in groups for word in group.words]
    words = read_word_list(TREND_WORDS_FILE)

    # 要件3.1 のキーワードが入っていること。
    for required in ("AI駆動開発", "Claude Code", "Codex", "M365", "AIエージェント"):
        assert required in names, f"{required} が keywords.txt に無い"
    # RAG とナレッジグラフは1つの表にまとまっている。
    assert "RAG・ナレッジグラフ" in names
    assert "RAG" in search_words
    assert "ナレッジグラフ" in search_words

    # 設計メモの「必須」の単語が入っていること（これが無いと取りこぼす）。
    for required in ("AI", "LLM", "GPT", "OpenAI", "ChatGPT", "xAI", "Anthropic"):
        assert required in words, f"{required} が ai_trend_words.txt に無い"


# ---------- キーワードのまとまり（1行に複数の単語）----------


def test_1行1キーワードならそのまま1つの表になる(tmp_path: Path) -> None:
    path = _write(tmp_path, "keywords.txt", "AI駆動開発\nM365\n")
    groups = read_keywords(path)

    assert [g.name for g in groups] == ["AI駆動開発", "M365"]
    assert groups[0].words == ("AI駆動開発",)


def test_カンマで区切ると1つの表にまとまる(tmp_path: Path) -> None:
    """表の名前は単語を「・」でつないだものになる。"""
    path = _write(tmp_path, "keywords.txt", "RAG, ナレッジグラフ\n")
    group = read_keywords(path)[0]

    assert group.name == "RAG・ナレッジグラフ"
    assert group.words == ("RAG", "ナレッジグラフ")


@pytest.mark.parametrize(
    "line", ["RAG,ナレッジグラフ", "RAG，ナレッジグラフ", "RAG、ナレッジグラフ"]
)
def test_全角のカンマや読点でも区切れる(line: str) -> None:
    """日本語入力のまま打っても通じるようにする。"""
    group = parse_keyword_line(line)
    assert group is not None
    assert group.words == ("RAG", "ナレッジグラフ")


def test_区切りの前後の空白は取り除く() -> None:
    group = parse_keyword_line("  RAG ,   ナレッジグラフ  ")
    assert group is not None
    assert group.words == ("RAG", "ナレッジグラフ")


def test_単語が無い行は読み飛ばす(tmp_path: Path) -> None:
    path = _write(tmp_path, "keywords.txt", ",,\nRAG\n")
    assert [g.name for g in read_keywords(path)] == ["RAG"]
    assert parse_keyword_line(" , , ") is None


def test_同じ名前の行は1つだけ残す(tmp_path: Path) -> None:
    path = _write(tmp_path, "keywords.txt", "RAG\nM365\nRAG\n")
    assert [g.name for g in read_keywords(path)] == ["RAG", "M365"]


def test_keywordsが空ならエラーにする(tmp_path: Path) -> None:
    path = _write(tmp_path, "keywords.txt", "# コメントだけ\n\n")
    with pytest.raises(ConfigError, match="項目が1つもありません"):
        read_keywords(path)


def test_keywordsもBOM付きで読める(tmp_path: Path) -> None:
    """Windows のメモ帳で保存すると先頭に BOM が付く。"""
    path = _write(tmp_path, "keywords.txt", "RAG\n", encoding="utf-8-sig")
    assert [g.name for g in read_keywords(path)] == ["RAG"]


# ---------- 表を置かない位置（display_order.txt の「（空き）」）----------


def test_空きの行はNoneになる(tmp_path: Path) -> None:
    path = _write(tmp_path, "display_order.txt", "M365\n（空き）\nRAG\n")
    assert read_display_order(path) == ["M365", None, "RAG"]


@pytest.mark.parametrize("marker", ["（空き）", "(空き)", "空き", "-"])
def test_空きの書き方はいくつか許す(tmp_path: Path, marker: str) -> None:
    path = _write(tmp_path, "display_order.txt", f"M365\n{marker}\n")
    assert read_display_order(path) == ["M365", None]


def test_空きは何度書いても残る(tmp_path: Path) -> None:
    """表の名前は重複を省くが、空きは位置を決めるものなので省かない。"""
    path = _write(tmp_path, "display_order.txt", "M365\n（空き）\nRAG\n（空き）\n")
    assert read_display_order(path) == ["M365", None, "RAG", None]


def test_同じ表の名前を2回書いても1回だけ出る(tmp_path: Path) -> None:
    path = _write(tmp_path, "display_order.txt", "M365\nM365\nRAG\n")
    assert read_display_order(path) == ["M365", "RAG"]


def test_カンマ区切りで書いても表の名前として読める(tmp_path: Path) -> None:
    """keywords.txt と同じ書き方をしても通じるようにする。"""
    path = _write(tmp_path, "display_order.txt", "RAG, ナレッジグラフ\n")
    assert read_display_order(path) == ["RAG・ナレッジグラフ"]


def test_display_orderは無くても空で返る(tmp_path: Path) -> None:
    assert read_display_order(tmp_path / "ない.txt") == []


def test_keywordsのファイルが無ければ分かるエラーにする(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="見つかりません"):
        read_keywords(tmp_path / "ない.txt")
