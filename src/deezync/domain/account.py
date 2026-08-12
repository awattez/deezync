from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, tzinfo


@dataclass(frozen=True)
class DeezerAccount:
    """A Deezer account to synchronise.

    Authenticates either with an OAuth `access_token` (official REST API) or with
    an `arl` session cookie (private web-player API) -- exactly one of the two.
    On a family subscription each profile has its own `arl`.

    `display_timezone` is where this listener is, which is what makes dayOfWeek
    and hourOfDay meaningful. It belongs to the account rather than to the run:
    two profiles living in different countries keep their own local rhythm. It
    defaults to UTC here but `users.toml` demands it, since that is where a human
    can forget it and get plausible, wrong local hours.
    """

    name: str
    access_token: str | None = None
    arl: str | None = None
    display_timezone: tzinfo = UTC

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("an account needs a non-empty `name`")
        if bool(self.access_token) == bool(self.arl):
            raise ValueError(
                f"account {self.name!r}: exactly one of `access_token` or `arl` is required"
            )

    @property
    def auth_method(self) -> str:
        """`"oauth"` or `"arl"`, used to pick the matching Deezer client."""
        return "oauth" if self.access_token else "arl"


@dataclass(frozen=True)
class DeezerProfile:
    """Who the credentials belong to, as resolved when logging in.

    `country` is the subscription market Deezer reports, not a geolocation of the
    plays: it is a property of the account, stable across runs. Reading it from
    the login response that every run makes anyway beats asking for it twice --
    once from Deezer, once from a configuration file that could disagree.
    """

    user_id: str
    country: str | None = None
