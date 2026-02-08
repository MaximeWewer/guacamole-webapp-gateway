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
