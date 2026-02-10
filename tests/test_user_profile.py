"""
Tests for broker.domain.user_profile.UserProfile.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def user_data_tmp(tmp_path, mocker):
    """Redirect USER_DATA_PATH to a temp directory."""
    mocker.patch("broker.domain.user_profile.USER_DATA_PATH", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# get_user_path
# ---------------------------------------------------------------------------

class TestGetUserPath:

    def test_get_user_path(self, user_data_tmp):
        """Path sanitised under USER_DATA_PATH."""
        from broker.domain.user_profile import UserProfile
        p = UserProfile.get_user_path("alice")
        assert p == user_data_tmp / "alice"

    def test_get_user_path_sanitised(self, user_data_tmp):
        """Special characters stripped."""
        from broker.domain.user_profile import UserProfile
        p = UserProfile.get_user_path("al!ce@foo")
        assert ".." not in str(p)
        assert "@" not in p.name


# ---------------------------------------------------------------------------
# ensure_profile
# ---------------------------------------------------------------------------

class TestEnsureProfile:

    def test_ensure_profile_firefox(self, user_data_tmp, mock_broker_config):
        """Creates desktop/ + firefox-policies/."""
        from broker.domain.user_profile import UserProfile
        p = UserProfile.ensure_profile("alice")
        assert (p / "desktop").is_dir()
        assert (p / "firefox-policies").is_dir()

    def test_ensure_profile_chromium(self, user_data_tmp, mocker):
        """Creates desktop/ + chromium-policies/managed/."""
        mocker.patch("broker.config.loader.BrokerConfig.get_browser_type", return_value="chromium")
        from broker.domain.user_profile import UserProfile
        p = UserProfile.ensure_profile("bob")
        assert (p / "desktop").is_dir()
        assert (p / "chromium-policies" / "managed").is_dir()


# ---------------------------------------------------------------------------
# _expand_autofill_variables
# ---------------------------------------------------------------------------

class TestExpandVariables:

    def test_expand_guac_username(self, mocker):
        """${GUAC_USERNAME} → username."""
        mocker.patch("broker.config.secrets.secrets_provider", MagicMock(get=MagicMock(return_value="")))
        from broker.domain.user_profile import UserProfile
        autofill = [{"url": "https://example.com", "username": "${GUAC_USERNAME}"}]
        result = UserProfile._expand_autofill_variables(autofill, "alice")
        assert result[0]["username"] == "alice"

    def test_expand_vault_secret(self, mocker):
        """${vault:key} → secrets_provider.get(key)."""
        mock_sp = MagicMock()
        mock_sp.get.return_value = "vault-value"
        mocker.patch("broker.config.secrets.secrets_provider", mock_sp)
        from broker.domain.user_profile import UserProfile
        autofill = [{"password": "${vault:db_pass}"}]
        result = UserProfile._expand_autofill_variables(autofill, "user")
        assert result[0]["password"] == "vault-value"

    def test_expand_env_var(self, mocker):
        """${env:VAR} → os.environ[VAR]."""
        mocker.patch("broker.config.secrets.secrets_provider", MagicMock(get=MagicMock(return_value="")))
        os.environ["TEST_BROKER_VAR"] = "env-value"
        try:
            from broker.domain.user_profile import UserProfile
            autofill = [{"username": "${env:TEST_BROKER_VAR}"}]
            result = UserProfile._expand_autofill_variables(autofill, "user")
            assert result[0]["username"] == "env-value"
        finally:
            del os.environ["TEST_BROKER_VAR"]


# ---------------------------------------------------------------------------
# Firefox policies
# ---------------------------------------------------------------------------

class TestFirefoxPolicies:

    def test_firefox_policies_basic(self, user_data_tmp, mock_broker_config):
        """JSON with DisableAppUpdate, ManagedBookmarks, Homepage."""
        from broker.domain.user_profile import UserProfile
        bookmarks = [{"name": "Google", "url": "https://google.com"}]
        UserProfile._set_firefox_policies("alice", bookmarks, "https://home.example.com", [])

        policies_file = user_data_tmp / "alice" / "firefox-policies" / "policies.json"
        assert policies_file.exists()
        data = json.loads(policies_file.read_text())

        assert data["policies"]["DisableAppUpdate"] is True
        assert data["policies"]["Homepage"]["URL"] == "https://home.example.com"
        assert len(data["policies"]["ManagedBookmarks"]) == 2  # toplevel_name + 1 bookmark
        assert data["policies"]["ManagedBookmarks"][1]["url"] == "https://google.com"

    def test_firefox_policies_autofill(self, user_data_tmp, mock_broker_config, mocker):
        """Logins array in policies.json."""
        mocker.patch("broker.config.secrets.secrets_provider", MagicMock(get=MagicMock(return_value="")))
        from broker.domain.user_profile import UserProfile
        autofill = [{"url": "https://app.example.com", "username": "alice", "password": "p4ss"}]
        UserProfile._set_firefox_policies("alice", [], "", autofill)

        policies_file = user_data_tmp / "alice" / "firefox-policies" / "policies.json"
        data = json.loads(policies_file.read_text())

        assert "Logins" in data["policies"]
        assert data["policies"]["Logins"][0]["origin"] == "https://app.example.com"
        assert data["policies"]["Logins"][0]["username"] == "alice"


# ---------------------------------------------------------------------------
# Chromium policies
# ---------------------------------------------------------------------------

class TestChromiumPolicies:

    def test_chromium_policies_basic(self, user_data_tmp, mocker):
        """JSON with ManagedBookmarks, HomepageLocation, RestoreOnStartup."""
        mocker.patch("broker.config.loader.BrokerConfig.get_browser_type", return_value="chromium")
        from broker.domain.user_profile import UserProfile
        bookmarks = [{"name": "Google", "url": "https://google.com"}]
        UserProfile._set_chromium_policies("bob", bookmarks, "https://home.example.com", [])

        policies_file = user_data_tmp / "bob" / "chromium-policies" / "managed" / "bookmarks.json"
        assert policies_file.exists()
        data = json.loads(policies_file.read_text())

        assert data["HomepageLocation"] == "https://home.example.com"
        assert data["HomepageIsNewTabPage"] is False
        assert data["RestoreOnStartup"] == 4
        assert len(data["ManagedBookmarks"]) == 2

    def test_chromium_no_homepage(self, user_data_tmp, mocker):
        """HomepageIsNewTabPage=true, RestoreOnStartup=5."""
        mocker.patch("broker.config.loader.BrokerConfig.get_browser_type", return_value="chromium")
        from broker.domain.user_profile import UserProfile
        UserProfile._set_chromium_policies("bob", [], "", [])

        policies_file = user_data_tmp / "bob" / "chromium-policies" / "managed" / "bookmarks.json"
        data = json.loads(policies_file.read_text())

        assert data["HomepageIsNewTabPage"] is True
        assert data["RestoreOnStartup"] == 5


# ---------------------------------------------------------------------------
# apply_profile_config
# ---------------------------------------------------------------------------

class TestApplyProfileConfig:

    def test_apply_profile_config(self, user_data_tmp, mocker, mock_broker_config):
        """Orchestrates get_user_config → set_browser_policies."""
        mocker.patch("broker.config.loader.ProfilesConfig.get_user_config", return_value={
            "homepage": "https://example.com",
            "bookmarks": [{"name": "Ex", "url": "https://example.com"}],
            "autofill": [],
        })
        set_mock = mocker.patch("broker.domain.user_profile.UserProfile.set_browser_policies")

        from broker.domain.user_profile import UserProfile
        result = UserProfile.apply_profile_config("alice", ["developers"])

        assert result["browser"] == "firefox"
        assert result["bookmarks"] == 1
        set_mock.assert_called_once()


# ---------------------------------------------------------------------------
# get_volume_mounts
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cumulative merge (ProfilesConfig.get_user_config)
# ---------------------------------------------------------------------------

class TestCumulativeMerge:

    def _load_profiles(self, mocker, profiles_dict):
        """Helper: patch ProfilesConfig.load to return given dict."""
        mocker.patch("broker.config.loader.ProfilesConfig.load", return_value=profiles_dict)

    def test_merge_multiple_profiles(self, mocker):
        """User in 2 groups → bookmarks from both profiles merged."""
        self._load_profiles(mocker, {
            "developers": {
                "priority": 10,
                "homepage": "https://github.com",
                "bookmarks": [{"name": "GitHub", "url": "https://github.com"}],
            },
            "intranet": {
                "priority": 5,
                "bookmarks": [{"name": "Intranet", "url": "https://intranet.example.com"}],
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["developers", "intranet"])
        urls = [bm["url"] for bm in result["bookmarks"]]
        assert "https://github.com" in urls
        assert "https://intranet.example.com" in urls
        assert len(result["bookmarks"]) == 2

    def test_merge_dedup_bookmarks(self, mocker):
        """Same bookmark URL in 2 profiles → appears only once."""
        self._load_profiles(mocker, {
            "a": {
                "priority": 1,
                "bookmarks": [{"name": "Google", "url": "https://google.com"}],
            },
            "b": {
                "priority": 2,
                "bookmarks": [{"name": "Google2", "url": "https://google.com"}],
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["a", "b"])
        assert len(result["bookmarks"]) == 1

    def test_merge_dedup_autofill(self, mocker):
        """Same autofill URL in 2 profiles → appears only once."""
        self._load_profiles(mocker, {
            "a": {
                "priority": 1,
                "autofill": [{"url": "https://app.com", "username": "user1"}],
            },
            "b": {
                "priority": 2,
                "autofill": [{"url": "https://app.com", "username": "user2"}],
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["a", "b"])
        assert len(result["autofill"]) == 1

    def test_homepage_highest_priority_wins(self, mocker):
        """2 profiles with homepage → highest priority wins."""
        self._load_profiles(mocker, {
            "low": {"priority": 1, "homepage": "https://low.com"},
            "high": {"priority": 10, "homepage": "https://high.com"},
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["low", "high"])
        assert result["homepage"] == "https://high.com"

    def test_default_always_inherited(self, mocker):
        """User without specific group → receives default profile."""
        self._load_profiles(mocker, {
            "default": {
                "priority": 0,
                "homepage": "https://default.com",
                "bookmarks": [{"name": "Default", "url": "https://default.com"}],
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["unknown_group"])
        assert result["homepage"] == "https://default.com"
        assert "default" in result["groups"]

    def test_default_merged_with_group(self, mocker):
        """User in a group + default exists → bookmarks from both are merged."""
        self._load_profiles(mocker, {
            "default": {
                "priority": 0,
                "homepage": "https://default.com",
                "bookmarks": [{"name": "Default", "url": "https://default.com"}],
            },
            "developers": {
                "priority": 10,
                "homepage": "https://github.com",
                "bookmarks": [{"name": "GitHub", "url": "https://github.com"}],
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["developers"])
        urls = [bm["url"] for bm in result["bookmarks"]]
        assert "https://default.com" in urls
        assert "https://github.com" in urls
        assert result["homepage"] == "https://github.com"

    def test_user_override_homepage(self, mocker):
        """_users.alice.homepage overrides profile homepage."""
        self._load_profiles(mocker, {
            "default": {"priority": 0, "homepage": "https://default.com"},
            "_users": {
                "alice": {"homepage": "https://alice.example.com"},
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["default"], username="alice")
        assert result["homepage"] == "https://alice.example.com"

    def test_user_override_bookmarks(self, mocker):
        """_users.alice.bookmarks are added at the front."""
        self._load_profiles(mocker, {
            "default": {
                "priority": 0,
                "bookmarks": [{"name": "Google", "url": "https://google.com"}],
            },
            "_users": {
                "alice": {
                    "bookmarks": [{"name": "Alice", "url": "https://alice.example.com"}],
                },
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["default"], username="alice")
        assert result["bookmarks"][0]["url"] == "https://alice.example.com"
        assert len(result["bookmarks"]) == 2

    def test_user_override_autofill(self, mocker):
        """_users.alice.autofill entries are added."""
        self._load_profiles(mocker, {
            "default": {"priority": 0},
            "_users": {
                "alice": {
                    "autofill": [{"url": "https://special.com", "username": "alice"}],
                },
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["default"], username="alice")
        assert len(result["autofill"]) == 1
        assert result["autofill"][0]["url"] == "https://special.com"

    def test_backward_compat_no_username(self, mocker):
        """Calling without username still works (backward compat)."""
        self._load_profiles(mocker, {
            "default": {
                "priority": 0,
                "homepage": "https://default.com",
                "bookmarks": [{"name": "Default", "url": "https://default.com"}],
            },
            "_users": {
                "alice": {"homepage": "https://alice.example.com"},
            },
        })
        from broker.config.loader import ProfilesConfig
        result = ProfilesConfig.get_user_config(["default"])
        assert result["homepage"] == "https://default.com"


# ---------------------------------------------------------------------------
# get_volume_mounts
# ---------------------------------------------------------------------------

class TestGetVolumeMounts:

    def test_get_volume_mounts(self, user_data_tmp, mock_broker_config):
        """Returns dict with browser-specific paths."""
        from broker.domain.user_profile import UserProfile
        # Ensure profile exists first
        UserProfile.ensure_profile("alice")
        mounts = UserProfile.get_volume_mounts("alice")

        # desktop mount
        desktop_key = str(user_data_tmp / "alice" / "desktop")
        assert desktop_key in mounts
        assert mounts[desktop_key]["bind"] == "/headless/Desktop"

        # firefox policies mount
        ff_key = str(user_data_tmp / "alice" / "firefox-policies")
        assert ff_key in mounts
        assert mounts[ff_key]["bind"] == "/etc/firefox/policies"
