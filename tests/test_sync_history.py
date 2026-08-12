import pytest

from deezync.application.sync_history import SyncHistory
from deezync.domain.account import DeezerAccount, DeezerProfile
from deezync.infrastructure.deezer_client import DeezerAuthError
from deezync.infrastructure.listen_repository import SaveResult

PROFILES = {
    "token-adrien": DeezerProfile(user_id="2529", country="FR"),
    "token-alice": DeezerProfile(user_id="3040", country="BE"),
    "arl-alice": DeezerProfile(user_id="3040", country="BE"),
}


class FakeDeezer:
    """In-memory Deezer client: one history per user id."""

    def __init__(self, history_by_user, profiles=None, failing_credentials=()):
        self._history_by_user = history_by_user
        self._profiles = PROFILES if profiles is None else profiles
        self._failing_credentials = set(failing_credentials)
        self.accounts_seen = []
        self.profile_calls = 0

    def fetch_profile(self, account):
        self._check(account)
        self.profile_calls += 1
        return self._profiles[account.access_token or account.arl]

    def fetch_history(self, account, user_id="me", limit=100):
        self._check(account)
        self.accounts_seen.append(account.name)
        return self._history_by_user.get(user_id, [])[:limit]

    def _check(self, account):
        if (account.access_token or account.arl) in self._failing_credentials:
            raise DeezerAuthError("invalid or expired token")


class FakeRepository:
    """In-memory repository reproducing the `create` semantics of Elasticsearch."""

    def __init__(self):
        self.documents = {}
        self.index_created = False

    def ensure_index(self):
        self.index_created = True
        return True

    def save_all(self, listens):
        created = already_present = 0
        for listen in listens:
            document = listen.to_document()
            if document["id"] in self.documents:
                already_present += 1
            else:
                self.documents[document["id"]] = document
                created += 1
        return SaveResult(created=created, already_present=already_present)


@pytest.fixture
def repository():
    return FakeRepository()


def sync(deezer, repository):
    return SyncHistory({"oauth": deezer, "arl": deezer}, repository)


def account(name="adrien", token="token-adrien"):
    return DeezerAccount(name=name, access_token=token)


def entries_at(timestamps, track_id=3135556):
    return [{"id": track_id, "title": "Track", "timestamp": ts} for ts in timestamps]


def test_index_is_created_before_writing(repository):
    sync(FakeDeezer({}), repository).run([])
    assert repository.index_created


def test_listens_are_indexed_for_the_account(repository):
    deezer = FakeDeezer({"2529": entries_at([1722945600, 1722945900])})

    (report,) = sync(deezer, repository).run([account()])

    assert (report.fetched, report.created, report.already_present) == (2, 2, 0)
    assert report.ok


def test_running_twice_creates_no_duplicate(repository):
    deezer = FakeDeezer({"2529": entries_at([1722945600, 1722945900])})
    use_case = sync(deezer, repository)

    use_case.run([account()])
    (report,) = use_case.run([account()])

    assert (report.created, report.already_present) == (0, 2)
    assert len(repository.documents) == 2


def test_only_new_listens_are_created_on_the_next_run(repository):
    history = entries_at([1722945600])
    deezer = FakeDeezer({"2529": history})
    use_case = sync(deezer, repository)
    use_case.run([account()])

    history.insert(0, *entries_at([1722946200]))
    (report,) = use_case.run([account()])

    assert (report.created, report.already_present) == (1, 1)


def test_each_account_is_synced_with_its_own_history(repository):
    deezer = FakeDeezer({"2529": entries_at([1722945600]), "3040": entries_at([1722945600])})

    reports = sync(deezer, repository).run([account(), account("alice", "token-alice")])

    assert [report.created for report in reports] == [1, 1]
    assert {doc["user"] for doc in repository.documents.values()} == {"adrien", "alice"}


def test_the_client_is_picked_from_the_auth_method(repository):
    oauth = FakeDeezer({"2529": entries_at([1722945600])})
    arl = FakeDeezer({"3040": entries_at([1722945600])})
    use_case = SyncHistory({"oauth": oauth, "arl": arl}, repository)

    reports = use_case.run([account(), DeezerAccount(name="alice", arl="arl-alice")])

    assert all(report.ok for report in reports)
    assert oauth.accounts_seen == ["adrien"]
    assert arl.accounts_seen == ["alice"]


def test_a_failing_account_does_not_stop_the_others(repository):
    deezer = FakeDeezer(
        {"2529": entries_at([1722945600]), "3040": entries_at([1722945600])},
        failing_credentials=["token-alice"],
    )

    failed, healthy = sync(deezer, repository).run([account("alice", "token-alice"), account()])

    assert not failed.ok and "expired token" in failed.error
    assert healthy.ok and healthy.created == 1


def test_the_profile_is_resolved_from_deezer_on_every_run(repository):
    """Nothing about the identity is configured: it comes from the login call."""
    deezer = FakeDeezer({"2529": entries_at([1722945600])})

    (report,) = sync(deezer, repository).run([account()])

    assert deezer.profile_calls == 1
    assert report.created == 1


def test_the_country_comes_from_the_deezer_profile(repository):
    """The subscription market is read at login, never declared in users.toml."""
    deezer = FakeDeezer({"3040": entries_at([1722945600])})

    sync(deezer, repository).run([account("alice", "token-alice")])

    (document,) = repository.documents.values()
    assert document["country"] == "BE"


def test_a_profile_without_a_country_leaves_the_field_out(repository):
    deezer = FakeDeezer(
        {"2529": entries_at([1722945600])},
        profiles={"token-adrien": DeezerProfile(user_id="2529")},
    )

    sync(deezer, repository).run([account()])

    (document,) = repository.documents.values()
    assert "country" not in document


def test_unusable_entries_are_skipped(repository):
    deezer = FakeDeezer({"2529": [{"id": 1, "title": "no timestamp"}]})

    (report,) = sync(deezer, repository).run([account()])

    assert (report.fetched, report.created) == (1, 0)


def test_the_history_entry_is_stored_as_metadata_without_extra_lookups(repository, gateway_entry):
    """The gateway ships the full record, so syncing costs one call per account."""
    deezer = FakeDeezer({"2529": [gateway_entry]})

    (report,) = sync(deezer, repository).run([account()])

    assert report.created == 1
    (document,) = repository.documents.values()
    metadata = document["deezer_metadata"]
    assert metadata["isrc"] == "GBDUW0000059"
    assert metadata["track_position"] == 4
    assert metadata["contributors"]["main_artist"] == ["Daft Punk"]
