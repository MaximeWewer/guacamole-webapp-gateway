"""
Tests for broker.domain.container (facade functions).
"""

import socket
from unittest.mock import MagicMock, patch

import pytest

from broker.domain.orchestrator.base import ContainerInfo


# ---------------------------------------------------------------------------
# generate_vnc_password
# ---------------------------------------------------------------------------

class TestGenerateVncPassword:

    def test_generate_vnc_password(self):
        """Returns a non-empty string."""
        from broker.domain.container import generate_vnc_password
        pw = generate_vnc_password()
        assert isinstance(pw, str)
        assert len(pw) > 0

    def test_generate_vnc_password_unique(self):
        """50 generated passwords are all different."""
        from broker.domain.container import generate_vnc_password
        passwords = {generate_vnc_password() for _ in range(50)}
        assert len(passwords) == 50


# ---------------------------------------------------------------------------
# wait_for_vnc
# ---------------------------------------------------------------------------

class TestWaitForVnc:

    def test_wait_for_vnc_success(self, mocker):
        """Socket connect immediate → True."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock()
        mock_conn.__exit__ = MagicMock(return_value=False)
        mocker.patch("broker.domain.container.socket.create_connection", return_value=mock_conn)

        from broker.domain.container import wait_for_vnc
        assert wait_for_vnc("10.0.0.1", timeout=5) is True

    def test_wait_for_vnc_retry_then_success(self, mocker):
        """2 failures then success → True."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock()
        mock_conn.__exit__ = MagicMock(return_value=False)
        mocker.patch(
            "broker.domain.container.socket.create_connection",
            side_effect=[ConnectionRefusedError, ConnectionRefusedError, mock_conn],
        )
        mocker.patch("broker.domain.container.time.sleep")
        mocker.patch("broker.domain.container.time.time", side_effect=[0, 0.5, 1.0, 1.5])

        from broker.domain.container import wait_for_vnc
        assert wait_for_vnc("10.0.0.1", timeout=30) is True

    def test_wait_for_vnc_timeout(self, mocker):
        """Always ConnectionRefused → False."""
        mocker.patch(
            "broker.domain.container.socket.create_connection",
            side_effect=ConnectionRefusedError,
        )
        mocker.patch("broker.domain.container.time.sleep")
        # Simulate time progression past timeout
        times = [0] + [i * 5.0 for i in range(1, 20)]
        mocker.patch("broker.domain.container.time.time", side_effect=times)

        from broker.domain.container import wait_for_vnc
        assert wait_for_vnc("10.0.0.1", timeout=10) is False


# ---------------------------------------------------------------------------
# Facade delegation to orchestrator
# ---------------------------------------------------------------------------

class TestFacadeDelegation:

    def test_spawn_delegates_to_orchestrator(self, mock_orchestrator):
        """spawn_vnc_container calls orchestrator.spawn_container."""
        from broker.domain.container import spawn_vnc_container
        cid, cip = spawn_vnc_container("sess-1", "alice", "pw")
        assert cid == "cnt-abc123"
        assert cip == "172.18.0.5"
        mock_orchestrator.spawn_container.assert_called_once_with("sess-1", "alice", "pw")

    def test_destroy_delegates_to_orchestrator(self, mock_orchestrator):
        """destroy_container calls orchestrator.destroy_container."""
        from broker.domain.container import destroy_container
        destroy_container("cnt-abc123")
        mock_orchestrator.destroy_container.assert_called_once_with("cnt-abc123")

    def test_is_running_delegates(self, mock_orchestrator):
        """is_container_running calls orchestrator.is_container_running."""
        from broker.domain.container import is_container_running
        assert is_container_running("cnt-abc123") is True
        mock_orchestrator.is_container_running.assert_called_once_with("cnt-abc123")

    def test_claim_delegates(self, mock_orchestrator):
        """claim_container calls orchestrator.claim_container."""
        from broker.domain.container import claim_container
        assert claim_container("cnt-abc123", "alice") is True
        mock_orchestrator.claim_container.assert_called_once_with("cnt-abc123", "alice")
