from __future__ import annotations

from typing import Any

import requests

from deezync.domain.account import DeezerAccount, DeezerProfile


class DeezerError(RuntimeError):
    """Error returned by the Deezer API."""


class DeezerAuthError(DeezerError):
    """Invalid or expired access token."""


_AUTH_ERROR_TYPES = {"OAuthException"}


class DeezerClient:
    """Read-only access to the Deezer REST API.

    The API reports business errors with an HTTP 200 and an `error` key in the body,
    hence the explicit check after every call.
    """

    BASE_URL = "https://api.deezer.com"
    PAGE_SIZE = 50
    HISTORY_WINDOW = 100

    def __init__(
        self,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout

    def fetch_profile(self, account: DeezerAccount) -> DeezerProfile:
        """Identity behind the token. `/user/me` carries the country too."""
        payload = self._get("/user/me", account.access_token)
        user_id = payload.get("id")
        if user_id is None:
            raise DeezerError("unexpected /user/me response: no `id` field")

        code = str(payload.get("country") or "").strip().upper()
        return DeezerProfile(
            user_id=str(user_id),
            country=code if len(code) == 2 and code.isalpha() else None,
        )

    def fetch_history(
        self, account: DeezerAccount, user_id: str = "me", limit: int = HISTORY_WINDOW
    ) -> list[dict[str, Any]]:
        """Fetch the most recent plays, in pages of 50 (the maximum Deezer allows)."""
        entries: list[dict[str, Any]] = []
        while len(entries) < limit:
            page_size = min(self.PAGE_SIZE, limit - len(entries))
            payload = self._get(
                f"/user/{user_id}/history",
                account.access_token,
                params={"index": len(entries), "limit": page_size},
            )
            page = payload.get("data") or []
            entries.extend(page)
            if len(page) < page_size:
                break
        return entries

    def _get(
        self, path: str, access_token: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        query = {"access_token": access_token, **(params or {})}
        response = self._session.get(f"{self._base_url}{path}", params=query, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()

        error = payload.get("error") if isinstance(payload, dict) else None
        if error:
            self._raise_for_error(path, error)
        return payload

    @staticmethod
    def _raise_for_error(path: str, error: Any) -> None:
        if not isinstance(error, dict):
            raise DeezerError(f"{path}: {error}")

        message = f"{path}: {error.get('type', 'Error')} - {error.get('message', error)}"
        if error.get("type") in _AUTH_ERROR_TYPES or error.get("code") in (200, 300):
            raise DeezerAuthError(f"{message} (invalid or expired token?)")
        raise DeezerError(message)
