"""
Session management for the Session Broker.
"""

from __future__ import annotations

from typing import Any

from psycopg2.extras import RealDictCursor

from broker.domain.types import SessionData
from broker.persistence.database import get_db_connection


class SessionStore:
    """Manages session data in PostgreSQL."""

    @staticmethod
    def save_session(session_id: str, data: SessionData | dict[str, Any]) -> None:
        """
        Save or update a session.

        Args:
            session_id: Session identifier
            data: Session data (SessionData or dict)
        """
        d = data.to_dict() if isinstance(data, SessionData) else data
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO broker_sessions
                    (session_id, username, guac_connection_id, vnc_password, container_id, container_ip, created_at, started_at, last_activity, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), to_timestamp(%s), CURRENT_TIMESTAMP)
                    ON CONFLICT (session_id) DO UPDATE SET
                        username = COALESCE(EXCLUDED.username, broker_sessions.username),
                        guac_connection_id = COALESCE(EXCLUDED.guac_connection_id, broker_sessions.guac_connection_id),
                        vnc_password = COALESCE(EXCLUDED.vnc_password, broker_sessions.vnc_password),
                        container_id = COALESCE(EXCLUDED.container_id, broker_sessions.container_id),
                        container_ip = COALESCE(EXCLUDED.container_ip, broker_sessions.container_ip),
                        started_at = COALESCE(EXCLUDED.started_at, broker_sessions.started_at),
                        last_activity = COALESCE(EXCLUDED.last_activity, broker_sessions.last_activity),
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    session_id,
                    d.get("username"),
                    d.get("guac_connection_id"),
                    d.get("vnc_password"),
                    d.get("container_id"),
                    d.get("container_ip"),
                    d.get("created_at"),
                    d.get("started_at"),
                    d.get("last_activity")
                ))

    @staticmethod
    def _row_to_dict(row: dict[str, Any] | None) -> SessionData | None:
        """Convert database row to SessionData."""
        if not row:
            return None
        return SessionData(
            session_id=row["session_id"],
            username=row["username"],
            guac_connection_id=row["guac_connection_id"],
            vnc_password=row["vnc_password"],
            container_id=row["container_id"],
            container_ip=row["container_ip"],
            created_at=row["created_at"].timestamp() if row["created_at"] else None,
            started_at=row["started_at"].timestamp() if row["started_at"] else None,
            last_activity=row["last_activity"].timestamp() if row.get("last_activity") else None,
        )

    @staticmethod
    def get_session(session_id: str) -> SessionData | None:
        """
        Get session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session data or None
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM broker_sessions WHERE session_id = %s", (session_id,))
                return SessionStore._row_to_dict(cur.fetchone())

    @staticmethod
    def delete_session(session_id: str) -> None:
        """
        Delete a session.

        Args:
            session_id: Session identifier
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM broker_sessions WHERE session_id = %s", (session_id,))

    @staticmethod
    def get_session_by_connection(connection_id: str) -> SessionData | None:
        """
        Get session by Guacamole connection ID.

        Args:
            connection_id: Guacamole connection identifier

        Returns:
            Session data or None
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM broker_sessions WHERE guac_connection_id = %s", (connection_id,))
                return SessionStore._row_to_dict(cur.fetchone())

    @staticmethod
    def get_session_by_username(username: str) -> SessionData | None:
        """
        Get session by username.

        Args:
            username: Username

        Returns:
            Session data or None
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM broker_sessions WHERE username = %s", (username,))
                return SessionStore._row_to_dict(cur.fetchone())

    @staticmethod
    def list_sessions() -> list[SessionData | None]:
        """
        List all sessions.

        Returns:
            List of session dictionaries
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM broker_sessions ORDER BY created_at DESC")
                return [SessionStore._row_to_dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_provisioned_users() -> set:
        """
        Get set of usernames with provisioned sessions.

        Returns:
            Set of usernames
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT username FROM broker_sessions WHERE username IS NOT NULL")
                return {row[0] for row in cur.fetchall()}

    @staticmethod
    def get_sessions_needing_containers() -> list[SessionData]:
        """
        Get sessions that need a container (no container_id or container not running).
        Used for pre-warming containers.

        Returns:
            List of SessionData needing containers
        """
        # Import here to avoid circular imports
        from broker.domain.container import is_container_running

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM broker_sessions
                    WHERE guac_connection_id IS NOT NULL
                    ORDER BY created_at DESC
                """)
                sessions = [SessionStore._row_to_dict(row) for row in cur.fetchall()]

        # Filter to sessions without running containers
        result: list[SessionData] = []
        for session in sessions:
            if session is None:
                continue
            if not session.container_id:
                result.append(session)
            elif not is_container_running(session.container_id):
                # Container was removed, clear the stale ID
                session.container_id = None
                session.container_ip = None
                result.append(session)
        return result

    @staticmethod
    def get_pool_sessions() -> list[SessionData]:
        """
        Get pool sessions (sessions without username, with running container).
        These are pre-warmed containers ready to be claimed.

        Returns:
            List of pool SessionData
        """
        # Import here to avoid circular imports
        from broker.domain.container import is_container_running

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM broker_sessions
                    WHERE username IS NULL
                    AND container_id IS NOT NULL
                    ORDER BY created_at ASC
                """)
                sessions = [SessionStore._row_to_dict(row) for row in cur.fetchall()]

        # Filter to sessions with running containers
        result: list[SessionData] = []
        for session in sessions:
            if session is None:
                continue
            if session.container_id and is_container_running(session.container_id):
                result.append(session)
        return result

    @staticmethod
    def claim_pool_session(session_id: str, username: str) -> bool:
        """
        Claim a pool session for a specific user.

        Args:
            session_id: Pool session ID to claim
            username: Username to assign

        Returns:
            True if claimed successfully, False otherwise
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE broker_sessions
                    SET username = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = %s AND username IS NULL
                """, (username, session_id))
                return bool(cur.rowcount > 0)
