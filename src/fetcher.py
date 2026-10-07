"""ネットからの取得をまとめた場所。

取得元のモジュール（src/sources/*.py）は、ここで定義した JsonFetch / TextFetch を
「外から渡してもらう」形で受け取る。こうしておくと、テストでは偽の取得関数を渡せるので
実際の Web サイトにつながずに動作を確かめられる。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Protocol

import requests

# 相手サイトへの配慮と、こちらの事故防止のための値。
TIMEOUT_SECONDS = 20
MAX_RETRIES = 2
SLEEP_BETWEEN_REQUESTS = 0.5
USER_AGENT = "website-maker/0.1 (personal weekly digest; +https://github.com/)"


class FetchError(Exception):
    """取得に失敗した。やり直しても駄目だったときに投げる。"""


class JsonFetch(Protocol):
    """JSON を取ってくる関数の形。"""

    def __call__(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...


class TextFetch(Protocol):
    """文字列（RSS など）を取ってくる関数の形。"""

    def __call__(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str: ...


class HttpFetcher:
    """実際にネットにつないで取得する。

    ・タイムアウト 20 秒
    ・失敗したら最大2回やり直す（1秒待ち → 2秒待ち）
    ・連続アクセスの間に 0.5 秒の待ちを入れる
    """

    def __init__(
        self,
        *,
        sleep: float = SLEEP_BETWEEN_REQUESTS,
        session: Any | None = None,
    ) -> None:
        # session はテストで差し替えるためだけの引数。本番では渡さない。
        self._session = session if session is not None else requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._sleep = sleep
        self._first_request = True

    def _wait_turn(self) -> None:
        # 1回目は待たない。2回目以降だけ間隔をあける。
        if self._first_request:
            self._first_request = False
            return
        time.sleep(self._sleep)

    def _get(
        self,
        url: str,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
    ) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            self._wait_turn()
            try:
                response = self._session.get(
                    url, params=params, headers=dict(headers or {}), timeout=TIMEOUT_SECONDS
                )
                response.raise_for_status()
                return response
            except Exception as error:  # noqa: BLE001 - 種類を問わずやり直す
                last_error = error
                if attempt < MAX_RETRIES:
                    time.sleep(2**attempt)
        raise FetchError(f"{url} の取得に失敗しました: {last_error}") from last_error

    def json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self._get(url, params, headers)
        try:
            return response.json()
        except ValueError as error:
            raise FetchError(f"{url} の応答が JSON ではありませんでした") from error

    def text(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        return self._get(url, params, headers).text
