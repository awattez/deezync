import pytest

ENVIRONMENT_VARIABLES = (
    "ES_URL",
    "ES_API_KEY",
    "ES_USERNAME",
    "ES_PASSWORD",
    "ES_INDEX",
    "DEEZYNC_USERS_FILE",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """Keep variables loaded by one test from leaking into the next."""
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def gateway_entry():
    """A gateway history entry, already normalised by DeezerGwClient."""
    return {
        "id": 3135556,
        "title": "Harder, Better, Faster, Stronger",
        "duration": 224,
        "timestamp": 1722945600,
        "link": "https://www.deezer.com/track/3135556",
        "isrc": "GBDUW0000059",
        "rank": 814839,
        "gain": -12.4,
        "track_position": 4,
        "disk_number": 1,
        "explicit_lyrics": False,
        "explicit_content_lyrics": 0,
        "explicit_content_cover": 0,
        "contributors": {
            "main_artist": ["Daft Punk"],
            "composer": ["Thomas Bangalter", "Guy-Manuel de Homem-Christo"],
        },
        "md5_image": "2e018122cb56986277102d2041a592c8",
        "artist": {
            "id": 27,
            "name": "Daft Punk",
            "md5_image": "f2bc007e9133c946ac3c3907ddc5d2ea",
        },
        "album": {
            "id": 302127,
            "title": "Discovery",
            "md5_image": "2e018122cb56986277102d2041a592c8",
        },
        "type": "track",
    }


@pytest.fixture
def history_entry():
    return {
        "id": 3135556,
        "readable": True,
        "title": "Harder, Better, Faster, Stronger",
        "title_short": "Harder, Better, Faster, Stronger",
        "title_version": "",
        "link": "https://www.deezer.com/track/3135556",
        "duration": 224,
        "rank": 856555,
        "explicit_lyrics": False,
        "explicit_content_lyrics": 0,
        "explicit_content_cover": 0,
        "preview": "https://cdns-preview-d.dzcdn.net/stream/preview.mp3",
        "md5_image": "2e018122cb56986277102d2041a592c8",
        "timestamp": 1722945600,
        "artist": {
            "id": 27,
            "name": "Daft Punk",
            "link": "https://www.deezer.com/artist/27",
            "type": "artist",
        },
        "album": {
            "id": 302127,
            "title": "Discovery",
            "cover": "https://api.deezer.com/album/302127/image",
            "type": "album",
        },
        "type": "track",
    }
