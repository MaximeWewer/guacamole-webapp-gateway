"""
Session Broker for Guacamole VNC Container Management.

This service manages the lifecycle of VNC containers for Guacamole users:
- Automatic synchronization of Guacamole users
- Group-based configuration (bookmarks, wallpaper) stored in PostgreSQL
- Pre-provisions a "Virtual Desktop" connection for each user
- Spawns VNC container on connection start
- Destroys container on connection end
- Persists Firefox bookmarks and wallpaper between sessions
- Secret management via Vault (OpenBao/HashiCorp) or environment variables
- Session and group storage in PostgreSQL
- Network isolation via Docker networks
"""

__version__ = "1.0.0"
