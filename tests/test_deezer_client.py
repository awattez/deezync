import pytest

from deezync.domain.account import DeezerAccount
from deezync.infrastructure.deezer_client import (
    DeezerAuthError,
    DeezerClient,
    DeezerError,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    """HTTP session returning canned responses and recording the calls."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self._payloads.pop(0))


def oauth_account(token="token"):
    return DeezerAccount(name="adrien", access_token=token)


def page(size, start=0):
    return {"data": [{"id": start + i, "timestamp": 1722945600 + i} for i in range(size)]}


def test_history_is_fetched_in_two_pages_of_fifty():
    session = FakeSession([page(50), page(50, start=50)])

    entries = DeezerClient(session=session).fetch_history(oauth_account())

    assert len(entries) == 100
    assert [params["index"] for _, params in session.calls] == [0, 50]
    assert [params["limit"] for _, params in session.calls] == [50, 50]


def test_pagination_stops_on_a_partial_page():
    session = FakeSession([page(12)])

    entries = DeezerClient(session=session).fetch_history(oauth_account())

    assert len(entries) == 12
    assert len(session.calls) == 1


def test_the_access_token_is_sent_on_every_call():
    session = FakeSession([page(50), page(50, start=50)])

    DeezerClient(session=session).fetch_history(oauth_account("secret"))

    assert all(params["access_token"] == "secret" for _, params in session.calls)


def test_history_targets_the_requested_user():
    session = FakeSession([page(1)])

    DeezerClient(session=session).fetch_history(oauth_account(), user_id="2529")

    url, _ = session.calls[0]
    assert url.endswith("/user/2529/history")


def test_expired_token_raises_an_explicit_auth_error():
    session = FakeSession(
        [
            {
                "error": {
                    "type": "OAuthException",
                    "message": "Invalid OAuth access token",
                    "code": 300,
                }
            }
        ]
    )

    with pytest.raises(DeezerAuthError, match="expired token"):
        DeezerClient(session=session).fetch_history(oauth_account())


def test_other_api_errors_are_reported_as_such():
    session = FakeSession(
        [{"error": {"type": "Exception", "message": "Quota exceeded", "code": 4}}]
    )

    with pytest.raises(DeezerError, match="Quota exceeded") as raised:
        DeezerClient(session=session).fetch_history(oauth_account())

    assert not isinstance(raised.value, DeezerAuthError)


def test_the_profile_is_read_from_the_me_endpoint():
    session = FakeSession([{"id": 2529, "name": "adrien", "country": "FR"}])

    profile = DeezerClient(session=session).fetch_profile(oauth_account())

    assert (profile.user_id, profile.country) == ("2529", "FR")


def test_a_me_response_without_a_country_yields_none():
    session = FakeSession([{"id": 2529, "name": "adrien"}])

    assert DeezerClient(session=session).fetch_profile(oauth_account()).country is None
