"""Tests for the database connection pool."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

import broker.persistence.database as db_mod


@pytest.fixture(autouse=True)
def _reset_pool():
    """Ensure each test starts with no pool and restores state afterward."""
    original = db_mod._pool
    db_mod._pool = None
    yield
    db_mod._pool = original


class TestInitPool:
    def test_creates_pool(self, mocker):
        mock_pool_cls = mocker.patch(
            "broker.persistence.database.ThreadedConnectionPool",
            return_value=MagicMock(),
        )
        db_mod.init_pool()
        mock_pool_cls.assert_called_once()
        assert db_mod._pool is not None

    def test_is_idempotent(self, mocker):
        mock_pool_cls = mocker.patch(
            "broker.persistence.database.ThreadedConnectionPool",
            return_value=MagicMock(),
        )
        db_mod.init_pool()
        db_mod.init_pool()
        mock_pool_cls.assert_called_once()


class TestClosePool:
    def test_closes_pool(self, mocker):
        mock_pool = MagicMock()
        db_mod._pool = mock_pool
        db_mod.close_pool()
        mock_pool.closeall.assert_called_once()
        assert db_mod._pool is None

    def test_is_idempotent(self):
        db_mod._pool = None
        db_mod.close_pool()  # should not raise
        db_mod.close_pool()


class TestGetPoolStats:
    def test_returns_zeros_when_no_pool(self):
        assert db_mod.get_pool_stats() == {"pool_size": 0, "pool_used": 0}

    def test_returns_stats_from_pool(self):
        mock_pool = MagicMock()
        mock_pool._used = {"conn1": True, "conn2": True}
        mock_pool._pool = ["idle1"]
        db_mod._pool = mock_pool
        stats = db_mod.get_pool_stats()
        assert stats == {"pool_size": 3, "pool_used": 2}


class TestGetDbConnection:
    def test_raises_without_pool(self):
        with pytest.raises(RuntimeError, match="pool not initialized"):
            with db_mod.get_db_connection():
                pass

    def test_connection_returned_to_pool(self):
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        db_mod._pool = mock_pool

        with db_mod.get_db_connection() as conn:
            assert conn is mock_conn

        mock_conn.commit.assert_called_once()
        mock_pool.putconn.assert_called_once_with(mock_conn)

    def test_connection_returned_on_exception(self):
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        db_mod._pool = mock_pool

        with pytest.raises(ValueError):
            with db_mod.get_db_connection():
                raise ValueError("boom")

        mock_conn.rollback.assert_called_once()
        mock_pool.putconn.assert_called_once_with(mock_conn)
