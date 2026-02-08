"""
User profile management for browser policies (Firefox & Chromium).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from broker.config.settings import get_env
from broker.config.loader import BrokerConfig, ProfilesConfig
from broker.api.validators import sanitize_for_path

logger = logging.getLogger("session-broker")

# User data paths
USER_DATA_PATH = Path(get_env("user_data_path", "/data/users") or "/data/users")
USER_DATA_PATH.mkdir(parents=True, exist_ok=True)


class UserProfile:
    """Manages user profile data (browser bookmarks, autofill, etc.)."""

    @staticmethod
    def get_user_path(username: str) -> Path:
        """
        Get the path to user's profile directory.

        Args:
            username: Username (will be sanitized)

        Returns:
            Path to user directory
        """
        safe_username = sanitize_for_path(username)
        return USER_DATA_PATH / safe_username

    @staticmethod
    def ensure_profile(username: str) -> Path:
        """
        Ensure user profile directories exist.

        Args:
            username: Username

        Returns:
            Path to user directory
        """
        user_path = UserProfile.get_user_path(username)
        browser_type = BrokerConfig.get_browser_type()

        # Create common directories
        (user_path / "desktop").mkdir(parents=True, exist_ok=True)

        # Create browser-specific directories
        if browser_type == "firefox":
            (user_path / "firefox-policies").mkdir(parents=True, exist_ok=True)
        else:
            (user_path / "chromium-policies" / "managed").mkdir(parents=True, exist_ok=True)

        return user_path

    @staticmethod
    def get_config(username: str) -> dict:
        """
        Get user's configuration from profiles.yml based on group membership.

        Args:
            username: Username

        Returns:
            Configuration dictionary with homepage, bookmarks, autofill, etc.
        """
        from broker.container import get_services

        config: dict[str, Any] = {
            "homepage": "about:blank",
            "bookmarks": [],
            "autofill": []
        }

        try:
            user_groups = get_services().guac_api.get_user_groups(username)
            yaml_config = ProfilesConfig.get_user_config(user_groups)
            config.update(yaml_config)
        except Exception as e:
            logger.warning(f"Error getting config for {username}: {e}")
            default_config = ProfilesConfig.get_user_config(["default"])
            config.update(default_config)
        return config

    @staticmethod
    def get_volume_mounts(username: str) -> dict:
        """
        Get Docker volume mount configuration for user.

        Args:
            username: Username

        Returns:
            Volume mounts dictionary
        """
        user_path = UserProfile.ensure_profile(username)
        browser_type = BrokerConfig.get_browser_type()

        mounts = {
            str(user_path / "desktop"): {"bind": "/headless/Desktop", "mode": "rw"},
        }

        # Add browser-specific policy mounts
        if browser_type == "firefox":
            policies_dir = user_path / "firefox-policies"
            if policies_dir.exists():
                mounts[str(policies_dir)] = {"bind": "/etc/firefox/policies", "mode": "ro"}
        else:
            policies_dir = user_path / "chromium-policies"
            if policies_dir.exists():
                mounts[str(policies_dir)] = {"bind": "/etc/chromium/policies", "mode": "ro"}

        return mounts

    @staticmethod
    def _expand_autofill_variables(autofill: list, username: str) -> list:
        """
        Expand variables in autofill credentials.

        Supported variables:
            ${GUAC_USERNAME} - The Guacamole username
            ${vault:key} - Secret from Vault
            ${env:VAR} - Environment variable
        """
        from broker.config.secrets import secrets_provider

        vault_pattern = re.compile(r'\$\{vault:([^}]+)\}')
        env_pattern = re.compile(r'\$\{env:([^}]+)\}')

        def expand_value(value: str) -> str:
            if not isinstance(value, str):
                return value

            value = value.replace("${GUAC_USERNAME}", username)

            for match in vault_pattern.finditer(value):
                secret_key = match.group(1)
                secret_value = secrets_provider.get(secret_key, "")
                if secret_value:
                    value = value.replace(match.group(0), secret_value)
                else:
                    logger.warning(f"Vault secret not found: {secret_key}")
                    value = value.replace(match.group(0), "")

            for match in env_pattern.finditer(value):
                env_var = match.group(1)
                env_value = os.environ.get(env_var, "")
                value = value.replace(match.group(0), env_value)

            return value

        expanded = []
        for entry in autofill:
            new_entry = {key: expand_value(value) for key, value in entry.items()}
            expanded.append(new_entry)
        return expanded

    @staticmethod
    def add_bookmark(username: str, name: str, url: str) -> None:
        """Add a single bookmark for a user by re-applying browser policies."""
        raw_config = ProfilesConfig.get_user_config([])  # Will get defaults
        raw_bookmarks = raw_config.get("bookmarks", [])
        bookmarks: list[Any] = list(raw_bookmarks) if isinstance(raw_bookmarks, list) else []
        bookmarks.append({"name": name, "url": url})
        homepage = str(raw_config.get("homepage", ""))
        UserProfile.set_browser_policies(username, bookmarks, homepage)

    @staticmethod
    def _set_firefox_policies(username: str, bookmarks: list, homepage: str, autofill: list) -> None:
        """Generate Firefox enterprise policies."""
        user_path = UserProfile.get_user_path(username)
        policies_dir = user_path / "firefox-policies"
        policies_dir.mkdir(parents=True, exist_ok=True)

        managed_bookmarks = [
            {"name": bm["name"], "url": bm["url"]}
            for bm in bookmarks if "name" in bm and "url" in bm
        ]

        policies = {
            "policies": {
                "DisableAppUpdate": True,
                "DisableFirefoxStudies": True,
                "DisablePocket": True,
                "DisableTelemetry": True,
                "DontCheckDefaultBrowser": True,
                "NoDefaultBookmarks": True,
                "OverrideFirstRunPage": "",
                "OverridePostUpdatePage": "",
                "DisplayBookmarksToolbar": "always",
                "PasswordManagerEnabled": True,
                "UserMessaging": {
                    "WhatsNew": False,
                    "ExtensionRecommendations": False,
                    "FeatureRecommendations": False,
                    "UrlbarInterventions": False,
                    "SkipOnboarding": True,
                    "MoreFromMozilla": False
                },
                "Preferences": {
                    "browser.startup.homepage_override.mstone": {"Value": "ignore", "Status": "locked"},
                    "datareporting.policy.dataSubmissionEnabled": {"Value": False, "Status": "locked"},
                    "toolkit.telemetry.reportingpolicy.firstRun": {"Value": False, "Status": "locked"},
                    "signon.rememberSignons": {"Value": True, "Status": "default"},
                    "signon.autofillForms": {"Value": True, "Status": "default"}
                }
            }
        }

        if managed_bookmarks:
            policies["policies"]["ManagedBookmarks"] = [
                {"toplevel_name": "Bookmarks"}
            ] + managed_bookmarks

        policies["policies"]["Homepage"] = {
            "URL": homepage if homepage else "about:blank",
            "StartPage": "homepage"
        }

        if autofill:
            expanded = UserProfile._expand_autofill_variables(autofill, username)
            logins = []
            for entry in expanded:
                if "url" in entry and "username" in entry:
                    login = {"origin": entry["url"], "username": entry["username"]}
                    if entry.get("password"):
                        login["password"] = entry["password"]
                    logins.append(login)

            if logins:
                policies["policies"]["PrimaryPassword"] = False
                policies["policies"]["OfferToSaveLogins"] = False
                policies["policies"]["Logins"] = logins

        (policies_dir / "policies.json").write_text(json.dumps(policies, indent=2))

    @staticmethod
    def _set_chromium_policies(username: str, bookmarks: list, homepage: str, autofill: list) -> None:
        """Generate Chromium enterprise policies."""
        user_path = UserProfile.get_user_path(username)
        policies_dir = user_path / "chromium-policies" / "managed"
        policies_dir.mkdir(parents=True, exist_ok=True)

        # Build managed bookmarks for Chromium format
        managed_bookmarks = []
        for i, bm in enumerate(bookmarks):
            if "name" in bm and "url" in bm:
                managed_bookmarks.append({
                    "name": bm["name"],
                    "url": bm["url"]
                })

        policies: dict[str, Any] = {
            # Disable telemetry and updates
            "MetricsReportingEnabled": False,
            "SafeBrowsingProtectionLevel": 1,
            "DefaultBrowserSettingEnabled": False,
            "BrowserSignin": 0,
            "SyncDisabled": True,
            "PasswordManagerEnabled": True,
            "AutofillAddressEnabled": True,
            "AutofillCreditCardEnabled": False,

            # Bookmarks bar
            "BookmarkBarEnabled": True,
            "ShowHomeButton": True,

            # First run
            "PromotionalTabsEnabled": False,
            "ShowAppsShortcutInBookmarkBar": False
        }

        # Set homepage
        if homepage:
            policies["HomepageLocation"] = homepage
            policies["HomepageIsNewTabPage"] = False
            policies["RestoreOnStartup"] = 4  # Open URLs
            policies["RestoreOnStartupURLs"] = [homepage]
        else:
            policies["HomepageIsNewTabPage"] = True
            policies["RestoreOnStartup"] = 5  # New tab page

        # Add managed bookmarks
        if managed_bookmarks:
            policies["ManagedBookmarks"] = [
                {"toplevel_name": "Bookmarks"},
                *managed_bookmarks
            ]

        # Autofill credentials (Chromium doesn't support pre-populated passwords via policy)
        # But we can configure password manager settings
        if autofill:
            expanded = UserProfile._expand_autofill_variables(autofill, username)
            # Log a warning since Chromium doesn't support pre-filled passwords
            if any(entry.get("password") for entry in expanded):
                logger.warning(
                    f"Chromium does not support pre-filled passwords via policy. "
                    f"Autofill entries for {username} will only configure the password manager."
                )
            policies["PasswordManagerEnabled"] = True

        (policies_dir / "bookmarks.json").write_text(json.dumps(policies, indent=2))

    @staticmethod
    def set_browser_policies(username: str, bookmarks: list, homepage: str = "", autofill: list[Any] | None = None) -> None:
        """
        Set browser policies based on configured browser type.

        Args:
            username: Username
            bookmarks: List of bookmark dictionaries
            homepage: Homepage URL
            autofill: List of autofill entries
        """
        browser_type = BrokerConfig.get_browser_type()
        autofill = autofill or []

        if browser_type == "firefox":
            UserProfile._set_firefox_policies(username, bookmarks, homepage, autofill)
        else:
            UserProfile._set_chromium_policies(username, bookmarks, homepage, autofill)

    @staticmethod
    def apply_profile_config(username: str, user_groups: list) -> dict:
        """
        Apply profile configuration to user based on their groups.

        Args:
            username: Username
            user_groups: List of group names

        Returns:
            Applied configuration summary
        """
        config = ProfilesConfig.get_user_config(user_groups)
        browser_type = BrokerConfig.get_browser_type()

        raw_bookmarks = config.get("bookmarks", [])
        bookmarks: list[Any] = raw_bookmarks if isinstance(raw_bookmarks, list) else []
        homepage: str = str(config.get("homepage", ""))
        raw_autofill = config.get("autofill", [])
        autofill: list[Any] = raw_autofill if isinstance(raw_autofill, list) else []

        UserProfile.set_browser_policies(username, bookmarks, homepage, autofill)

        log_parts = [f"browser={browser_type}"]
        if bookmarks:
            log_parts.append(f"{len(bookmarks)} bookmarks")
        if homepage:
            log_parts.append(f"homepage={homepage}")
        if autofill:
            log_parts.append(f"{len(autofill)} autofill")

        logger.info(f"Profile applied for {username}: {', '.join(log_parts)}")

        return {
            "groups": user_groups,
            "browser": browser_type,
            "bookmarks": len(bookmarks),
            "homepage": homepage,
            "autofill_entries": len(autofill),
        }

    # Backward compatibility aliases
    @staticmethod
    def set_firefox_policies(username: str, bookmarks: list, homepage: str = "", autofill: list[Any] | None = None) -> None:
        """Deprecated: Use set_browser_policies instead."""
        UserProfile.set_browser_policies(username, bookmarks, homepage, autofill)

    @staticmethod
    def apply_group_config(username: str, user_groups: list) -> dict:
        """Deprecated: Use apply_profile_config instead."""
        return UserProfile.apply_profile_config(username, user_groups)
