from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import requests

from deezync.domain.account import DeezerAccount, DeezerProfile
from deezync.infrastructure.deezer_client import DeezerAuthError, DeezerError

logger = logging.getLogger(__name__)

GW_URL = "https://www.deezer.com/ajax/gw-light.php"

# The gateway rejects the default python-requests agent. Chrome on Windows is the
# most widespread desktop combination, hence the least identifying one; Chrome
# froze its minor version at 0.0.0, so only the major one ever needs refreshing.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


@dataclass
class _GwSession:
    """One authenticated web-player session: cookies plus the CSRF token."""

    http: requests.Session
    check_form: str
    user_id: str
    country: str | None = None


class DeezerGwClient:
    """History access through the private web-player API (gw-light.php).

    Authenticates with the `arl` session cookie: `deezer.getUserData` yields the
    CSRF token (`checkForm`) and the user id, then `deezer.pageProfile` returns the
    recent plays. That method backs the web history page and, for the same 100
    plays, carries more than `user.getSongsHistory`: ISRC, contributors, track and
    disk numbers, artist artwork. Entries are normalised to the official REST API
    shape so the rest of the pipeline is identical for both auth methods.

    Deezer caps the history at 100 entries server-side; asking for more is ignored.
    """

    HISTORY_WINDOW = 100

    def __init__(
        self,
        gw_url: str = GW_URL,
        timeout: float = 10.0,
        session_factory: Callable[[], requests.Session] = requests.Session,
    ) -> None:
        self._gw_url = gw_url
        self._timeout = timeout
        self._session_factory = session_factory
        self._sessions: dict[str, _GwSession] = {}

    def fetch_profile(self, account: DeezerAccount) -> DeezerProfile:
        session = self._login(account)
        return DeezerProfile(user_id=session.user_id, country=session.country)

    def fetch_history(
        self, account: DeezerAccount, user_id: str = "me", limit: int = HISTORY_WINDOW
    ) -> list[dict[str, Any]]:
        """The most recent plays, newest first, in one gateway call.

        An ARL is bound to a single profile: asking the gateway for a sibling
        profile of the same family answers an empty history rather than an error,
        so the session profile always wins over the requested one.
        """
        session = self._login(account)
        if user_id not in (None, "", "me") and str(user_id) != session.user_id:
            logger.warning(
                "account %s: ignoring user_id %s, this ARL belongs to profile %s",
                account.name,
                user_id,
                session.user_id,
            )
        body = {"user_id": session.user_id, "tab": "history", "nb": limit}
        try:
            results = self._call(session, "deezer.pageProfile", body)
        except DeezerAuthError:
            # The CSRF token expires with the session: re-login once, then retry.
            session = self._login(account, force=True)
            results = self._call(session, "deezer.pageProfile", body)

        entries = ((results.get("TAB") or {}).get("history") or {}).get("data") or []
        return [_normalise(entry) for entry in entries if entry.get("__TYPE__") == "song"]

    def _login(self, account: DeezerAccount, force: bool = False) -> _GwSession:
        """One `deezer.getUserData` call per account and per run (cached)."""
        if not force and account.name in self._sessions:
            return self._sessions[account.name]

        http = self._session_factory()
        http.headers.update({"User-Agent": _USER_AGENT})
        # The arl alone bootstraps the session and pins the active profile: on a
        # family subscription each profile has its own arl (switch profile in the
        # web player, then copy the arl cookie again).
        http.cookies.set("arl", account.arl, domain=".deezer.com")
        http.cookies.set("comeback", "1", domain=".deezer.com")

        payload = self._post(http, "deezer.getUserData", api_token="", body={})
        results = payload.get("results") or {}
        user_id = (results.get("USER") or {}).get("USER_ID")
        check_form = results.get("checkForm")
        if not user_id or str(user_id) == "0" or not check_form:
            raise DeezerAuthError(f"account {account.name!r}: invalid or expired ARL")

        session = _GwSession(
            http=http,
            check_form=str(check_form),
            user_id=str(user_id),
            # The subscription market, corroborated by `license_country`. Not to be
            # confused with SETTING.location, which is a geo-IP guess and goes stale.
            country=_country(results.get("COUNTRY")),
        )
        self._sessions[account.name] = session
        return session

    def _call(self, session: _GwSession, method: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = self._post(session.http, method, api_token=session.check_form, body=body)
        return payload.get("results") or {}

    def _post(
        self,
        http: requests.Session,
        method: str,
        api_token: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        response = http.post(
            self._gw_url,
            params={
                "method": method,
                "input": "3",
                "api_version": "1.0",
                "api_token": api_token,
            },
            json=body,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()

        # The gateway reports errors as {"error": {"CODE": "message"}} with HTTP 200
        # ("error" is an empty list on success).
        error = payload.get("error") if isinstance(payload, dict) else None
        if error:
            message = f"{method}: {error}"
            if "VALID_TOKEN_REQUIRED" in str(error):
                raise DeezerAuthError(message)
            raise DeezerError(message)
        return payload


def _normalise(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Map a gateway `SNG_*` history entry onto the official REST API shape.

    Only the fields declared in the index mapping are kept; everything else the
    gateway carries (media tokens, per-format file sizes, rights...) is dropped.
    `DATE_START` is deliberately ignored: it is a rights start date, not a release
    date, and is often a placeholder.
    """
    track_id = entry.get("SNG_ID")
    explicit = entry.get("EXPLICIT_TRACK_CONTENT") or {}

    normalised: dict[str, Any] = {
        "id": _to_int(track_id),
        "title": entry.get("SNG_TITLE"),
        "title_version": entry.get("VERSION") or None,
        "duration": _to_int(entry.get("DURATION")),
        "timestamp": _to_int(entry.get("TS")),
        "link": f"https://www.deezer.com/track/{track_id}" if track_id else None,
        "isrc": entry.get("ISRC"),
        "rank": _to_int(entry.get("RANK_SNG")),
        "gain": _to_float(entry.get("GAIN")),
        "track_position": _to_int(entry.get("TRACK_NUMBER")),
        "disk_number": _to_int(entry.get("DISK_NUMBER")),
        "explicit_lyrics": str(entry.get("EXPLICIT_LYRICS", "0")) == "1",
        "explicit_content_lyrics": explicit.get("EXPLICIT_LYRICS_STATUS"),
        "explicit_content_cover": explicit.get("EXPLICIT_COVER_STATUS"),
        "contributors": entry.get("SNG_CONTRIBUTORS") or None,
        "md5_image": entry.get("ALB_PICTURE"),
        "artist": _entity(entry, id_key="ART_ID", name_key="ART_NAME", image_key="ART_PICTURE"),
        "album": _entity(entry, id_key="ALB_ID", name_key="ALB_TITLE", image_key="ALB_PICTURE"),
        "type": "track",
    }
    return {key: value for key, value in normalised.items() if value is not None}


def _entity(
    entry: Mapping[str, Any], *, id_key: str, name_key: str, image_key: str
) -> dict[str, Any]:
    """Artist or album sub-document, keyed as in the official API."""
    name_field = "name" if id_key == "ART_ID" else "title"
    fields = {
        "id": _to_int(entry.get(id_key)),
        name_field: entry.get(name_key),
        "md5_image": entry.get(image_key),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _country(value: Any) -> str | None:
    """Keep an ISO 3166-1 alpha-2 code, drop anything else the gateway may answer."""
    code = str(value or "").strip().upper()
    return code if len(code) == 2 and code.isalpha() else None
