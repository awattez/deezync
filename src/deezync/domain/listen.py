from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import Any

_DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def _iso(moment: datetime) -> str:
    """Format as strict_date_optional_time, in UTC."""
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _credited_artists(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Every artist billed on the track, the primary one first.

    A list rather than a single name, so co-artists and featurings survive.
    The gateway spells the leading role either `main_artist` or `mainartist`; its
    `artist` role is a different thing -- the individual band members, down to the
    session musicians -- and is deliberately left out. Names are deduplicated
    case-insensitively because a contributor sometimes repeats the main artist in
    another casing.
    """
    contributors = entry.get("contributors") or {}
    candidates = [(entry.get("artist") or {}).get("name")]
    for role in ("main_artist", "mainartist", "featuring"):
        candidates.extend(contributors.get(role) or [])

    credited: list[str] = []
    seen: set[str] = set()
    for name in candidates:
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        credited.append(name)
    return tuple(credited)


@dataclass(frozen=True)
class Listen:
    """A track played by a user at a given moment.

    `duration` is in milliseconds, whereas Deezer counts in seconds; the raw
    value stays untouched in `raw`.
    """

    user: str
    user_id: str
    track_id: str
    played_at: datetime
    title: str | None = None
    artist: tuple[str, ...] = ()
    album: str | None = None
    duration: int | None = None
    explicit: bool | None = None
    url: str | None = None
    country: str | None = None
    display_timezone: tzinfo = UTC
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def listen_id(self) -> str:
        """Deterministic identifier: collecting the same play twice yields the same id."""
        return f"{self.user_id}:{self.track_id}:{int(self.played_at.timestamp())}"

    @classmethod
    def from_history_entry(
        cls,
        entry: Mapping[str, Any],
        *,
        user: str,
        user_id: str,
        country: str | None = None,
        display_timezone: tzinfo = UTC,
    ) -> Listen:
        """Build a listen from one entry of GET /user/{id}/history."""
        track_id = entry.get("id")
        played_at_epoch = entry.get("timestamp")
        if track_id is None or played_at_epoch is None:
            raise ValueError("unusable history entry: missing `id` or `timestamp`")

        album = entry.get("album") or {}
        duration_seconds = entry.get("duration")

        return cls(
            user=user,
            user_id=str(user_id),
            track_id=str(track_id),
            played_at=datetime.fromtimestamp(int(played_at_epoch), tz=UTC),
            title=entry.get("title"),
            artist=_credited_artists(entry),
            album=album.get("title"),
            duration=None if duration_seconds is None else int(duration_seconds) * 1000,
            explicit=entry.get("explicit_lyrics"),
            url=entry.get("link"),
            country=country,
            display_timezone=display_timezone,
            raw=entry,
        )

    def to_document(self) -> dict[str, Any]:
        """The Elasticsearch document for this listen.

        `display_timezone` only affects dayOfWeek / hourOfDay: dates stay in UTC.
        """
        local = self.played_at.astimezone(self.display_timezone)
        played_at = _iso(self.played_at)

        document: dict[str, Any] = {
            "id": self.listen_id,
            "user": self.user,
            "@timestamp": played_at,
            "played_at": played_at,
            "dayOfWeek": _DAY_NAMES[local.weekday()],
            "hourOfDay": local.hour,
            "deezer_metadata": dict(self.raw),
        }

        optional = {
            "title": self.title,
            "artist": list(self.artist) or None,
            "album": self.album,
            "duration": self.duration,
            "explicit": self.explicit,
            "url": self.url,
            "country": self.country,
        }
        document.update({k: v for k, v in optional.items() if v is not None})
        return document
