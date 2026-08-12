import pytest

from deezync.domain.account import DeezerAccount
from deezync.infrastructure.deezer_client import DeezerAuthError, DeezerError
from deezync.infrastructure.deezer_gw_client import DeezerGwClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeCookies:
    def __init__(self):
        self.values = {}

    def set(self, name, value, domain=None):
        self.values[name] = value


class FakeGwSession:
    """Gateway session returning canned responses and recording the calls."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.headers = {}
        self.cookies = FakeCookies()
        self.calls = []

    def post(self, url, params=None, json=None, timeout=None):
        self.calls.append((params, json))
        return FakeResponse(self._payloads.pop(0))


def login_payload(user_id=2529, check_form="csrf-token", country="FR"):
    results = {"USER": {"USER_ID": user_id}}
    if check_form is not None:
        results["checkForm"] = check_form
    if country is not None:
        results["COUNTRY"] = country
    return {"error": [], "results": results}


def history_payload(entries):
    return {"error": [], "results": {"TAB": {"history": {"data": entries}}}}


def gw_entry(**overrides):
    entry = {
        "SNG_ID": "3135556",
        "SNG_TITLE": "Harder, Better, Faster, Stronger",
        "VERSION": "",
        "ART_ID": "27",
        "ART_NAME": "Daft Punk",
        "ART_PICTURE": "f2bc007e9133c946ac3c3907ddc5d2ea",
        "ALB_ID": "302127",
        "ALB_TITLE": "Discovery",
        "ALB_PICTURE": "2e018122cb56986277102d2041a592c8",
        "DURATION": "224",
        "TS": 1722945600,
        "ISRC": "GBDUW0000059",
        "RANK_SNG": "814839",
        "GAIN": "-12.4",
        "TRACK_NUMBER": "4",
        "DISK_NUMBER": "1",
        "EXPLICIT_LYRICS": "0",
        "EXPLICIT_TRACK_CONTENT": {
            "EXPLICIT_LYRICS_STATUS": 0,
            "EXPLICIT_COVER_STATUS": 0,
        },
        "SNG_CONTRIBUTORS": {"main_artist": ["Daft Punk"]},
        "DATE_START": "2000-01-01",
        "TRACK_TOKEN": "ephemeral",
        "FILESIZE_MP3_320": "9061272",
        "__TYPE__": "song",
    }
    entry.update(overrides)
    return entry


def make_client(*payload_batches):
    """One fake session per batch: a re-login consumes the next batch."""
    sessions = [FakeGwSession(batch) for batch in payload_batches]
    iterator = iter(sessions)
    return DeezerGwClient(session_factory=lambda: next(iterator)), sessions


def arl_account(name="adrien", arl="arl-cookie"):
    return DeezerAccount(name=name, arl=arl)


def test_entries_are_normalised_to_the_official_api_shape():
    client, _ = make_client([login_payload(), history_payload([gw_entry()])])

    (entry,) = client.fetch_history(arl_account())

    assert entry == {
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
        "contributors": {"main_artist": ["Daft Punk"]},
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


def test_media_tokens_and_file_sizes_are_dropped():
    """The gateway ships playback plumbing that has no place in the index."""
    client, _ = make_client([login_payload(), history_payload([gw_entry()])])

    (entry,) = client.fetch_history(arl_account())

    for noise in ("TRACK_TOKEN", "FILESIZE_MP3_320", "track_token", "filesize"):
        assert noise not in entry


def test_the_rights_start_date_is_not_mistaken_for_a_release_date():
    """DATE_START is a rights date, often a placeholder like 2000-01-01."""
    client, _ = make_client([login_payload(), history_payload([gw_entry()])])

    (entry,) = client.fetch_history(arl_account())

    assert "release_date" not in entry
    assert "2000-01-01" not in entry.values()


def test_an_empty_title_version_is_omitted():
    client, _ = make_client([login_payload(), history_payload([gw_entry()])])

    (entry,) = client.fetch_history(arl_account())

    assert "title_version" not in entry


def test_non_song_entries_are_filtered_out():
    entries = [gw_entry(), gw_entry(__TYPE__="episode", SNG_ID="42")]
    client, _ = make_client([login_payload(), history_payload(entries)])

    assert len(client.fetch_history(arl_account())) == 1


def test_the_session_carries_the_arl_cookie_and_a_browser_user_agent():
    client, (session,) = make_client([login_payload(), history_payload([])])

    client.fetch_history(arl_account())

    assert session.cookies.values["arl"] == "arl-cookie"
    assert session.cookies.values["comeback"] == "1"
    assert "Mozilla" in session.headers["User-Agent"]


def test_login_sends_an_empty_api_token_and_history_the_csrf_token():
    client, (session,) = make_client([login_payload(), history_payload([])])

    client.fetch_history(arl_account())

    login_params, history_params = (params for params, _ in session.calls)
    assert login_params["method"] == "deezer.getUserData"
    assert login_params["api_token"] == ""
    assert history_params["method"] == "deezer.pageProfile"
    assert history_params["api_token"] == "csrf-token"


def test_history_targets_the_history_tab_of_the_logged_in_profile():
    client, (session,) = make_client([login_payload(), history_payload([])])

    client.fetch_history(arl_account())

    _, body = session.calls[-1]
    assert body == {"user_id": "2529", "tab": "history", "nb": 100}


def test_a_foreign_profile_id_is_ignored_in_favour_of_the_session(caplog):
    """A sibling family profile answers an empty history, never an error:
    honouring the requested id would silently sync nothing."""
    client, (session,) = make_client([login_payload(), history_payload([])])

    client.fetch_history(arl_account(), user_id="925815041")

    _, body = session.calls[-1]
    assert body["user_id"] == "2529"
    assert "925815041" in caplog.text


def test_the_login_is_done_once_per_account():
    client, (session,) = make_client([login_payload(), history_payload([]), history_payload([])])

    client.fetch_history(arl_account())
    client.fetch_history(arl_account())

    logins = [p for p, _ in session.calls if p["method"] == "deezer.getUserData"]
    assert len(logins) == 1


def test_the_profile_comes_from_the_login_response():
    client, _ = make_client([login_payload(user_id=2529, country="FR")])

    profile = client.fetch_profile(arl_account())

    assert (profile.user_id, profile.country) == ("2529", "FR")


def test_the_country_is_the_subscription_market_not_a_geolocation():
    """`COUNTRY` stays FR for a French account browsing from abroad."""
    payload = login_payload(country="FR")
    payload["results"]["USER"]["SETTING"] = {"location": {"city": "Sherbrooke", "source": "ip"}}
    client, _ = make_client([payload])

    assert client.fetch_profile(arl_account()).country == "FR"


def test_a_missing_or_odd_country_is_dropped():
    client, _ = make_client([login_payload(country="")])

    assert client.fetch_profile(arl_account()).country is None


def test_an_expired_arl_raises_an_explicit_auth_error():
    client, _ = make_client([login_payload(user_id=0)])

    with pytest.raises(DeezerAuthError, match="invalid or expired ARL"):
        client.fetch_history(arl_account())


def test_a_login_without_csrf_token_raises_an_auth_error():
    client, _ = make_client([login_payload(check_form=None)])

    with pytest.raises(DeezerAuthError, match="invalid or expired ARL"):
        client.fetch_profile(arl_account())


def test_an_expired_csrf_token_triggers_one_relogin_and_one_retry():
    expired = {"error": {"VALID_TOKEN_REQUIRED": "Invalid CSRF token"}, "results": {}}
    client, sessions = make_client(
        [login_payload(), expired],
        [login_payload(check_form="fresh-token"), history_payload([gw_entry()])],
    )

    entries = client.fetch_history(arl_account())

    assert len(entries) == 1
    retry_params, _ = sessions[1].calls[-1]
    assert retry_params["api_token"] == "fresh-token"


def test_other_gateway_errors_are_reported_as_such():
    failure = {"error": {"UNKNOWN": "boom"}, "results": {}}
    client, _ = make_client([login_payload(), failure])

    with pytest.raises(DeezerError, match="boom") as raised:
        client.fetch_history(arl_account())

    assert not isinstance(raised.value, DeezerAuthError)
