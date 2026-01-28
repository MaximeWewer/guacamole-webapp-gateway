# Guacamole WebApp Gateway

Extend Apache Guacamole with web application support. This project adds a **Session Broker** that provisions isolated browser containers (Firefox/Chromium) per user, enabling secure access to internal web applications through Guacamole's clientless remote desktop interface.

**Turn Guacamole into a web application gateway** - users connect via their browser to access corporate webapps in isolated, pre-configured environments with managed bookmarks, secret autofill, and session recording.

## Overview

Traditional Guacamole provides RDP/VNC/SSH access to full desktops and servers. This project adds a new use case: **web application access** through lightweight browser containers.

When a user logs in, the broker automatically provisions a dedicated VNC container running only a web browser. The browser is pre-configured with:

- **Managed bookmarks** pointing to internal web applications
- **Homepage** set to the primary webapp
- **Credential autofill** for login pages (with Vault integration)
- **Enterprise browser policies** (no downloads, restricted settings, etc.)

### Use cases

- **Internal webapp access** - Provide browser-based access to intranet applications
- **Contractor/vendor access** - Secure, isolated browsing without VPN or device enrollment
- **BYOD environments** - Access corporate webapps from any device with a browser
- **Compliance & audit** - Session recording for regulated environments
- **Kiosk mode** - Locked-down browser access to specific applications

### Key features

- **Web application gateway** - Access internal webapps through Guacamole's interface
- **Isolated browser containers** - Each user gets a dedicated Firefox/Chromium instance
- **Group-based profiles** - Bookmarks, homepage, and autofill from Guacamole user groups
- **Credential autofill** - Pre-fill login forms with Vault-stored secrets
- **Session recording** - Record browser sessions for audit/compliance (Guacamole 1.5+)
- **Container pre-warming** - Pool of ready containers for instant connections
- **Auto-provisioning** - Containers created/destroyed based on user activity
- **Enterprise policies** - Firefox/Chromium managed policies for lockdown

## Architecture

```
                    +------------------+
                    |      nginx       |  :443 (HTTPS)
                    | (reverse proxy)  |
                    +--------+---------+
                             |
          +------------------+------------------+
          |                                     |
          v                                     v
+-------------------+               +---------------------+
|    Guacamole      |               |   Session Broker    |
|   (Web Client)    |               |   (Flask API)       |
+--------+----------+               +----------+----------+
         |                                     |
         v                                     v
+-------------------+               +---------------------+
|      guacd        |<------------->|   Docker Daemon     |
| (Protocol Server) |               +----------+----------+
+--------+----------+                          |
         |                          +----------+----------+
         |                          |    VNC Containers   |
         +------------------------->| (Firefox/Chromium)  |
                                    +---------------------+

         +-------------------+
         |    PostgreSQL     |  (Sessions, Users, Config)
         +-------------------+
```

### Components

| Service            | Description                                     |
| ------------------ | ----------------------------------------------- |
| **nginx**          | TLS termination, WebSocket proxy, rate limiting |
| **guacamole**      | Apache Guacamole web application                |
| **guacd**          | Guacamole protocol server (VNC gateway)         |
| **session-broker** | Python service managing container lifecycle     |
| **postgres**       | Database for Guacamole and broker state         |
| **VNC containers** | Per-user browser instances for webapp access    |

## Requirements

