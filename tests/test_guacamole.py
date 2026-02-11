"""
Tests for broker.domain.guacamole.GuacamoleAPI.
"""

import time
from unittest.mock import MagicMock

import pytest
import requests

from broker.config.models import BrokerSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api():
    """Create a GuacamoleAPI instance without triggering module-level globals."""
    from broker.domain.guacamole import GuacamoleAPI
    return GuacamoleAPI("http://guac:8080/guacamole", "admin", "secret")


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError()
    return resp


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------

class TestAuthenticate:

    def test_authenticate_success(self, mocker):
        """POST /api/tokens → stores token + data_source."""
        api = _make_api()
        mocker.patch("broker.domain.guacamole.requests.post", return_value=_mock_response(
            json_data={
                "authToken": "tok-123",
                "availableDataSources": ["postgresql"],
            }
        ))
        token = api.authenticate()

        assert token == "tok-123"
        assert api.token == "tok-123"
        assert api.data_source == "postgresql"
        assert api.token_expires > time.time()


class TestEnsureAuth:

    def test_ensure_auth_refreshes_expired(self, mocker):
        """Token expired → re-authenticate."""
        api = _make_api()
        api.token = "old-token"
        api.token_expires = time.time() - 100  # expired

        mock_post = mocker.patch("broker.domain.guacamole.requests.post", return_value=_mock_response(
            json_data={"authToken": "new-token", "availableDataSources": ["postgresql"]}
        ))
        api.ensure_auth()

        assert api.token == "new-token"
        mock_post.assert_called_once()

    def test_ensure_auth_keeps_valid(self, mocker):
        """Token valid → no HTTP request."""
        api = _make_api()
        api.token = "valid-token"
        api.token_expires = time.time() + 3000

        mock_post = mocker.patch("broker.domain.guacamole.requests.post")
        api.ensure_auth()

        mock_post.assert_not_called()
        assert api.token == "valid-token"


# ---------------------------------------------------------------------------
# create_connection
# ---------------------------------------------------------------------------

class TestCreateConnection:

    def test_create_connection_basic(self, mocker, mock_broker_config):
        """POST with VNC params (hostname, port, password, color-depth)."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        mock_post = mocker.patch("broker.domain.guacamole.requests.post", return_value=_mock_response(
            json_data={"identifier": "100"}
        ))
        conn_id = api.create_connection("Desktop", "172.18.0.5", 5901, "vnc-pw", username="alice")

        assert conn_id == "100"
        call_kwargs = mock_post.call_args
        json_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert json_body["protocol"] == "vnc"
        assert json_body["parameters"]["hostname"] == "172.18.0.5"
        assert json_body["parameters"]["port"] == "5901"
        assert json_body["parameters"]["password"] == "vnc-pw"
        assert json_body["parameters"]["color-depth"] == "24"

    def test_create_connection_with_recording(self, mocker):
        """Recording enabled → recording-path and recording-name params."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        # Override BrokerConfig to enable recording
        custom_settings = BrokerSettings(guacamole={"recording": {
            "enabled": True,
            "path": "/recordings",
            "name": "${GUAC_USERNAME}-session",
            "include_keys": False,
            "auto_create_path": True,
        }})
        mocker.patch("broker.config.loader.BrokerConfig.settings", return_value=custom_settings)

        mock_post = mocker.patch("broker.domain.guacamole.requests.post", return_value=_mock_response(
            json_data={"identifier": "101"}
        ))
        api.create_connection("Desktop", "10.0.0.1", 5901, "pw", username="bob")

        json_body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        params = json_body["parameters"]
        assert params["recording-path"] == "/recordings"
        assert "bob-session" in params["recording-name"]
        assert params["create-recording-path"] == "true"


# ---------------------------------------------------------------------------
# update_connection
# ---------------------------------------------------------------------------

class TestUpdateConnection:

    def test_update_connection(self, mocker):
        """GET existing + PUT with new params."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        existing_conn = {"name": "Desktop", "protocol": "vnc", "parameters": {}}
        existing_params = {"hostname": "old", "port": "5901", "color-depth": "24"}

        mock_get = mocker.patch("broker.domain.guacamole.requests.get", side_effect=[
            _mock_response(json_data=existing_conn),
            _mock_response(json_data=existing_params),
        ])
        mock_put = mocker.patch("broker.domain.guacamole.requests.put")

        api.update_connection("42", "172.18.0.10", 5901, "new-pw")

        mock_put.assert_called_once()
        put_body = mock_put.call_args.kwargs.get("json") or mock_put.call_args[1].get("json")
        assert put_body["parameters"]["hostname"] == "172.18.0.10"
        assert put_body["parameters"]["password"] == "new-pw"
        # Preserved from existing
        assert put_body["parameters"]["color-depth"] == "24"


# ---------------------------------------------------------------------------
# sync_connection_config
# ---------------------------------------------------------------------------

class TestSyncConnectionConfig:

    def test_sync_connection_config(self, mocker):
        """Updates recording + connection_name from config."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        custom_settings = BrokerSettings(
            containers={"connection_name": "My Desktop"},
            guacamole={"recording": {"enabled": True, "path": "/rec", "name": "", "include_keys": False, "auto_create_path": True}},
        )
        mocker.patch("broker.config.loader.BrokerConfig.settings", return_value=custom_settings)

        existing_conn = {"name": "Old Name", "protocol": "vnc"}
        existing_params = {"hostname": "10.0.0.1", "port": "5901"}

        mocker.patch("broker.domain.guacamole.requests.get", side_effect=[
            _mock_response(json_data=existing_conn),
            _mock_response(json_data=existing_params),
        ])
        mock_put = mocker.patch("broker.domain.guacamole.requests.put", return_value=_mock_response())

        result = api.sync_connection_config("42", "alice")

        assert result is True
        put_body = mock_put.call_args.kwargs.get("json") or mock_put.call_args[1].get("json")
        assert put_body["name"] == "My Desktop - alice"
        assert put_body["parameters"]["recording-path"] == "/rec"


