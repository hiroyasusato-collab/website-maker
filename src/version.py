"""このプログラムのバージョン番号。

番号は pyproject.toml の [project] version の1か所にだけ書く。番号を上げるときは
そこだけを直せばよい（ここや他のファイルに番号を書き写さない）。
版ごとの変更点は CHANGELOG.md に書く。

番号は「左.真ん中.右」の3つの数（例：1.1.0）。
    機能を足した          → 真ん中を上げる（1.1.0 → 1.2.0）
    不具合を直しただけ    → 右を上げる    （1.1.0 → 1.1.1）
    作りが大きく変わった  → 左を上げる    （1.1.0 → 2.0.0）
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def read_version(path: Path = PYPROJECT) -> str:
    """pyproject.toml から番号を読む。3つの数の形でなければ止める。

    書き間違いのままページに出さないよう、黙って別の値にはしない。
    """
    with path.open("rb") as file:
        version = tomllib.load(file).get("project", {}).get("version")
    if not isinstance(version, str) or not VERSION_PATTERN.match(version):
        raise ValueError(
            f"{path.name} の version は「1.1.0」のような3つの数で書いてください: {version!r}"
        )
    return version


VERSION = read_version()
