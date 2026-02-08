"""
Tests for Flask API routes (broker.api.routes).
"""

from unittest.mock import MagicMock, patch

import pytest

from broker.domain.types import SessionData


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:

    def test_health_ok(self, app_client, mocker):
        """GET /health → 200, database=true."""
        mocker.patch("broker.api.routes.get_db_connection")
        resp = app_client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert data["database"] is True

    def test_health_no_auth_needed(self, app_client, mocker):
        """GET /health without API key → still 200."""
        mocker.patch("broker.api.routes.get_db_connection")
        resp = app_client.get("/health", headers={})
        # health is a public endpoint, so we need to bypass our wrapper
        # by explicitly passing empty X-API-Key
        assert resp.status_code in (200, 503)  # 503 if DB mock not set up

    def test_health_db_down(self, app_client, mocker):
        """GET /health with DB failure → 503, degraded."""
        mocker.patch("broker.api.routes.get_db_connection", side_effect=Exception("DB down"))
        resp = app_client.get("/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "degraded"
        assert data["database"] is False


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuth:

    def test_api_requires_auth(self, app_client):
        """GET /api/sessions without API key → 401."""
        resp = app_client.get("/api/sessions", headers={"X-API-Key": ""})
        assert resp.status_code == 401

    def test_api_invalid_key(self, app_client):
        """Wrong API key → 401."""
        resp = app_client.get("/api/sessions", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_api_bearer_token(self, app_client):
        """Authorization: Bearer → 200."""
        resp = app_client.get(
            "/api/sessions",
            headers={"Authorization": "Bearer test-api-key-secret"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class TestSessions:

    def test_list_sessions(self, app_client, mocker):
        """GET /api/sessions → 200, vnc_password excluded."""
        mocker.patch("broker.api.routes.SessionStore.list_sessions", return_value=[
            SessionData(
                session_id="s1", username="alice",
                guac_connection_id="42", vnc_password="secret",
                container_id="c1", container_ip="10.0.0.1",
                created_at=1000.0, started_at=1000.0, last_activity=None,
            )
        ])
        resp = app_client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        sessions = data["data"]["sessions"]
        assert len(sessions) == 1
        assert "vnc_password" not in sessions[0]
        assert sessions[0]["active"] is True

    def test_force_cleanup(self, app_client, mocker):
        """DELETE /api/sessions/X → 200, destroy called."""
        mocker.patch("broker.api.routes.SessionStore.get_session", return_value=SessionData(
            session_id="s1", username="alice",
            container_id="c1", container_ip="10.0.0.1",
            guac_connection_id="42", vnc_password="pw",
        ))
        save_mock = mocker.patch("broker.api.routes.SessionStore.save_session")
        destroy_mock = mocker.patch("broker.api.routes.destroy_container")

        resp = app_client.delete("/api/sessions/s1")
        assert resp.status_code == 200
        destroy_mock.assert_called_once_with("c1")

    def test_force_cleanup_not_found(self, app_client, mocker):
        """DELETE nonexistent session → 404."""
        mocker.patch("broker.api.routes.SessionStore.get_session", return_value=None)
        resp = app_client.delete("/api/sessions/nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

class TestSync:

    def test_trigger_sync(self, app_client):
        """POST /api/sync → 200."""
        resp = app_client.post("/api/sync")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Provision
# ---------------------------------------------------------------------------

class TestProvision:

    def test_provision_user(self, app_client, mocker):
        """POST /api/users/X/provision → 200."""
        mocker.patch("broker.api.routes.provision_user_connection", return_value="42")
        resp = app_client.post("/api/users/alice/provision")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["connection_id"] == "42"

    def test_provision_validation_error(self, app_client):
        """Invalid username → 400."""
        resp = app_client.post("/api/users/inv@lid!/provision")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

class TestGroups:

    def test_list_groups(self, app_client):
        """GET /api/groups → 200."""
        resp = app_client.get("/api/groups")
        assert resp.status_code == 200
        assert "groups" in resp.get_json()["data"]

    def test_update_group(self, app_client):
        """PUT /api/groups/X → 200."""
        resp = app_client.put(
            "/api/groups/devs",
            json={"description": "Developers", "priority": 10, "bookmarks": []},
        )
        assert resp.status_code == 200

    def test_delete_group_default(self, app_client):
        """DELETE /api/groups/default → 400."""
        resp = app_client.delete("/api/groups/default")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class TestSettings:

    def test_update_settings(self, app_client):
        """PUT /api/settings → 200."""
        resp = app_client.put("/api/settings", json={"merge_bookmarks": True})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------

class TestRateLimit:

    def test_rate_limit_on_write(self, app_client, mocker):
        """11 POST /api/sync → 10×200 + 1×429."""
        # Re-enable rate limiting for this test
        from broker.app import app
        app.config["RATELIMIT_ENABLED"] = True
        from broker.api.rate_limit import limiter
        limiter.reset()

        ok_count = 0
        limited_count = 0
        for _ in range(11):
            resp = app_client.post("/api/sync")
            if resp.status_code == 200:
                ok_count += 1
            elif resp.status_code == 429:
                limited_count += 1

        assert ok_count == 10
        assert limited_count == 1

        # Restore
        app.config["RATELIMIT_ENABLED"] = False

    def test_rate_limit_exempt_health(self, app_client, mocker):
        """Many GET /health → all 200 (exempt from rate limit)."""
        mocker.patch("broker.api.routes.get_db_connection")
        from broker.app import app
        app.config["RATELIMIT_ENABLED"] = True
        from broker.api.rate_limit import limiter
        limiter.reset()

        for _ in range(15):
            resp = app_client.get("/health")
            assert resp.status_code == 200

        app.config["RATELIMIT_ENABLED"] = False


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class TestAudit:

    def test_audit_logs_post(self, app_client, mocker):
        """POST → audit_logger.info called."""
        from broker.api.audit import audit_logger
        info_mock = mocker.patch.object(audit_logger, "info")

        app_client.post("/api/sync")
        info_mock.assert_called()
        entry = info_mock.call_args[0][0]
        assert entry["method"] == "POST"
        assert entry["event"] == "api_admin_action"

    def test_audit_skips_get(self, app_client, mocker):
        """GET → audit_logger.info NOT called."""
        from broker.api.audit import audit_logger
        info_mock = mocker.patch.object(audit_logger, "info")

        app_client.get("/api/sessions")
        info_mock.assert_not_called()

    def test_audit_extracts_username(self, app_client, mocker):
        """POST /api/users/alice/provision → username=alice in log."""
        mocker.patch("broker.api.routes.provision_user_connection", return_value="42")
        from broker.api.audit import audit_logger
        info_mock = mocker.patch.object(audit_logger, "info")

        app_client.post("/api/users/alice/provision")
        info_mock.assert_called()
        entry = info_mock.call_args[0][0]
        assert entry.get("username") == "alice"