# ---------------------------------------------------------------------------
# grant_connection_permission
# ---------------------------------------------------------------------------

class TestGrantPermission:

    def test_grant_connection_permission(self, mocker):
        """PATCH with op=add, path=/connectionPermissions/X, value=READ."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        mock_patch = mocker.patch("broker.domain.guacamole.requests.patch")
        api.grant_connection_permission("alice", "42")

        mock_patch.assert_called_once()
        perms = mock_patch.call_args.kwargs.get("json") or mock_patch.call_args[1].get("json")
        assert perms[0]["op"] == "add"
        assert perms[0]["path"] == "/connectionPermissions/42"
        assert perms[0]["value"] == "READ"


# ---------------------------------------------------------------------------
# create_home_connection
# ---------------------------------------------------------------------------

class TestCreateHomeConnection:

    def test_create_home_connection(self, mocker, mock_broker_config):
        """Creates placeholder localhost:1 with failover-only."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        # get_connections returns empty → no duplicate
        mocker.patch("broker.domain.guacamole.requests.get", return_value=_mock_response(json_data={}))
        mock_post = mocker.patch("broker.domain.guacamole.requests.post", return_value=_mock_response(
            status_code=200, json_data={"identifier": "99"}
        ))
        mock_patch = mocker.patch("broker.domain.guacamole.requests.patch")

        result = api.create_home_connection("alice")

        assert result == "99"
        post_body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert post_body["parameters"]["hostname"] == "localhost"
        assert post_body["parameters"]["port"] == "1"
        assert post_body["attributes"]["failover-only"] == "true"

    def test_create_home_connection_skips_existing(self, mocker, mock_broker_config):
        """Connection already exists → returns None."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        # get_connections returns a matching connection
        mocker.patch("broker.domain.guacamole.requests.get", return_value=_mock_response(
            json_data={"1": {"name": "Home - alice"}}
        ))
        result = api.create_home_connection("alice")
        assert result is None


# ---------------------------------------------------------------------------
# delete_connection / get_user_groups
# ---------------------------------------------------------------------------

class TestMiscMethods:

    def test_delete_connection(self, mocker):
        """DELETE correct endpoint."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        mock_delete = mocker.patch("broker.domain.guacamole.requests.delete")
        api.delete_connection("42")

        url = mock_delete.call_args[0][0]
        assert "/connections/42" in url

    def test_get_user_groups(self, mocker):
        """GET returns list of groups."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        mocker.patch("broker.domain.guacamole.requests.get", return_value=_mock_response(
            json_data=["developers", "admins"]
        ))
        groups = api.get_user_groups("alice")
        assert groups == ["developers", "admins"]


# ---------------------------------------------------------------------------
# 403 re-authentication
# ---------------------------------------------------------------------------

class TestReauthOn403:

    def test_retries_on_403_then_succeeds(self, mocker):
        """First call returns 403 → invalidate token → re-auth → retry succeeds."""
        api = _make_api()
        api.token = "stale-token"
        api.token_expires = time.time() + 3000

        resp_403 = _mock_response(status_code=403)
        resp_200 = _mock_response(json_data={"user1": {}})

        mock_get = mocker.patch(
            "broker.domain.guacamole.requests.get", side_effect=[resp_403, resp_200]
        )
        mock_post = mocker.patch(
            "broker.domain.guacamole.requests.post",
            return_value=_mock_response(
                json_data={"authToken": "fresh-token", "availableDataSources": ["postgresql"]}
            ),
        )

        users = api.get_users()

        assert users == ["user1"]
        assert api.token == "fresh-token"
        # First GET returned 403, then POST to re-auth, then second GET succeeded
        assert mock_get.call_count == 2
        mock_post.assert_called_once()

    def test_no_retry_on_non_403_error(self, mocker):
        """Non-403 error → raise immediately, no retry."""
        api = _make_api()
        api.token = "tok"
        api.token_expires = time.time() + 3000

        mocker.patch(
            "broker.domain.guacamole.requests.get",
            return_value=_mock_response(status_code=500),
        )

        with pytest.raises(requests.HTTPError):
            api.get_users()
