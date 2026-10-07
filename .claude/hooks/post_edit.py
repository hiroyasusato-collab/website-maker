"""PostToolUse フック：編集されたファイルに black / ruff を即時適用する。

Claude Code がファイルを Edit / Write するたびに自動実行される（settings.json 参照）。
対象は .py のみ。軽いチェックだけをここで行い、重いチェック（mypy / pytest）は
作業終了時の on_stop.py に任せる（編集のたびに重い処理を回すと作業全体が遅くなるため）。

終了コードの意味（Claude Code のフック仕様）:
  0 = 問題なし
  2 = 問題あり（stderr の内容が Claude にフィードバックされ、自己修正を促す）
"""

import json
import subprocess
import sys

# 入出力の文字コード。Windows の Python は既定で cp932 を使うため、明示しないと
# ruff の UTF-8 出力（日本語コメントを含む違反行など）をデコードできず
# UnicodeDecodeError で落ちる。落ちると下の return 2 に到達せず終了コード 1 で死に、
# 「違反あり」が Claude に伝わらないまま素通りする（CLAUDE.md 文字エンコーディング）。
_ENCODING = "utf-8"


def main() -> int:
    # 違反内容を日本語で stderr に書き出すため、出力側も UTF-8 に固定する。
    sys.stderr.reconfigure(encoding=_ENCODING)  # type: ignore[union-attr]

    # フックは標準入力で JSON を受け取る（どのツールが・どのファイルを操作したか）
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # 入力が読めない場合はブロックしない（フック自体の故障で作業を止めない）

    file_path = payload.get("tool_input", {}).get("file_path", "")

    # Python ファイル以外（.md, .toml 等）はチェック対象外
    if not file_path.endswith(".py"):
        return 0

    # black：整形（-q で出力を抑制。整形は自動適用なので失敗扱いにしない）
    subprocess.run(
        ["black", "-q", file_path], capture_output=True, text=True, encoding=_ENCODING
    )

    # ruff：リント（--fix で自動修正できるものは直す。残った違反は Claude に返す）
    result = subprocess.run(
        ["ruff", "check", "--fix", file_path],
        capture_output=True,
        text=True,
        encoding=_ENCODING,
    )
    if result.returncode != 0:
        # 違反は stdout、ruff 自体の異常（設定不備等）は stderr に出る。
        # 片方だけ拾うと「失敗したのに中身が空」の通知になるため両方を渡す。
        detail = "\n".join(part for part in (result.stdout, result.stderr) if part)
        print(f"ruff 違反が残っています:\n{detail}", file=sys.stderr)
        return 2  # Claude に違反内容をフィードバックして修正させる

    return 0


if __name__ == "__main__":
    sys.exit(main())