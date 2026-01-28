"""
Session management for the Session Broker.
"""

from psycopg2.extras import RealDictCursor

from broker.persistence.database import get_db_connection


class SessionStore:
    """Manages session data in PostgreSQL."""

    @staticmethod
    def save_session(session_id: str, data: dict) -> None:
        """
        Save or update a session.

        Args:
            session_id: Session identifier
            data: Session data dictionary
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO broker_sessions
                    (session_id, username, guac_connection_id, vnc_password, container_id, container_ip, created_at, started_at, last_activity, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), to_timestamp(%s), CURRENT_TIMESTAMP)
                    ON CONFLICT (session_id) DO UPDATE SET
                        guac_connection_id = EXCLUDED.guac_connection_id,
                        vnc_password = EXCLUDED.vnc_password,
                        container_id = EXCLUDED.container_id,
                        container_ip = EXCLUDED.container_ip,
                        started_at = EXCLUDED.started_at,
                        last_activity = EXCLUDED.last_activity,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    session_id,
                    data.get("username"),
                    data.get("guac_connection_id"),
                    data.get("vnc_password"),
                    data.get("container_id"),
                    data.get("container_ip"),
                    data.get("created_at"),
                    data.get("started_at"),
                    data.get("last_activity")
                ))

    @staticmethod
    def _row_to_dict(row: dict) -> dict | None:
        """Convert database row to session dictionary."""
        if not row:
            return None
        return {
            "session_id": row["session_id"],
            "username": row["username"],
            "guac_connection_id": row["guac_connection_id"],
            "vnc_password": row["vnc_password"],
            "container_id": row["container_id"],
            "container_ip": row["container_ip"],
            "created_at": row["created_at"].timestamp() if row["created_at"] else None,
            "started_at": row["started_at"].timestamp() if row["started_at"] else None,
            "last_activity": row["last_activity"].timestamp() if row.get("last_activity") else None
        }

    @staticmethod
    def get_session(session_id: str) -> dict | None:
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
    def get_session_by_connection(connection_id: str) -> dict | None:
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
    def get_session_by_username(username: str) -> dict | None:
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
    def list_sessions() -> list:
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
    def get_sessions_needing_containers() -> list:
        """
        Get sessions that need a container (no container_id or container not running).
        Used for pre-warming containers.

        Returns:
            List of session dictionaries needing containers
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
        result = []
        for session in sessions:
            container_id = session.get("container_id")
            if not container_id:
                result.append(session)
            elif not is_container_running(container_id):
                # Container was removed, clear the stale ID
                session["container_id"] = None
                session["container_ip"] = None
                result.append(session)
        return result
