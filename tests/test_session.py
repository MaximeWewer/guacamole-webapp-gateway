"""
Tests for broker.domain.session.SessionStore.
"""

import time
from datetime import datetime
from unittest.mock import MagicMock, call

import pytest

from broker.domain.session import SessionStore


# ---------------------------------------------------------------------------
# save_session
# ---------------------------------------------------------------------------

class TestSaveSession:

    def test_save_session_insert(self, mock_db):
        """Full save with all keys triggers INSERT ON CONFLICT."""
        now = time.time()
        data = {
            "username": "alice",
            "guac_connection_id": "42",
            "vnc_password": "secret",
            "container_id": "cnt-1",
            "container_ip": "172.18.0.5",
            "created_at": now,
            "started_at": now,
            "last_activity": now,
        }
        SessionStore.save_session("sess-1", data)

        mock_db.execute.assert_called_once()
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO broker_sessions" in sql
        assert "ON CONFLICT" in sql

        params = mock_db.execute.call_args[0][1]
        assert params[0] == "sess-1"
        assert params[1] == "alice"
        assert params[2] == "42"

    def test_save_session_partial_update(self, mock_db):
        """Partial save (only container_id) → COALESCE preserves other fields."""
        SessionStore.save_session("sess-1", {"container_id": "cnt-2"})

        params = mock_db.execute.call_args[0][1]
        # username should be None (not provided)
        assert params[1] is None
        # container_id should be set
        assert params[4] == "cnt-2"


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------

class TestGetSession:

    def test_get_session_found(self, mock_db):
        """get_session returns dict with timestamps converted to float."""
        now = datetime.now()
        mock_db.fetchone.return_value = {
            "session_id": "sess-1",
            "username": "alice",
            "guac_connection_id": "42",
            "vnc_password": "secret",
            "container_id": "cnt-1",
            "container_ip": "172.18.0.5",
            "created_at": now,
            "started_at": now,
            "last_activity": now,
        }
        result = SessionStore.get_session("sess-1")

        assert result is not None
        assert result.session_id == "sess-1"
        assert result.username == "alice"
        assert isinstance(result.created_at, float)
        assert isinstance(result.started_at, float)
        assert isinstance(result.last_activity, float)

    def test_get_session_not_found(self, mock_db):
        """get_session returns None when no row found."""
        mock_db.fetchone.return_value = None
        result = SessionStore.get_session("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# delete_session
# ---------------------------------------------------------------------------

class TestDeleteSession:

    def test_delete_session(self, mock_db):
        """delete_session issues DELETE SQL."""
        SessionStore.delete_session("sess-1")
        sql = mock_db.execute.call_args[0][0]
        assert "DELETE FROM broker_sessions" in sql
        params = mock_db.execute.call_args[0][1]
        assert params == ("sess-1",)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

class TestLookups:

    def test_get_session_by_username(self, mock_db):
        """Lookup by username."""
        now = datetime.now()
        mock_db.fetchone.return_value = {
            "session_id": "sess-1",
            "username": "bob",
            "guac_connection_id": "10",
            "vnc_password": "pw",
            "container_id": "cnt-2",
            "container_ip": "172.18.0.6",
            "created_at": now,
            "started_at": now,
            "last_activity": None,
        }
        result = SessionStore.get_session_by_username("bob")
        assert result is not None
        assert result.username == "bob"
        sql = mock_db.execute.call_args[0][0]
        assert "WHERE username" in sql

    def test_get_session_by_connection(self, mock_db):
        """Lookup by connection_id."""
        now = datetime.now()
        mock_db.fetchone.return_value = {
            "session_id": "sess-1",
            "username": "alice",
            "guac_connection_id": "42",
            "vnc_password": "pw",
            "container_id": "cnt-1",
            "container_ip": "172.18.0.5",
            "created_at": now,
            "started_at": now,
            "last_activity": None,
        }
        result = SessionStore.get_session_by_connection("42")
        assert result is not None
        assert result.guac_connection_id == "42"
        sql = mock_db.execute.call_args[0][0]
        assert "WHERE guac_connection_id" in sql


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

class TestListSessions:

    def test_list_sessions(self, mock_db):
        """list_sessions returns list of dicts."""
        now = datetime.now()
        mock_db.fetchall.return_value = [
            {
                "session_id": "s1", "username": "alice",
                "guac_connection_id": "1", "vnc_password": "pw",
                "container_id": "c1", "container_ip": "10.0.0.1",
                "created_at": now, "started_at": now, "last_activity": None,
            },
            {
                "session_id": "s2", "username": "bob",
                "guac_connection_id": "2", "vnc_password": "pw2",
                "container_id": "c2", "container_ip": "10.0.0.2",
                "created_at": now, "started_at": None, "last_activity": None,
            },
        ]
        result = SessionStore.list_sessions()
        assert len(result) == 2
        assert result[0].session_id == "s1"
        assert result[1].session_id == "s2"


# ---------------------------------------------------------------------------
# Pool sessions
# ---------------------------------------------------------------------------

class TestPoolSessions:

    def test_get_pool_sessions_filters_dead(self, mock_db, mocker):
        """get_pool_sessions filters out containers that are not running."""
        now = datetime.now()
        mock_db.fetchall.return_value = [
            {
                "session_id": "pool-1", "username": None,
                "guac_connection_id": None, "vnc_password": "pw",
                "container_id": "alive", "container_ip": "10.0.0.1",
                "created_at": now, "started_at": now, "last_activity": None,
            },
            {
                "session_id": "pool-2", "username": None,
                "guac_connection_id": None, "vnc_password": "pw2",
                "container_id": "dead", "container_ip": "10.0.0.2",
                "created_at": now, "started_at": now, "last_activity": None,
            },
        ]
        # alive → True, dead → False
        mocker.patch(
            "broker.domain.container.is_container_running",
            side_effect=lambda cid: cid == "alive",
        )
        result = SessionStore.get_pool_sessions()
        assert len(result) == 1
        assert result[0].container_id == "alive"


# ---------------------------------------------------------------------------
# claim_pool_session
# ---------------------------------------------------------------------------

class TestClaimPoolSession:

    def test_claim_pool_session_success(self, mock_db):
        """rowcount=1 → True (claimed successfully)."""
        mock_db.rowcount = 1
        assert SessionStore.claim_pool_session("pool-1", "alice") is True
        sql = mock_db.execute.call_args[0][0]
        assert "UPDATE broker_sessions" in sql
        assert "username IS NULL" in sql

    def test_claim_pool_session_race(self, mock_db):
        """rowcount=0 → False (already claimed by someone else)."""
        mock_db.rowcount = 0
        assert SessionStore.claim_pool_session("pool-1", "alice") is False


# ---------------------------------------------------------------------------
# get_provisioned_users
# ---------------------------------------------------------------------------

class TestGetProvisionedUsers:

    def test_get_provisioned_users(self, mock_db):
        """Returns set of usernames."""
        mock_db.fetchall.return_value = [("alice",), ("bob",)]
        result = SessionStore.get_provisioned_users()
        assert result == {"alice", "bob"}
        sql = mock_db.execute.call_args[0][0]
        assert "DISTINCT username" in sql
