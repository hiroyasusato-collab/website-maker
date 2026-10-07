"""設定ファイルの読み込みのテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import ConfigError, load_settings, read_word_list


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

    assert settings.keywords == ["RAG"]
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
    from src.config import KEYWORDS_FILE, TREND_WORDS_FILE

    keywords = read_word_list(KEYWORDS_FILE)
    words = read_word_list(TREND_WORDS_FILE)

    # 要件3.1 のキーワードが入っていること。
    assert "AI駆動開発" in keywords
    assert "RAG" in keywords
    assert "Claude Code" in keywords
    assert "M365" in keywords

    # 設計メモの「必須」の単語が入っていること（これが無いと取りこぼす）。
    for required in ("AI", "LLM", "GPT", "OpenAI", "ChatGPT", "xAI", "Anthropic"):
        assert required in words, f"{required} が ai_trend_words.txt に無い"
