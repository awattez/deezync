from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from deezync.domain.listen import Listen


def build(entry, **kwargs):
    return Listen.from_history_entry(entry, user="adrien", user_id="2529", **kwargs)


def test_listen_id_is_deterministic(history_entry):
    assert build(history_entry).listen_id == build(history_entry).listen_id


def test_listen_id_combines_user_track_and_moment(history_entry):
    assert build(history_entry).listen_id == "2529:3135556:1722945600"


def test_two_plays_of_the_same_track_get_distinct_ids(history_entry):
    later = {**history_entry, "timestamp": history_entry["timestamp"] + 300}
    assert build(history_entry).listen_id != build(later).listen_id


def test_two_users_playing_the_same_track_get_distinct_ids(history_entry):
    other = Listen.from_history_entry(history_entry, user="alice", user_id="3040")
    assert build(history_entry).listen_id != other.listen_id


def test_entry_without_timestamp_is_rejected(history_entry):
    with pytest.raises(ValueError):
        build({k: v for k, v in history_entry.items() if k != "timestamp"})


def test_document_maps_deezer_fields_to_the_index_schema(history_entry):
    document = build(history_entry).to_document()

    assert document["id"] == "2529:3135556:1722945600"
    assert document["user"] == "adrien"
    assert document["title"] == "Harder, Better, Faster, Stronger"
    assert document["artist"] == ["Daft Punk"]
    assert document["album"] == "Discovery"
    assert document["duration"] == 224_000
    assert document["explicit"] is False
    assert document["url"] == "https://www.deezer.com/track/3135556"


def test_duration_is_converted_to_milliseconds(history_entry):
    """The index stores milliseconds; Deezer answers in seconds."""
    document = build(history_entry).to_document()

    assert history_entry["duration"] == 224
    assert document["duration"] == 224_000
    assert document["deezer_metadata"]["duration"] == 224


def test_document_dates_are_utc_iso8601(history_entry):
    document = build(history_entry).to_document()

    assert document["@timestamp"] == "2024-08-06T12:00:00Z"
    assert document["played_at"] == document["@timestamp"]


def test_document_keeps_the_raw_payload(history_entry):
    assert build(history_entry).to_document()["deezer_metadata"] == history_entry


def at_2330_utc(**overrides):
    return Listen(
        user="adrien",
        user_id="2529",
        track_id="1",
        played_at=datetime(2024, 8, 5, 23, 30, tzinfo=UTC),
        **overrides,
    )


def test_derived_fields_follow_the_display_timezone():
    utc = at_2330_utc().to_document()
    paris = at_2330_utc(display_timezone=ZoneInfo("Europe/Paris")).to_document()

    assert (utc["dayOfWeek"], utc["hourOfDay"]) == ("Monday", 23)
    assert (paris["dayOfWeek"], paris["hourOfDay"]) == ("Tuesday", 1)
    assert paris["played_at"] == utc["played_at"]


def test_each_listen_carries_its_own_timezone():
    """Two profiles in different countries keep their own local rhythm."""
    paris = at_2330_utc(display_timezone=ZoneInfo("Europe/Paris")).to_document()
    montreal = at_2330_utc(display_timezone=ZoneInfo("America/Montreal")).to_document()

    assert (paris["dayOfWeek"], paris["hourOfDay"]) == ("Tuesday", 1)
    assert (montreal["dayOfWeek"], montreal["hourOfDay"]) == ("Monday", 19)


GW_NORMALISED_ENTRY = {
    "id": 3135556,
    "title": "Harder, Better, Faster, Stronger",
    "duration": 224,
    "timestamp": 1722945600,
    "link": "https://www.deezer.com/track/3135556",
    "explicit_lyrics": False,
    "artist": {"id": 27, "name": "Daft Punk"},
    "album": {"id": 302127, "title": "Discovery"},
    "type": "track",
}


def test_a_normalised_gateway_entry_yields_the_same_id_as_the_official_api(history_entry):
    """A listen must not be duplicated when an account switches auth method."""
    assert build(GW_NORMALISED_ENTRY).listen_id == build(history_entry).listen_id


def test_a_normalised_gateway_entry_fills_the_same_top_level_fields(history_entry):
    gateway = build(GW_NORMALISED_ENTRY).to_document()
    official = build(history_entry).to_document()

    for field in ("title", "artist", "album", "duration", "explicit", "url"):
        assert gateway[field] == official[field], field


def test_the_history_entry_is_kept_verbatim_as_metadata(gateway_entry):
    """No enrichment step: whatever the client returns is what gets indexed."""
    document = build(gateway_entry).to_document()

    assert document["deezer_metadata"] == gateway_entry


def with_contributors(history_entry, artist_name, contributors):
    return build({**history_entry, "artist": {"name": artist_name}, "contributors": contributors})


def test_artist_is_a_list_even_for_a_single_name(history_entry):
    assert build(history_entry).to_document()["artist"] == ["Daft Punk"]


def test_co_artists_and_featurings_join_the_artist_list(history_entry):
    listen = with_contributors(
        history_entry,
        "Danger Mouse",
        {"main_artist": ["Danger Mouse", "Daniele Luppi"], "featuring": ["Jack White"]},
    )

    assert listen.to_document()["artist"] == ["Danger Mouse", "Daniele Luppi", "Jack White"]


def test_the_primary_artist_stays_first(history_entry):
    """The billed artist comes first, whatever order the credits come in."""
    listen = with_contributors(
        history_entry, "Mary J. Blige", {"featuring": ["Diddy"], "main_artist": ["Mary J. Blige"]}
    )

    assert listen.to_document()["artist"][0] == "Mary J. Blige"


def test_the_band_members_role_is_left_out(history_entry):
    """The gateway `artist` role lists members and session players, not billing."""
    listen = with_contributors(
        history_entry,
        "SBTRKT",
        {"main_artist": ["SBTRKT", "Little Dragon"], "artist": ["Aaron Jerome Foulds"]},
    )

    assert listen.to_document()["artist"] == ["SBTRKT", "Little Dragon"]


def test_the_alternate_spelling_of_the_main_role_is_understood(history_entry):
    listen = with_contributors(history_entry, "Applause", {"mainartist": ["Applause", "Bo"]})

    assert listen.to_document()["artist"] == ["Applause", "Bo"]


def test_a_contributor_repeating_the_artist_in_another_casing_is_not_duplicated(history_entry):
    listen = with_contributors(
        history_entry, "CONCRETE KNIVES", {"main_artist": ["Concrete Knives"]}
    )

    assert listen.to_document()["artist"] == ["CONCRETE KNIVES"]


def test_a_track_without_contributors_falls_back_on_the_single_artist(history_entry):
    listen = build({k: v for k, v in history_entry.items() if k != "contributors"})

    assert listen.to_document()["artist"] == ["Daft Punk"]


def test_the_country_comes_from_the_account(history_entry):
    """Deezer cannot tell where a play happened, so it is declared per account."""
    assert build(history_entry, country="FR").to_document()["country"] == "FR"


def test_an_account_without_a_country_leaves_the_field_out(history_entry):
    assert "country" not in build(history_entry).to_document()


def test_missing_optional_fields_are_omitted():
    document = Listen(
        user="adrien",
        user_id="2529",
        track_id="1",
        played_at=datetime(2024, 8, 5, 23, 30, tzinfo=UTC),
    ).to_document()

    assert "title" not in document
    assert "explicit" not in document
    assert "artist" not in document
