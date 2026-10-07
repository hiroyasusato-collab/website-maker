"""Stop フック：Claude Code の作業終了時に mypy / pytest を全体に実行する。

Claude Code が「完了」しようとした瞬間に自動実行される（settings.json 参照）。
失敗があれば終了コード 2 で Claude を作業に引き戻し、自己修正させる。
全チェックが通って初めて作業を終えられる ＝ 品質チェックの機械的強制。

無限ループ防止:
  フックが Claude を引き戻した後の再終了時は、入力 JSON の stop_hook_active が
  True になる。その場合に再びブロックし続けると修正不能な問題で永久ループするため、
  2回目は警告だけ出して通す（最終判断は人間の検収に委ねる）。
"""

import json
import os
import subprocess
import sys

# pytest の終了コードのうち「失敗ではない」もの（許容する値）。
#   0 = 全テスト通過
#   5 = テストが1件も収集されなかった（新規プロジェクトはテストが空なので正常）
# これ以外（1=テスト失敗, 2=中断, 3=内部エラー, 4=誤用）を失敗として扱う。
_PYTEST_OK_CODES = (0, 5)

# mypy が「型チェックする対象が1つも無い」ときに出す文言（新規プロジェクトは src/ が
# 空なので必ずこれで落ちる）。pytest の終了コード5 と同じく、道具が対象を見つけられない
# ことはコードの問題ではないため通す。
# 終了コードでは判定できない：mypy は使い方の誤り全般に 2 を返すため、対象が無いことを
# 一意に示すのは、この文言だけである。
_MYPY_NO_SOURCES = "There are no .py[i] files in directory"

# 入出力の文字コード。Windows の Python は既定で cp932 を使うため、明示しないと
# pytest が失敗時に出力する日本語（assert したソース行・メッセージ）をデコードできず
# UnicodeDecodeError で落ちる。落ちると下の return 2 に到達せず終了コード 1 で死に、
# 品質チェックが失敗しているのに Claude がそのまま完了してしまう（CLAUDE.md）。
_ENCODING = "utf-8"


def main() -> int:
    # 失敗内容を日本語で stderr に書き出すため、出力側も UTF-8 に固定する。
    sys.stderr.reconfigure(encoding=_ENCODING)  # type: ignore[union-attr]

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}

    # ループ防止：一度引き戻した後の終了はブロックしない
    already_blocked_once = payload.get("stop_hook_active", False)

    failures: list[str] = []

    # チェック対象のフォルダは、プロジェクトの直下を起点に組み立てる。
    # フックは「いまいるフォルダ」を起点に相対パスを解決するため、素の "src/" と書くと
    # サブフォルダ（例：01_docs\02_仕様書）で作業しているときに対象が見つからず失敗する。
    # Claude Code は CLAUDE_PROJECT_DIR にプロジェクトの直下を入れて渡す。
    # 既定値を "." にしてあるのは、人が手で実行するときも動くようにするため。
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    src_dir = os.path.join(project_dir, "src")
    tests_dir = os.path.join(project_dir, "tests")

    # mypy：型チェック（対象は src/。コードは src/ 配下に置く前提のため src/ のみを渡す。
    # src/ の外にコード（例：直下の app.py）を置くプロジェクトでは、ここに対象を追加する）
    mypy = subprocess.run(["mypy", src_dir], capture_output=True, text=True, encoding=_ENCODING)
    if mypy.returncode != 0 and _MYPY_NO_SOURCES not in _output_of(mypy):
        failures.append(f"--- mypy 失敗 ---\n{_output_of(mypy)}")

    # pytest：全テスト実行（-q で簡潔表示）
    # 終了コードが許容値（0=全通過 / 5=テスト0件）以外のときだけ失敗として扱う。
    pytest = subprocess.run(
        ["pytest", tests_dir, "-q"], capture_output=True, text=True, encoding=_ENCODING
    )
    if pytest.returncode not in _PYTEST_OK_CODES:
        failures.append(f"--- pytest 失敗 ---\n{_output_of(pytest)}")

    if not failures:
        return 0

    message = "\n".join(failures)

    if already_blocked_once:
        # 2回目：永久ループを避けるため通すが、未解決である事実を明示する
        print(
            "警告: 品質チェックが未解決のまま作業を終了します。"
            "完了報告に失敗内容を必ず記載してください。\n" + message,
            file=sys.stderr,
        )
        return 0

    # 1回目：Claude を引き戻して自己修正させる
    print(
        "品質チェックが失敗しています。修正してから完了してください。\n"
        "注意: テスト側を弱める変更（assert の緩和・skip 化・削除）は禁止。\n"
        "テストが誤りと判断した場合は変更せず、理由を報告して確認を求めること。\n" + message,
        file=sys.stderr,
    )
    return 2


def _output_of(result: "subprocess.CompletedProcess[str]") -> str:
    """失敗内容として Claude に渡す本文を組み立てる。

    通常の検査結果は stdout に、ツール自体の異常（設定不備・内部エラー）は stderr に出る。
    stdout だけを見ると「失敗したのに中身が空」の通知になり、Claude が何を直せばよいか
    分からなくなるため、存在するほうを両方つなげて返す。
    """
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


if __name__ == "__main__":
    sys.exit(main())