- Docker Engine 24.0+
- Docker Compose v2
- 4GB RAM minimum (8GB+ recommended for multiple users)
- `yq` for YAML processing ([installation](https://github.com/mikefarah/yq#install))

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/MaximeWewer/guacamole-session-broker.git
cd guacamole-session-broker

# Run interactive setup
./setup.sh
```

The setup script will:

- Prompt for database and admin passwords
- Configure SSL (self-signed or Let's Encrypt)
- Set URL routing mode (path, root, or subdomain)
- Generate `docker-compose.yml` and nginx configs
- Initialize PostgreSQL schema

### 2. Start services

```bash
docker compose up -d
```

### 3. Get Let's Encrypt certificate (if configured)

```bash
./init-letsencrypt.sh
```

### 4. Access Guacamole

- **Path mode**: `https://your-domain/guacamole/`
- **Root mode**: `https://your-domain/`
- **Subdomain mode**: `https://guacamole.your-domain/`

Default credentials: `guacadmin` / (password set during setup)

## Configuration

Configuration is split into three files in the `config/` directory:

### setup.yml - Infrastructure

Deployment settings used by `setup.sh` to generate Docker Compose:

```yaml
database:
  host: postgres
  port: 5432
  name: guacamole
  user: guacamole
  password: ""  # Set during setup

guacamole:
  admin_user: guacadmin
  admin_password: ""  # Set during setup

versions:
  guacamole: "1.6.0"
  guacd: "1.6.0"
  postgres: "15-alpine"
  nginx: "1.27-alpine"

ssl:
  mode: selfsigned  # or "letsencrypt"
  profile: modern   # or "intermediate" for TLSv1.2
  domain: ""
  email: ""

nginx:
  url_mode: path    # path, root, or subdomain
  base_path: "/guacamole/"

vault:
  enabled: false
  address: ""
  token: ""
```

### broker.yml - Runtime behavior

Container and lifecycle settings (hot-reloaded every 60 seconds):

```yaml
sync:
  interval: 10              # User sync frequency (seconds)
  ignored_users:
    - guacadmin
  sync_config_on_restart: true  # Update existing connections on restart

containers:
  image: ghcr.io/maximewewer/docker-browser-vnc:2026.01.2-chromium
  connection_name: "Virtual Desktop"
  network: guacamole_vnc-network
  memory_limit: "1g"
  shm_size: "256m"
  vnc_timeout: 30

lifecycle:
  persist_after_disconnect: true
  idle_timeout_minutes: 3
  force_kill_on_low_resources: true

pool:
  enabled: true
  init_containers: 2
  max_containers: 10
  batch_size: 3
  resources:
    min_free_memory_gb: 2.0
    max_total_memory_gb: 16.0
    max_memory_percent: 0.75

guacamole:
  force_home_page: true
  home_connection_name: "Home"
  recording:
    enabled: true
    path: "${HISTORY_PATH}/${HISTORY_UUID}"
    name: ""
    include_keys: false
    auto_create_path: true
```

### profiles.yml - User profiles

Group-based browser configurations:

```yaml
default:
  description: "Default profile"
  priority: 0
  homepage: "https://www.google.com"
  bookmarks:
    - name: "Google"
      url: "https://www.google.com"

developers:
  description: "Development team"
  priority: 10
  homepage: "https://github.com"
  bookmarks:
    - name: "GitHub"
      url: "https://github.com"
    - name: "Stack Overflow"
      url: "https://stackoverflow.com"
  autofill:
    - url: "https://github.com/login"
      username: "${GUAC_USERNAME}"
      password: "${vault:github_password}"
```

**Variable expansion:**

- `${GUAC_USERNAME}` - Guacamole username
- `${vault:key}` - Secret from Vault/OpenBao
- `${env:VAR}` - Environment variable

## VNC container images

This project uses [docker-browser-vnc](https://github.com/MaximeWewer/docker-browser-vnc), purpose-built containers for webapp access:

- **Minimal footprint** - Debian with Openbox, just enough for a browser
- **Firefox ESR or Chromium** - Enterprise-ready browsers
- **VNC server** - TigerVNC with clipboard support
- **Managed policies** - Pre-configured bookmarks, homepage, restrictions
- **Persistent profiles** - User data survives container restarts

Available images:

```
ghcr.io/maximewewer/docker-browser-vnc:2026.01.2-firefox
ghcr.io/maximewewer/docker-browser-vnc:2026.01.2-chromium
```

The broker automatically detects the browser type from the image name and applies the appropriate policy format.

## Container lifecycle

```
1. User logs into Guacamole
           |
           v
2. Broker detects new user (sync every 10s)
           |
           v
3. VNC container spawned from pool or created
           |
           v
4. Browser policies applied (bookmarks, homepage)
           |
           v
5. Guacamole connection updated with container IP
           |
           v
6. User connects to their virtual desktop
           |
           v
7. On disconnect:
   - persist=true:  Container kept running (idle timeout)
   - persist=false: Container destroyed immediately
           |
           v
8. Idle timeout reached: Container destroyed
```

### Pre-warming pool

The broker maintains a pool of ready containers to reduce connection latency:

```yaml
pool:
  enabled: true
  init_containers: 2    # Start 2 containers at broker startup
  max_containers: 10    # Maximum total containers
  batch_size: 3         # Create up to 3 per sync cycle
```

Resource limits prevent runaway container creation:

- `min_free_memory_gb`: Stop if free RAM below threshold
- `max_total_memory_gb`: Stop if total VNC memory exceeds limit
- `max_memory_percent`: Stop if VNC containers use > X% of RAM

## Session recording

Enable VNC session recording for audit/playback:

```yaml
guacamole:
  recording:
    enabled: true
    path: "${HISTORY_PATH}/${HISTORY_UUID}"  # Guacamole 1.5+ integration
    include_keys: false                       # Keyboard capture (privacy concern)
    auto_create_path: true
```

Recordings appear in Guacamole's connection history with playback controls.

## API reference

The broker exposes a REST API on port 5000 (internal) and `/broker/` (via nginx).

### Health & status

| Endpoint              | Method | Description                           |
| --------------------- | ------ | ------------------------------------- |
| `/health`             | GET    | Health check (database, vault status) |
| `/api/config`         | GET    | Broker configuration summary          |
| `/api/secrets/status` | GET    | Secrets provider status               |

### Sessions

| Endpoint             | Method | Description             |
| -------------------- | ------ | ----------------------- |
| `/api/sessions`      | GET    | List all sessions       |
| `/api/sessions/<id>` | DELETE | Force cleanup a session |

### User operations

| Endpoint                               | Method | Description                |
| -------------------------------------- | ------ | -------------------------- |
| `/api/users/<username>/provision`      | POST   | Provision VNC connection   |
| `/api/users/<username>/groups`         | GET    | Get user's groups & config |
| `/api/users/<username>/refresh-config` | POST   | Reload group configuration |
| `/api/users/<username>/bookmarks`      | POST   | Add bookmark for user      |
| `/api/users/<username>/profile`        | GET    | Get profile info           |

### Sync

| Endpoint    | Method | Description              |
| ----------- | ------ | ------------------------ |
| `/api/sync` | GET    | Sync service status      |
| `/api/sync` | POST   | Trigger manual user sync |

### Groups (database-stored)

| Endpoint             | Method | Description         |
| -------------------- | ------ | ------------------- |
| `/api/groups`        | GET    | List all groups     |
| `/api/groups/<name>` | GET    | Get group config    |
| `/api/groups/<name>` | PUT    | Create/update group |
| `/api/groups/<name>` | DELETE | Delete group        |

### Guacamole integration

| Endpoint                | Method | Description                |
| ----------------------- | ------ | -------------------------- |
| `/api/guacamole/groups` | GET    | List Guacamole user groups |

## Vault integration

For secure credential management, configure HashiCorp Vault or OpenBao:

```yaml
# config/setup.yml
vault:
  enabled: true
  address: "https://vault.example.com:8200"
  token: "hvs.xxx"  # Or use AppRole
  role_id: ""
  secret_id: ""
  mount: "secret"
  path: "guacamole/broker"
```

Store secrets:

```bash
vault kv put secret/guacamole/broker \
  github_password="xxx" \
  intranet_password="yyy"
```

Reference in profiles:

```yaml
autofill:
  - url: "https://github.com/login"
    password: "${vault:github_password}"
```

## SSL configuration

### Self-signed (development)

Generated automatically during setup. Browser will show security warning.

### Let's Encrypt (production)

```yaml
ssl:
  mode: letsencrypt
  profile: modern     # TLSv1.3 only
  domain: example.com
  email: admin@example.com
```

After `docker compose up -d`, run:

```bash
./init-letsencrypt.sh
```

Certificate auto-renews every 12 hours via certbot container.

### Security headers

nginx includes security headers:

- HSTS (2 years, preload)
- X-Frame-Options: SAMEORIGIN
- X-Content-Type-Options: nosniff
- CSP, Referrer-Policy, Permissions-Policy

## Troubleshooting

### Container won't start

Check resource limits:

```bash
docker exec session-broker curl -s http://localhost:5000/api/sync
```

### VNC connection timeout

Increase timeout:

```yaml
containers:
  vnc_timeout: 60
```

### Recording playback not working

Ensure guacd has write permissions:

```bash
docker exec guacd ls -la /recordings
```

### View broker logs

```bash
docker logs -f session-broker
```

### Force user sync

```bash
curl -X POST http://localhost/broker/sync
```

## Project structure

```
.
├── broker/                    # Session Broker (Python/Flask)
│   ├── api/                   # REST API endpoints
│   ├── config/                # Configuration loaders
│   ├── domain/                # Core business logic
│   ├── persistence/           # Database layer
│   └── services/              # Background services
├── config/                    # Configuration files
│   ├── setup.yml              # Infrastructure config
│   ├── broker.yml             # Runtime behavior
│   └── profiles.yml           # User profiles
├── nginx/                     # nginx configuration (generated)
├── initdb/                    # PostgreSQL init scripts (generated)
├── setup.sh                   # Interactive setup script
└── docker-compose.yml         # Docker Compose (generated)
```

## Related projects

- [docker-browser-vnc](https://github.com/MaximeWewer/docker-browser-vnc) - Lightweight browser containers with VNC (Firefox/Chromium)
- [Apache Guacamole](https://guacamole.apache.org/) - Clientless remote desktop gateway (RDP, VNC, SSH)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

For issues and feature requests, use [GitHub Issues](https://github.com/MaximeWewer/guacamole-session-broker/issues).
