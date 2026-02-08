"""
User provisioning and connection lifecycle management.
"""

import logging
import time
import uuid

from broker.config.settings import VNC_PORT, VNC_CONTAINER_TIMEOUT, SESSION_ID_LENGTH
from broker.config.loader import BrokerConfig
from broker.domain.session import SessionStore
from broker.domain.guacamole import guac_api
from broker.domain.user_profile import UserProfile
from broker.domain.container import (
    spawn_vnc_container,
    destroy_container,
    wait_for_vnc,
    generate_vnc_password,
    is_container_running,
    get_pool_containers,
    claim_container,
)

logger = logging.getLogger("session-broker")


def provision_user_connection(username: str) -> str:
    """
    Provision a VNC connection for a user.
    First tries to claim a container from the pool, otherwise creates a new one.

    Args:
        username: Username

    Returns:
        Guacamole connection ID
    """
    # Check for existing session with running container
    existing = SessionStore.get_session_by_username(username)
    if existing and existing.get("guac_connection_id") and existing.get("container_id"):
        return existing["guac_connection_id"]

    UserProfile.ensure_profile(username)

    # Apply group configuration
    try:
        user_groups = guac_api.get_user_groups(username)
        applied_config = UserProfile.apply_group_config(username, user_groups)
        logger.info(f"Configuration applied for {username}, groups: {applied_config.get('groups', [])}")
    except Exception as e:
        logger.warning(f"Unable to get groups for {username}: {e}")

    # Try to claim a container from the pool first
    pool_sessions = SessionStore.get_pool_sessions()

    container_id = None
    container_ip = None
    session_id = None
    vnc_password = None
    claimed_from_pool = False

    # Try to claim from pool
    for pool_session in pool_sessions:
        pool_session_id = pool_session.get("session_id")
        pool_container_id = pool_session.get("container_id")
        pool_container_ip = pool_session.get("container_ip")
        pool_vnc_password = pool_session.get("vnc_password")

        # Try to claim the container in orchestrator first (updates labels)
        if claim_container(pool_container_id, username):
            # Then claim the session in database
            if SessionStore.claim_pool_session(pool_session_id, username):
                container_id = pool_container_id
                container_ip = pool_container_ip
                session_id = pool_session_id
                vnc_password = pool_vnc_password
                claimed_from_pool = True
                logger.info(f"Claimed pool container {container_id} for {username}")
                break
            else:
                logger.warning(f"Failed to claim session {pool_session_id}, trying next")
        else:
            logger.warning(f"Failed to claim container {pool_container_id}, trying next")

    # If no pool container available, create a new one
    if not container_id:
        session_id = str(uuid.uuid4())[:SESSION_ID_LENGTH]
        vnc_password = generate_vnc_password()
        container_id, container_ip = spawn_vnc_container(session_id, username, vnc_password)
        logger.info(f"Created new container {container_id} for {username} (no pool available)")

    # Wait for VNC to be ready (pool containers should already be ready)
    if not wait_for_vnc(container_ip, port=VNC_PORT, timeout=VNC_CONTAINER_TIMEOUT):
        destroy_container(container_id)
        raise RuntimeError(f"VNC server timeout for {username}")

    # Create connection with actual container IP
    connection_name = BrokerConfig.get("containers", "connection_name", default="Virtual Desktop")
    conn_id = guac_api.create_connection(
        name=connection_name,
        hostname=container_ip,
        port=VNC_PORT,
        password=vnc_password,
        username=username
    )
    guac_api.grant_connection_permission(username, conn_id)

    # Create placeholder connection to force home page display
    force_home = BrokerConfig.get("guacamole", "force_home_page", default=True)
    if force_home:
        guac_api.create_home_connection(username)

    # Update session with guac connection ID
    # For pool sessions, this updates the existing session
    # For new sessions, this creates a new session
    SessionStore.save_session(session_id, {
        "session_id": session_id,
        "username": username,
        "guac_connection_id": conn_id,
        "vnc_password": vnc_password,
        "container_id": container_id,
        "container_ip": container_ip,
        "created_at": time.time() if not claimed_from_pool else None,  # Keep original for claimed
        "started_at": time.time()
    })

    logger.info(f"Connection provisioned for {username}: {conn_id}")
    return conn_id


def on_connection_start(connection_id: str, username: str) -> bool:
    """
    Handle connection start event.

    Args:
        connection_id: Guacamole connection ID
        username: Username

    Returns:
        True on success, False on failure
    """
    session = SessionStore.get_session_by_connection(connection_id)
    if not session:
        return False

    # Check if existing container is still running
    if session.get("container_id"):
        if is_container_running(session["container_id"]):
            logger.info(f"Reusing existing container for {username}")
            return True
        else:
            # Container no longer exists, clear session data
            logger.info(f"Previous container for {username} no longer running, spawning new one")
            session.update({"container_id": None, "container_ip": None, "started_at": None})

    try:
        container_id, container_ip = spawn_vnc_container(
            session["session_id"],
            username,
            session["vnc_password"]
        )

        if not wait_for_vnc(container_ip, port=VNC_PORT, timeout=VNC_CONTAINER_TIMEOUT):
            destroy_container(container_id)
            raise RuntimeError("VNC server timeout")

        # Update Guacamole connection with container IP
        guac_api.update_connection(
            connection_id,
            container_ip,
            VNC_PORT,
            session["vnc_password"]
        )

        session.update({
            "container_id": container_id,
            "container_ip": container_ip,
            "started_at": time.time()
        })
        SessionStore.save_session(session["session_id"], session)

        logger.info(f"Container started for {username} at {container_ip}")
        return True
    except Exception as e:
        logger.error(f"Container start error: {e}")
        return False


def on_connection_end(connection_id: str, username: str) -> None:
    """
    Handle connection end event.
    If persist_after_disconnect is True, the container is kept running.

    Args:
        connection_id: Guacamole connection ID
        username: Username
    """
    session = SessionStore.get_session_by_connection(connection_id)
    if not session:
        return

    persist_enabled = BrokerConfig.get("lifecycle", "persist_after_disconnect", default=True)
    if persist_enabled:
        # Keep container running - update last activity for timeout tracking
        session["last_activity"] = time.time()
        SessionStore.save_session(session["session_id"], session)
        logger.info(f"Connection ended for {username}, container kept running (persist mode)")
        return

    # Destroy container if persist mode is disabled
    if session.get("container_id"):
        destroy_container(session["container_id"])
        session.update({"container_id": None, "container_ip": None, "started_at": None})
        SessionStore.save_session(session["session_id"], session)
        logger.info(f"Container destroyed for {username}")
