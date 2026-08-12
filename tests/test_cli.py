import pytest

from deezync import cli
from deezync.config import Settings
from deezync.domain.account import DeezerProfile
from deezync.infrastructure.deezer_client import DeezerAuthError

USERS_TOML = """
[[accounts]]
name = "adrien"
access_token = "token-adrien"
timezone = "Europe/Paris"
"""


class FakeDeezerClient:
    """Stands in for the real clients, which the CLI instantiates without arguments."""

    history = [{"id": 3135556, "title": "Track", "timestamp": 1722945600}]
    failing_tokens: set[str] = set()

    def fetch_profile(self, account):
        return DeezerProfile(user_id="2529", country="FR")

    def fetch_history(self, account, user_id="me", limit=100):
        if account.access_token in self.failing_tokens:
            raise DeezerAuthError("invalid or expired token")
        return self.history


class FakeElasticsearch:
    """Captures the arguments the Elasticsearch client is built with."""

    instances = []

    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.documents = {}
        FakeElasticsearch.instances.append(self)
        self.indices = self

    def exists(self, index):
        return True

    def create(self, index, **body):
        return {"acknowledged": True}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "users.toml").write_text(USERS_TOML, encoding="utf-8")
    (tmp_path / ".env").write_text(
        "ES_URL=http://localhost:9200\nES_API_KEY=key\nES_INDEX=deezync-test\n",
        encoding="utf-8",
    )
    FakeDeezerClient.failing_tokens = set()
    FakeElasticsearch.instances = []
    monkeypatch.setattr(cli, "DeezerClient", FakeDeezerClient)
    monkeypatch.setattr(cli, "DeezerGwClient", FakeDeezerClient)
    monkeypatch.setattr(cli, "Elasticsearch", FakeElasticsearch)
    monkeypatch.setattr(cli.ListenRepository, "save_all", lambda self, listens: _count(listens))
    return tmp_path


def _count(listens):
    from deezync.infrastructure.listen_repository import SaveResult

    return SaveResult(created=len(list(listens)))


def test_a_successful_run_exits_with_zero(workspace):
    assert cli.main([]) == 0


def test_an_invalid_configuration_exits_with_two(workspace):
    (workspace / ".env").write_text("ES_URL=http://localhost:9200\n", encoding="utf-8")

    assert cli.main([]) == 2


def test_a_missing_users_file_exits_with_two(workspace):
    (workspace / "users.toml").unlink()

    assert cli.main([]) == 2


def test_a_failing_account_exits_with_one(workspace):
    FakeDeezerClient.failing_tokens = {"token-adrien"}

    assert cli.main([]) == 1


def test_the_users_file_option_is_honoured(workspace):
    (workspace / "other.toml").write_text(
        '[[accounts]]\nname = "alice"\naccess_token = "token-alice"\ntimezone = "UTC"\n',
        encoding="utf-8",
    )

    assert cli.main(["--users", "other.toml"]) == 0


def test_the_api_key_is_passed_to_elasticsearch(workspace):
    cli.main([])

    client = FakeElasticsearch.instances[0]
    assert client.url == "http://localhost:9200"
    assert client.kwargs["api_key"] == "key"
    assert client.kwargs["basic_auth"] is None


def test_basic_auth_is_passed_to_elasticsearch(workspace):
    (workspace / ".env").write_text(
        "ES_URL=http://localhost:9200\nES_USERNAME=elastic\nES_PASSWORD=secret\n",
        encoding="utf-8",
    )

    cli.main([])

    client = FakeElasticsearch.instances[0]
    assert client.kwargs["api_key"] is None
    assert client.kwargs["basic_auth"] == ("elastic", "secret")


def test_the_summary_reports_the_indexed_listens(workspace, caplog):
    with caplog.at_level("INFO", logger="deezync"):
        cli.main([])

    assert "1 new listen(s) indexed into deezync-test" in caplog.text


def test_the_summary_reports_a_failing_account(workspace, caplog):
    FakeDeezerClient.failing_tokens = {"token-adrien"}

    with caplog.at_level("ERROR"):
        cli.main([])

    assert "adrien" in caplog.text and "expired token" in caplog.text


def test_the_repository_targets_the_configured_index(workspace, monkeypatch):
    captured = {}
    original = cli.ListenRepository.__init__

    def spy(self, client, index, **kwargs):
        captured["index"] = index
        captured.update(kwargs)
        original(self, client, index, **kwargs)

    monkeypatch.setattr(cli.ListenRepository, "__init__", spy)
    cli.main([])

    assert captured["index"] == "deezync-test"


def test_settings_are_a_plain_value_object():
    settings = Settings(es_url="http://localhost:9200")

    assert settings.es_index == "deezer-history"
