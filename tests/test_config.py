from datetime import UTC
from zoneinfo import ZoneInfo

import pytest

from deezync.config import ConfigError, load_accounts, load_settings

USERS_TOML = """
[[accounts]]
name = "adrien"
access_token = "token-adrien"
timezone = "Europe/Paris"

[[accounts]]
name = "alice"
access_token = "token-alice"
timezone = "UTC"
"""


@pytest.fixture(autouse=True)
def minimal_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ES_URL", "https://es.example.com")
    monkeypatch.setenv("ES_API_KEY", "key")


def write(tmp_path, content, name="users.toml"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_accounts_are_read_from_the_toml_file(tmp_path):
    accounts = load_accounts(write(tmp_path, USERS_TOML))

    assert [account.name for account in accounts] == ["adrien", "alice"]
    assert accounts[0].display_timezone == ZoneInfo("Europe/Paris")
    assert accounts[1].display_timezone is UTC


def test_a_missing_users_file_is_reported(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_accounts(tmp_path / "missing.toml")


def test_an_empty_users_file_is_reported(tmp_path):
    with pytest.raises(ConfigError, match="no account"):
        load_accounts(write(tmp_path, "# nothing here\n"))


def test_an_account_without_credentials_is_reported(tmp_path):
    content = '[[accounts]]\nname = "adrien"\ntimezone = "UTC"\n'

    with pytest.raises(ConfigError, match="access_token.*arl"):
        load_accounts(write(tmp_path, content))


def test_an_arl_account_is_accepted(tmp_path):
    content = '[[accounts]]\nname = "adrien"\narl = "arl-cookie"\ntimezone = "UTC"\n'

    (account,) = load_accounts(write(tmp_path, content))

    assert account.auth_method == "arl"
    assert account.arl == "arl-cookie"


def test_an_account_with_both_credentials_is_rejected(tmp_path):
    content = '[[accounts]]\nname = "adrien"\naccess_token = "t"\narl = "c"\ntimezone = "UTC"\n'

    with pytest.raises(ConfigError, match="exactly one"):
        load_accounts(write(tmp_path, content))


def test_each_account_carries_its_own_timezone(tmp_path):
    """Profiles living in different countries each keep a meaningful hourOfDay."""
    content = (
        '[[accounts]]\nname = "adrien"\narl = "a"\ntimezone = "Europe/Paris"\n'
        '[[accounts]]\nname = "emma"\narl = "b"\ntimezone = "America/Montreal"\n'
    )

    adrien, emma = load_accounts(write(tmp_path, content))

    assert adrien.display_timezone == ZoneInfo("Europe/Paris")
    assert emma.display_timezone == ZoneInfo("America/Montreal")


def test_an_account_without_a_timezone_is_reported(tmp_path):
    """No silent UTC: a wrong hourOfDay looks just as plausible as a right one."""
    with pytest.raises(ConfigError, match="timezone` is required"):
        load_accounts(write(tmp_path, '[[accounts]]\nname = "adrien"\narl = "x"\n'))


def test_an_unknown_account_timezone_is_reported(tmp_path):
    content = '[[accounts]]\nname = "adrien"\narl = "a"\ntimezone = "Mars/Olympus"\n'

    with pytest.raises(ConfigError, match="adrien"):
        load_accounts(write(tmp_path, content))


def test_neither_the_profile_id_nor_the_country_are_configurable(tmp_path):
    """Both are read from Deezer at login, so users.toml simply ignores them."""
    content = (
        '[[accounts]]\nname = "adrien"\narl = "a"\ntimezone = "UTC"\n'
        'user_id = "9999"\ncountry = "ZZ"\n'
    )

    (account,) = load_accounts(write(tmp_path, content))

    assert not hasattr(account, "user_id")
    assert not hasattr(account, "country")


def test_duplicate_account_names_are_reported(tmp_path):
    content = USERS_TOML + '\n[[accounts]]\nname = "adrien"\naccess_token = "o"\ntimezone = "UTC"\n'

    with pytest.raises(ConfigError, match="duplicate"):
        load_accounts(write(tmp_path, content))


def test_settings_fall_back_on_defaults():
    settings = load_settings()

    assert settings.es_index == "deezer-history"
    assert settings.users_file.name == "users.toml"


def test_elasticsearch_url_is_required(monkeypatch):
    monkeypatch.delenv("ES_URL")

    with pytest.raises(ConfigError, match="ES_URL"):
        load_settings()


def test_authentication_is_required(monkeypatch):
    monkeypatch.delenv("ES_API_KEY")

    with pytest.raises(ConfigError, match="authentication"):
        load_settings()


def test_basic_auth_is_accepted_instead_of_an_api_key(monkeypatch):
    monkeypatch.delenv("ES_API_KEY")
    monkeypatch.setenv("ES_USERNAME", "elastic")
    monkeypatch.setenv("ES_PASSWORD", "secret")

    assert load_settings().es_username == "elastic"


def test_the_command_line_users_file_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("DEEZYNC_USERS_FILE", "from-env.toml")

    assert load_settings("from-cli.toml").users_file.name == "from-cli.toml"


def test_the_env_file_of_the_working_directory_is_read(tmp_path):
    (tmp_path / ".env").write_text("ES_INDEX=from-env\n", encoding="utf-8")

    assert load_settings().es_index == "from-env"


def test_no_env_file_is_looked_up_outside_the_working_directory(tmp_path, monkeypatch):
    """An upward search would load a .env belonging to another project."""
    (tmp_path / ".env").write_text("ES_INDEX=from-the-parent\n", encoding="utf-8")
    working_directory = tmp_path / "project"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    assert load_settings().es_index == "deezer-history"
