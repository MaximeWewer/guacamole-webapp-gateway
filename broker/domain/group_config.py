"""
Group configuration management stored in PostgreSQL.
Legacy module - YAML configuration is preferred.
"""

import logging

from psycopg2.extras import RealDictCursor

from broker.persistence.database import get_db_connection

logger = logging.getLogger("session-broker")


class GroupConfig:
    """Manages group configuration stored in PostgreSQL."""

    @staticmethod
    def get_setting(key: str, default: str = None) -> str:
        """
        Get a broker setting.

        Args:
            key: Setting key
            default: Default value

        Returns:
            Setting value
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM broker_settings WHERE key = %s", (key,))
                row = cur.fetchone()
                return row[0] if row else default

    @staticmethod
    def set_setting(key: str, value: str) -> None:
        """
        Set a broker setting.

        Args:
            key: Setting key
            value: Setting value
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO broker_settings (key, value, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (key, value))

    @staticmethod
    def get_group_config(group_name: str) -> dict | None:
        """
        Get configuration for a specific group.

        Args:
            group_name: Group name

        Returns:
            Group configuration or None if not found
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM broker_groups WHERE group_name = %s", (group_name,))
                group = cur.fetchone()
                if not group:
                    return None

                cur.execute(
                    "SELECT name, url FROM broker_bookmarks WHERE group_name = %s ORDER BY position",
                    (group_name,)
                )
                bookmarks = [{"name": r["name"], "url": r["url"]} for r in cur.fetchall()]

                return {
                    "description": group["description"],
                    "priority": group["priority"],
                    "homepage": group.get("homepage", ""),
                    "bookmarks": bookmarks
                }

    @staticmethod
    def get_user_config(user_groups: list) -> dict:
        """
        Determine effective configuration for a user based on their groups.

        Args:
            user_groups: List of group names the user belongs to

        Returns:
            Effective configuration dictionary
        """
        merge_bookmarks = GroupConfig.get_setting("merge_bookmarks", "true") == "true"
        inherit_default = GroupConfig.get_setting("inherit_from_default", "true") == "true"

        user_group_configs = []
        for group_name in user_groups:
            cfg = GroupConfig.get_group_config(group_name)
            if cfg:
                cfg["_name"] = group_name
                user_group_configs.append(cfg)

        # Add default group if inheritance is enabled
        if inherit_default and "default" not in user_groups:
            default_cfg = GroupConfig.get_group_config("default")
            if default_cfg:
                default_cfg["_name"] = "default"
                user_group_configs.append(default_cfg)

        if not user_group_configs:
            return {"bookmarks": [], "groups": []}

        # Sort by priority (highest first)
        user_group_configs.sort(key=lambda x: x.get("priority", 0), reverse=True)

        # Merge or use highest priority bookmarks
        if merge_bookmarks:
            seen_urls = set()
            bookmarks = []
            for cfg in user_group_configs:
                for bm in cfg.get("bookmarks", []):
                    if bm.get("url") not in seen_urls:
                        bookmarks.append(bm)
                        seen_urls.add(bm.get("url"))
        else:
            bookmarks = user_group_configs[0].get("bookmarks", [])

        return {
            "bookmarks": bookmarks,
            "groups": [cfg["_name"] for cfg in user_group_configs]
        }

    @staticmethod
    def get_all_groups() -> dict:
        """
        Get all group configurations.

        Returns:
            Dictionary of group name to configuration
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT group_name FROM broker_groups ORDER BY priority DESC")
                groups = {}
                for row in cur.fetchall():
                    cfg = GroupConfig.get_group_config(row["group_name"])
                    if cfg:
                        groups[row["group_name"]] = cfg
                return groups

    @staticmethod
    def create_or_update_group(group_name: str, config: dict) -> bool:
        """
        Create or update a group configuration.

        Args:
            group_name: Group name
            config: Configuration dictionary

        Returns:
            True on success
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO broker_groups (group_name, description, priority, homepage, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (group_name) DO UPDATE SET
                        description = EXCLUDED.description,
                        priority = EXCLUDED.priority,
                        homepage = EXCLUDED.homepage,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    group_name,
                    config.get("description", ""),
                    config.get("priority", 0),
                    config.get("homepage", "")
                ))

                # Update bookmarks
                cur.execute("DELETE FROM broker_bookmarks WHERE group_name = %s", (group_name,))
                for i, bm in enumerate(config.get("bookmarks", [])):
                    cur.execute("""
                        INSERT INTO broker_bookmarks (group_name, name, url, position)
                        VALUES (%s, %s, %s, %s)
                    """, (group_name, bm.get("name"), bm.get("url"), i))

        logger.info(f"Group '{group_name}' updated")
        return True

    @staticmethod
    def delete_group(group_name: str) -> bool:
        """
        Delete a group.

        Args:
            group_name: Group name

        Returns:
            True if deleted, False if not found or is default
        """
        if group_name == "default":
            return False

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM broker_groups WHERE group_name = %s", (group_name,))
                if cur.rowcount > 0:
                    logger.info(f"Group '{group_name}' deleted")
                    return True
        return False


# Global instance
group_config = GroupConfig()
