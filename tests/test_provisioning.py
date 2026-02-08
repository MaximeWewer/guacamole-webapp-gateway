"""
Tests for broker.services.provisioning.
"""

import time
from unittest.mock import MagicMock, patch, call

import pytest

from broker.domain.orchestrator.base import ContainerInfo


# ---------------------------------------------------------------------------
# provision_user_connection
# ---------------------------------------------------------------------------

class TestProvisionUserConnection:

    def test_provision_new_container(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """No pool available → spawn new container → create connection → save session."""
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_username", return_value=None)
        mocker.patch("broker.services.provisioning.SessionStore.get_pool_sessions", return_value=[])
        mocker.patch("broker.services.provisioning.SessionStore.save_session")
        mocker.patch("broker.services.provisioning.UserProfile.ensure_profile")
        mocker.patch("broker.services.provisioning.UserProfile.apply_group_config", return_value={"groups": []})
        mocker.patch("broker.services.provisioning.wait_for_vnc", return_value=True)
        mocker.patch(
            "broker.services.provisioning.spawn_vnc_container",
            return_value=("cnt-new", "172.18.0.10"),
        )
        mocker.patch("broker.services.provisioning.generate_vnc_password", return_value="gen-pw")

        from broker.services.provisioning import provision_user_connection

        conn_id = provision_user_connection("alice")

        assert conn_id == "42"  # mock_guac_api.create_connection returns "42"
        mock_guac_api.create_connection.assert_called_once()
        mock_guac_api.grant_connection_permission.assert_called_once_with("alice", "42")

    def test_provision_claims_from_pool(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """Pool session available → claim container + claim_pool_session → no spawn."""
        pool_session = {
            "session_id": "pool-1",
            "container_id": "cnt-pool",
            "container_ip": "172.18.0.20",
            "vnc_password": "pool-pw",
        }
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_username", return_value=None)
        mocker.patch("broker.services.provisioning.SessionStore.get_pool_sessions", return_value=[pool_session])
        mocker.patch("broker.services.provisioning.SessionStore.claim_pool_session", return_value=True)
        mocker.patch("broker.services.provisioning.SessionStore.save_session")
        mocker.patch("broker.services.provisioning.UserProfile.ensure_profile")
        mocker.patch("broker.services.provisioning.UserProfile.apply_group_config", return_value={"groups": []})
        mocker.patch("broker.services.provisioning.wait_for_vnc", return_value=True)
        mocker.patch("broker.services.provisioning.claim_container", return_value=True)
        spawn_mock = mocker.patch("broker.services.provisioning.spawn_vnc_container")

        from broker.services.provisioning import provision_user_connection

        conn_id = provision_user_connection("alice")

        assert conn_id == "42"
        spawn_mock.assert_not_called()

    def test_provision_pool_race_fallback(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """First claim fails → retry on next pool session."""
        pool1 = {"session_id": "p1", "container_id": "c1", "container_ip": "10.0.0.1", "vnc_password": "pw1"}
        pool2 = {"session_id": "p2", "container_id": "c2", "container_ip": "10.0.0.2", "vnc_password": "pw2"}

        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_username", return_value=None)
        mocker.patch("broker.services.provisioning.SessionStore.get_pool_sessions", return_value=[pool1, pool2])
        # First claim_container fails, second succeeds
        mocker.patch("broker.services.provisioning.claim_container", side_effect=[False, True])
        mocker.patch("broker.services.provisioning.SessionStore.claim_pool_session", return_value=True)
        mocker.patch("broker.services.provisioning.SessionStore.save_session")
        mocker.patch("broker.services.provisioning.UserProfile.ensure_profile")
        mocker.patch("broker.services.provisioning.UserProfile.apply_group_config", return_value={"groups": []})
        mocker.patch("broker.services.provisioning.wait_for_vnc", return_value=True)

        from broker.services.provisioning import provision_user_connection

        conn_id = provision_user_connection("alice")
        assert conn_id == "42"

    def test_provision_vnc_timeout(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """wait_for_vnc=False → destroy container → raise RuntimeError."""
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_username", return_value=None)
        mocker.patch("broker.services.provisioning.SessionStore.get_pool_sessions", return_value=[])
        mocker.patch("broker.services.provisioning.UserProfile.ensure_profile")
        mocker.patch("broker.services.provisioning.UserProfile.apply_group_config", return_value={"groups": []})
        mocker.patch("broker.services.provisioning.wait_for_vnc", return_value=False)
        mocker.patch("broker.services.provisioning.spawn_vnc_container", return_value=("cnt-x", "10.0.0.1"))
        mocker.patch("broker.services.provisioning.generate_vnc_password", return_value="pw")
        destroy_mock = mocker.patch("broker.services.provisioning.destroy_container")

        from broker.services.provisioning import provision_user_connection

        with pytest.raises(RuntimeError, match="VNC server timeout"):
            provision_user_connection("alice")

        destroy_mock.assert_called_once_with("cnt-x")

    def test_provision_existing_session(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """Existing session with running container → return conn_id directly."""
        existing = {
            "session_id": "s1",
            "username": "alice",
            "guac_connection_id": "42",
            "container_id": "cnt-1",
            "container_ip": "10.0.0.1",
        }
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_username", return_value=existing)

        from broker.services.provisioning import provision_user_connection

        conn_id = provision_user_connection("alice")
        assert conn_id == "42"
        # Should not spawn or create a new connection
        mock_guac_api.create_connection.assert_not_called()

    def test_provision_applies_group_config(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """Verifies UserProfile.apply_group_config is called."""
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_username", return_value=None)
        mocker.patch("broker.services.provisioning.SessionStore.get_pool_sessions", return_value=[])
        mocker.patch("broker.services.provisioning.SessionStore.save_session")
        mocker.patch("broker.services.provisioning.UserProfile.ensure_profile")
        apply_mock = mocker.patch(
            "broker.services.provisioning.UserProfile.apply_group_config",
            return_value={"groups": ["developers"]},
        )
        mocker.patch("broker.services.provisioning.wait_for_vnc", return_value=True)
        mocker.patch("broker.services.provisioning.spawn_vnc_container", return_value=("c", "10.0.0.1"))
        mocker.patch("broker.services.provisioning.generate_vnc_password", return_value="pw")

        from broker.services.provisioning import provision_user_connection

        provision_user_connection("alice")
        apply_mock.assert_called_once_with("alice", ["developers"])


# ---------------------------------------------------------------------------
# on_connection_start
# ---------------------------------------------------------------------------

class TestOnConnectionStart:

    def test_on_connection_start_reuses_running(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """Container running → no spawn, return True."""
        session = {
            "session_id": "s1", "username": "alice",
            "container_id": "cnt-1", "container_ip": "10.0.0.1",
            "vnc_password": "pw", "guac_connection_id": "42",
        }
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_connection", return_value=session)
        mocker.patch("broker.services.provisioning.is_container_running", return_value=True)

        from broker.services.provisioning import on_connection_start

        assert on_connection_start("42", "alice") is True

    def test_on_connection_start_spawns_new(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """No container → spawn + update_connection."""
        session = {
            "session_id": "s1", "username": "alice",
            "container_id": None, "container_ip": None,
            "vnc_password": "pw", "guac_connection_id": "42",
        }
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_connection", return_value=session)
        mocker.patch("broker.services.provisioning.spawn_vnc_container", return_value=("cnt-new", "10.0.0.5"))
        mocker.patch("broker.services.provisioning.wait_for_vnc", return_value=True)
        mocker.patch("broker.services.provisioning.SessionStore.save_session")

        from broker.services.provisioning import on_connection_start

        assert on_connection_start("42", "alice") is True
        mock_guac_api.update_connection.assert_called_once()

    def test_on_connection_start_vnc_timeout(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """Spawn OK but VNC timeout → destroy → return False."""
        session = {
            "session_id": "s1", "username": "alice",
            "container_id": None, "container_ip": None,
            "vnc_password": "pw", "guac_connection_id": "42",
        }
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_connection", return_value=session)
        mocker.patch("broker.services.provisioning.spawn_vnc_container", return_value=("cnt-fail", "10.0.0.5"))
        mocker.patch("broker.services.provisioning.wait_for_vnc", return_value=False)
        destroy_mock = mocker.patch("broker.services.provisioning.destroy_container")

        from broker.services.provisioning import on_connection_start

        assert on_connection_start("42", "alice") is False
        destroy_mock.assert_called_once_with("cnt-fail")


# ---------------------------------------------------------------------------
# on_connection_end
# ---------------------------------------------------------------------------

class TestOnConnectionEnd:

    def test_on_connection_end_persist_mode(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """persist=True → no destroy, update last_activity."""
        session = {
            "session_id": "s1", "username": "alice",
            "container_id": "cnt-1", "container_ip": "10.0.0.1",
            "vnc_password": "pw", "guac_connection_id": "42",
        }
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_connection", return_value=session)
        save_mock = mocker.patch("broker.services.provisioning.SessionStore.save_session")
        destroy_mock = mocker.patch("broker.services.provisioning.destroy_container")
        # mock_broker_config already returns persist=True

        from broker.services.provisioning import on_connection_end

        on_connection_end("42", "alice")

        destroy_mock.assert_not_called()
        save_mock.assert_called_once()
        saved_data = save_mock.call_args[0][1]
        assert "last_activity" in saved_data
        assert saved_data["last_activity"] is not None

    def test_on_connection_end_destroy_mode(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """persist=False → destroy container, clear container_id."""
        session = {
            "session_id": "s1", "username": "alice",
            "container_id": "cnt-1", "container_ip": "10.0.0.1",
            "vnc_password": "pw", "guac_connection_id": "42",
        }
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_connection", return_value=session)
        save_mock = mocker.patch("broker.services.provisioning.SessionStore.save_session")
        destroy_mock = mocker.patch("broker.services.provisioning.destroy_container")

        # Override persist config
        mocker.patch(
            "broker.services.provisioning.BrokerConfig.get",
            side_effect=lambda *keys, default=None: False
            if keys == ("lifecycle", "persist_after_disconnect")
            else mock_broker_config(*keys, default=default),
        )

        from broker.services.provisioning import on_connection_end

        on_connection_end("42", "alice")

        destroy_mock.assert_called_once_with("cnt-1")
        saved_data = save_mock.call_args[0][1]
        assert saved_data["container_id"] is None

    def test_on_connection_end_no_session(
        self, mocker, mock_db, mock_guac_api, mock_orchestrator, mock_broker_config
    ):
        """Session not found → no-op."""
        mocker.patch("broker.services.provisioning.SessionStore.get_session_by_connection", return_value=None)
        destroy_mock = mocker.patch("broker.services.provisioning.destroy_container")

        from broker.services.provisioning import on_connection_end

        on_connection_end("999", "alice")
        destroy_mock.assert_not_called()
