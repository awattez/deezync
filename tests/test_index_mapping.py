from deezync.domain.listen import Listen
from deezync.infrastructure.listen_repository import load_index_mapping

DEFINITION = load_index_mapping()
PROPERTIES = DEFINITION["mappings"]["properties"]
METADATA = PROPERTIES["deezer_metadata"]["properties"]


def indexed(mapping):
    return mapping.get("index", True)


def test_documents_only_use_declared_fields(history_entry):
    """`deezer_metadata` is dynamic:false, so drift would silently go unindexed."""
    document = Listen.from_history_entry(history_entry, user="adrien", user_id="2529").to_document()

    assert set(document) <= set(PROPERTIES)
    assert set(document["deezer_metadata"]) <= set(METADATA)


def test_gateway_documents_only_use_declared_fields(gateway_entry):
    document = Listen.from_history_entry(gateway_entry, user="adrien", user_id="2529").to_document()
    metadata = document["deezer_metadata"]

    assert set(metadata) <= set(METADATA)
    assert set(metadata["album"]) <= set(METADATA["album"]["properties"])
    assert set(metadata["artist"]) <= set(METADATA["artist"]["properties"])


def test_the_isrc_stays_queryable():
    """The cross-platform track identifier, and the join key with other catalogues."""
    assert indexed(METADATA["isrc"])


def test_the_index_uses_the_compact_codec():
    assert DEFINITION["settings"]["index"]["codec"] == "best_compression"


def test_the_fields_used_for_analysis_stay_aggregatable():
    for field in ("user", "artist", "album", "title", "dayOfWeek", "hourOfDay", "duration"):
        assert PROPERTIES[field].get("doc_values", True), field
        assert indexed(PROPERTIES[field]), field


def test_stable_catalogue_identifiers_stay_queryable():
    for field in ("id", "rank"):
        assert indexed(METADATA[field]), field
    for entity in ("artist", "album"):
        assert indexed(METADATA[entity]["properties"]["id"]), entity


def test_images_and_previews_are_stored_but_not_indexed():
    noisy = (
        METADATA["preview"],
        METADATA["md5_image"],
        METADATA["link"],
        METADATA["artist"]["properties"]["picture_xl"],
        METADATA["album"]["properties"]["cover_xl"],
        PROPERTIES["url"],
    )
    for mapping in noisy:
        assert not indexed(mapping)
        assert not mapping.get("doc_values", True)


def test_fields_duplicated_at_top_level_are_not_indexed_twice():
    for field in ("title", "duration", "explicit_lyrics", "timestamp"):
        assert not indexed(METADATA[field]), field
    assert not indexed(METADATA["artist"]["properties"]["name"])
    assert not indexed(METADATA["album"]["properties"]["title"])


def test_the_playback_context_fields_remain_declared():
    """Deezer never fills them, but the mapping keeps the slots open."""
    for field in ("ip", "platform", "skipped", "shuffle", "listened_to_ms", "country"):
        assert field in PROPERTIES
